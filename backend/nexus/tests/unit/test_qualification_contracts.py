"""Public qualification is not healthy model eligibility or profile-quality evidence."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import GoalRevisionRef
from nexus.core.llm.company_adapter_contracts import JsonSchemaDocument
from nexus.core.llm.company_adapters import _registration
from nexus.core.llm.company_pricing import PriceCard
from nexus.core.llm.company_registry import ModelHealth, ModelRegistration, ModelRegistry
from nexus.core.llm.qualification_contracts import (
    QualificationRecipe,
    _sdk_snapshot,
    qualification_parameters,
    qualification_request,
    recipe_hash,
)
from nexus.harness.journal_contracts import LedgerScope

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


def recipe() -> QualificationRecipe:
    target = ModelRegistration(
        registry_id="qualification-target",
        provider="openai",
        model_id="gpt-5.4-mini-2026-03-17",
        endpoint_id="openai.official.v1",
        api_family="openai_responses",
        enabled=False,
        capabilities=frozenset({"text", "structured_output"}),
        allowed_data=frozenset({"public"}),
        context_window=400000,
        max_output_tokens=128000,
        health=ModelHealth(status="unknown", checked_at=NOW, expires_at=NOW + timedelta(hours=1)),
        evaluations=(),
        price=PriceCard(
            version="qualification-prices-v1",
            as_of=NOW.date(),
            valid_from=NOW,
            valid_until=NOW + timedelta(hours=1),
            source_reference="public:reviewed-price",
            input_per_million=Decimal("0.25"),
            output_per_million=Decimal("2"),
            reasoning_semantics="included_in_output",
        ),
    )
    return QualificationRecipe(
        goal=GoalRevisionRef(
            company_id=UUID(int=1),
            goal_id=UUID(int=8),
            revision_id=UUID(int=9),
            version="v1",
            sha256="a" * 64,
        ),
        recipe_id="public-sdk-probe",
        revision="v1",
        case_id="echo-v1",
        target=target,
        registry_revision="unqualified-v1",
        qualification_target_sha256s=(canonical_sha256(target),),
        input_text="Return exactly the word READY.",
        request_output_cap=64,
        financial_input_ceiling=400000,
        financial_output_ceiling=128000,
        source_reference="public:frozen-probe",
        source_sha256="a" * 64,
        valid_until=NOW + timedelta(minutes=5),
        sdk_pins=_sdk_snapshot(),
    )


def scope() -> LedgerScope:
    return LedgerScope(
        company_id=UUID(int=1), task_id=UUID(int=2), trace_id=UUID(int=3), principal_id=UUID(int=4)
    )


def test_recipe_has_distinct_financial_and_request_caps_without_eligibility() -> None:
    value = recipe()
    call = qualification_request(value, scope(), action_id=UUID(int=5), request_id=UUID(int=6))
    assert call.bounds.max_output_tokens == 64 and value.financial_output_ceiling == 128000
    assert call.bounds.input_tokens == value.financial_input_ceiling == 400000
    assert call.tools == () and call.data_classification == "public"
    assert not value.target.enabled and value.target.health.status == "unknown"
    assert value.target.evaluations == ()
    parameters = qualification_parameters(value, call)
    assert parameters["recipe_sha256"] == recipe_hash(value)
    assert "input_text" not in parameters and "api_key" not in parameters


def test_real_schema_alias_survives_frozen_recipe_and_request_copy() -> None:
    schema = JsonSchemaDocument(
        schema_json='{"type":"object","properties":{"ready":{"type":"boolean"}},"required":["ready"],"additionalProperties":false}'
    )
    value = recipe().model_copy(update={"output_schema": schema})
    call = qualification_request(value, scope(), action_id=UUID(int=5), request_id=UUID(int=6))
    assert call.output_schema == schema


def test_qualification_target_stays_denied_by_actual_ordinary_model_gate() -> None:
    value = recipe()
    call = qualification_request(value, scope(), action_id=UUID(int=5), request_id=UUID(int=6))
    assert value.target.price is not None
    registry = ModelRegistry(
        company_id=scope().company_id,
        revision=value.registry_revision,
        pricebook_version=value.target.price.version,
        models=(value.target,),
    )
    with pytest.raises(ValueError, match="unavailable"):
        _registration(registry, call, NOW)


@pytest.mark.parametrize("fault", ["enabled", "healthy", "input", "output", "private"])
def test_changed_unqualified_recipe_or_insufficient_financial_bound_denied(fault: str) -> None:
    value = recipe()
    data = value.model_dump(mode="json")
    if fault == "enabled":
        data["target"]["enabled"] = True
    elif fault == "healthy":
        data["target"]["health"]["status"] = "healthy"
    elif fault == "private":
        data["target"]["allowed_data"] = ["internal"]
    else:
        data[f"financial_{fault}_ceiling"] = 64
    with pytest.raises(ValidationError):
        QualificationRecipe.model_validate(data)
