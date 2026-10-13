"""Actual non-superuser PG plus pinned offline SDK context-to-effect authorization."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx2
import pytest
from pydantic import JsonValue, TypeAdapter
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.context import AssembledContext
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, ModelRequestCancelledError
from nexus.core.llm.company_pricing import quote_cost
from nexus.core.llm.company_registry import ModelRegistry
from nexus.harness.model_authorizer_contracts import InputEstimate, ModelInputRecipe
from nexus.harness.model_evidence import FileModelEvidenceStore
from nexus.settings import settings
from nexus.tests.brain_model_gate_support import (
    BrainGateCase,
    CountingEstimator,
    authorizer,
    build_case,
    ledger_facts,
)
from nexus.tests.integration.test_company_brain_retrieval import identity as brain_identity
from nexus.tests.integration.test_company_brain_retrieval import scope as brain_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, migrate
from nexus.tests.integration.test_company_model_authorizer import offline_adapter, recipe
from nexus.tests.unit.test_company_provider_conformance import response


@pytest.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    if not settings.company_test_database_url:
        pytest.skip("Explicit private Brain model gate database is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_brain_model_gate"
    assert settings.company_test_database_url != settings.database_url
    engine = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    async with engine.begin() as connection:
        await connection.run_sync(migrate, "upgrade")
    try:
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await engine.dispose()


def _strings(value: JsonValue) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return set().union(*(_strings(child) for child in value))
    if isinstance(value, dict):
        return set().union(*(_strings(child) for child in value.values()))
    return set()


async def revoke(case: BrainGateCase) -> None:
    await ResourceAccessStore(case.factory).change(
        brain_scope(OWNER),
        brain_identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=UUID(int=101)),
            principal_id=ACTOR,
            active=False,
            expected_generation=1,
        ),
    )


@pytest.mark.parametrize("expires", ["source", "approval"])
async def test_authority_expiring_during_estimation_cannot_issue_or_mutate_ledger(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, expires: str
) -> None:
    case = await build_case(
        factory,
        tmp_path,
        source_grant_seconds=2 if expires == "source" else None,
        approval_seconds=2 if expires == "approval" else None,
    )

    class SlowEstimator(CountingEstimator):
        def estimate(
            self, call: CompanyModelRequest, registry: ModelRegistry, recipe: ModelInputRecipe
        ) -> InputEstimate:
            # Deliberately bounded blocking work inside the synchronous fixture
            # estimator crosses the legitimate grant's wall-clock expiry.
            time.sleep(2.3)
            return super().estimate(call, registry, recipe)

    case = replace(case, estimator=SlowEstimator())
    before = await ledger_facts(case)
    wires: list[httpx2.Request] = []

    def handle(wire: httpx2.Request) -> httpx2.Response:
        wires.append(wire)
        return httpx2.Response(200, json=response("openai"))

    result = await offline_adapter(
        authorizer(case), case.registry, httpx2.MockTransport(handle)
    ).request_once(case.call, now=datetime.now(UTC))
    assert result.status == "denied" and result.billing == "not_issued" and not wires
    assert case.estimator.calls == 1 and await ledger_facts(case) == before


async def test_whole_assembled_request_uses_one_actual_sdk_call_and_exact_owner_preconditions(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await build_case(factory, tmp_path)
    gate = authorizer(case)
    wires: list[httpx2.Request] = []

    def handle(wire: httpx2.Request) -> httpx2.Response:
        wires.append(wire)
        return httpx2.Response(200, json=response("openai"))

    adapter = offline_adapter(gate, case.registry, httpx2.MockTransport(handle))
    result = await adapter.request_once(case.call, now=datetime.now(UTC))
    assert result.status == "response" and result.billing == "known" and len(wires) == 1
    body: JsonValue = TypeAdapter(JsonValue).validate_json(wires[0].content)
    assert {case.context.system_text, case.context.input_text} <= _strings(body)
    assert "MODEL_CONTEXT_SENTINEL" in case.context.input_text and not case.call.tools
    recorded = await gate.record_result(case.call, result)
    assert recorded.billing == "known" and recorded.actual_usd is not None
    evidence = await FileModelEvidenceStore(case.artifacts).load(recorded.artifact)
    assert evidence.request.input_text == case.context.input_text
    assert evidence.request.system_text == case.context.system_text
    assert case.context.manifest.token_qualification == "unavailable"
    facts = await ledger_facts(case)
    assert facts["used"] == facts["attempts"] == facts["intents"] == 1
    assert facts["tool_used"] == 0 and case.estimator.calls == 1
    second = await adapter.request_once(case.call, now=datetime.now(UTC))
    assert second.status == "denied" and second.billing == "not_issued" and len(wires) == 1
    assert await ledger_facts(case) == facts
    tmp_path.joinpath("context.json").write_text(case.context.model_dump_json(indent=2))
    tmp_path.joinpath("actual-sdk-request.json").write_text(json.dumps(body, indent=2))


@pytest.mark.parametrize("change", ["revoke", "head", "authority"])
async def test_changed_current_context_denies_before_sdk_intent_attempt_or_budget_mutation(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, change: str
) -> None:
    case = await build_case(factory, tmp_path)
    gate, before = authorizer(case), await ledger_facts(case)
    wires: list[httpx2.Request] = []
    if change == "revoke":
        await revoke(case)
    elif change == "head":
        raw = b"MODEL_CONTEXT_SENTINEL readiness evidence updated"
        artifact = case.command.artifact.model_copy(
            update={
                "artifact_revision_id": UUID(int=104),
                "revision": "2",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "byte_length": len(raw),
            }
        )
        await case.ingestion.ingest(
            brain_scope(OWNER),
            brain_identity(OWNER),
            case.command.model_copy(
                update={
                    "revision": "2",
                    "artifact": artifact,
                    "expected_previous_revision_id": case.context.manifest.source_heads[
                        0
                    ].current.source_revision_id,
                }
            ),
        )
    else:
        case.provider.mandate = "mandate-v2"

    def handle(wire: httpx2.Request) -> httpx2.Response:
        wires.append(wire)
        return httpx2.Response(200, json=response("openai"))

    result = await offline_adapter(gate, case.registry, httpx2.MockTransport(handle)).request_once(
        case.call, now=datetime.now(UTC)
    )
    assert result.status == "denied" and result.billing == "not_issued" and not wires
    assert await ledger_facts(case) == before and case.estimator.calls == 0


@pytest.mark.parametrize(
    "splice", ["input", "system", "scope", "identity", "class", "recipe", "missing_recipe"]
)
async def test_request_scope_identity_class_and_explicit_recipe_splices_cannot_start_model(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, splice: str
) -> None:
    case = await build_case(factory, tmp_path)
    before = await ledger_facts(case)
    with pytest.raises(ValueError):
        if splice == "input":
            authorizer(case, call=case.call.model_copy(update={"input_text": "spliced body"}))
        elif splice == "system":
            authorizer(case, call=case.call.model_copy(update={"system_text": "spliced system"}))
        elif splice == "scope":
            authorizer(
                case,
                brain_scope=case.brain_scope.model_copy(update={"task_trace_id": UUID(int=999)}),
            )
        elif splice == "identity":
            authorizer(case, signed=brain_identity(OWNER))
        elif splice == "class":
            authorizer(case, call=case.call.model_copy(update={"data_classification": "public"}))
        elif splice == "recipe":
            authorizer(case, bound_recipe=recipe().model_copy(update={"revision": "other"}))
        else:
            manifest = case.context.manifest.model_copy(
                update={
                    "authority": case.context.manifest.authority.model_copy(
                        update={"model_recipe": None, "model_recipe_revision": None}
                    )
                }
            )
            authorizer(
                case,
                context=AssembledContext.model_validate_json(
                    case.context.model_copy(update={"manifest": manifest}).model_dump_json()
                ),
            )
    assert await ledger_facts(case) == before and case.estimator.calls == 0


@pytest.mark.parametrize("invalid", ["missing_preconditions", "overdeclared_class"])
async def test_actual_context_conditions_and_maximum_source_classification_are_required(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, invalid: str
) -> None:
    classification: Literal["restricted", "internal"] = (
        "restricted" if invalid == "overdeclared_class" else "internal"
    )
    case = await build_case(
        factory,
        tmp_path,
        include_preconditions=invalid != "missing_preconditions",
        declared_classification=classification,
    )
    gate, before = authorizer(case, classification=classification), await ledger_facts(case)
    quote = quote_cost(case.registry.models[0].price, case.call.bounds, now=datetime.now(UTC))
    with pytest.raises(ValueError):
        await gate.claim(case.call, quote)
    assert await ledger_facts(case) == before and case.estimator.calls == 0


@pytest.mark.parametrize("outcome", ["known", "cancelled"])
async def test_issued_outcome_survives_source_revocation_without_reissue_or_refund(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, outcome: str
) -> None:
    case = await build_case(factory, tmp_path)
    wires: list[httpx2.Request] = []
    initial = await ledger_facts(case)
    gate = authorizer(case)

    async def handle(wire: httpx2.Request) -> httpx2.Response:
        wires.append(wire)
        await revoke(case)
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        return httpx2.Response(200, json=response("openai"))

    adapter = offline_adapter(gate, case.registry, httpx2.MockTransport(handle))
    if outcome == "cancelled":
        with pytest.raises(ModelRequestCancelledError) as caught:
            await adapter.request_once(case.call, now=datetime.now(UTC))
        result = caught.value.result
    else:
        result = await adapter.request_once(case.call, now=datetime.now(UTC))
    recorded = await gate.record_result(case.call, result)
    facts = await ledger_facts(case)
    assert facts["used"] == facts["attempts"] == facts["intents"] == len(wires) == 1
    assert facts["tool_used"] == 0 and recorded.billing == (
        "unknown" if outcome == "cancelled" else "known"
    )
    if outcome == "cancelled":
        assert recorded.stop_required and recorded.actual_usd is None
        assert facts["hold"][:3] == ("unknown", Decimal("0.020000"), None)
        assert facts["hold"][1:] == initial["hold"][1:]
        assert facts["work_budget"] == initial["work_budget"]
        assert facts["daily_budget"] == initial["daily_budget"]
    else:
        assert recorded.actual_usd is not None and recorded.actual_usd > 0
        assert facts["hold"][:3] == ("reconciled", Decimal("0.020000"), recorded.actual_usd)
    second = await adapter.request_once(case.call, now=datetime.now(UTC))
    assert second.status == "denied" and len(wires) == 1 and await ledger_facts(case) == facts
