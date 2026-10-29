"""Real C producer/router with a fresh funded synthetic catalog; no call permission."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from nexus.company.management.coding_intent import PreparedCodingRequest
from nexus.company.management.model_observations import ModelEligibilityObservation
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.core.llm.company_adapter_contracts import (
    CompanyModelRequest,
    JsonSchemaDocument,
    ModelTool,
)
from nexus.core.llm.company_pricing import quote_cost
from nexus.core.llm.company_registry import Capability, ModelRegistry
from nexus.core.llm.company_routing import (
    ModelPolicy,
    RoutingDeniedError,
    RoutingPlan,
    route_models,
)
from nexus.execution import coding_context
from nexus.execution.coding_context import (
    CODING_REQUEST_CAPABILITIES,
    prepare_content,
    route_prepared,
)
from nexus.execution.coding_services import CodingServices
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.journal_models import CompanyControl
from nexus.harness.model_input_estimator import FullContextInputEstimator
from nexus.tests.integration import nexus_coding_application_transport as transport
from nexus.tests.integration.nexus_coding_application_transport import priced_catalog
from nexus.tests.unit.coding_runtime_fixture import native_work, runtime_case
from nexus.tests.unit.test_coding_intent import runtime_graph
from nexus.tests.unit.test_nexus_coding_catalog import coding_case


def funded_case(
    root: Path,
) -> tuple[CodingServices, PreparedCodingRequest, ExecutionLease, CompanyControl]:
    """New synthetic prices before any registration, preserving held unaffordable fixtures."""
    original, source, lease = runtime_case(root)
    catalog = priced_catalog(original.management.catalog)
    factory, management, contexts = runtime_graph(root, source, catalog)
    services = replace(
        original,
        factory=factory,
        management=management,
        contexts=contexts,
        source_views=OwnerViewSources(management.artifacts, management.freshness),
        estimator=FullContextInputEstimator(catalog.models, original.recipe),
        max_output_tokens=1024,
    )
    prepared = prepare_content(services, lease, source.scope, source.context, source.binding)
    control = CompanyControl(
        company_id=prepared.request.company_id,
        policy_version="p1",
        price_version=catalog.models.pricebook_version,
        work_cap_usd=Decimal("0.1"),
        daily_cap_usd=Decimal(1),
    )
    return services, prepared, lease, control


def test_actual_c_producer_routes_whole_input_within_predeclared_slice(tmp_path: Path) -> None:
    services, prepared, lease, control = funded_case(tmp_path)
    assert prepared.request.tools == ()
    assert prepared.request.bounds.input_bound_kind == "model_input_ceiling_v1"
    assert prepared.input_estimate.whole_request is not None
    selected = route_prepared(
        services,
        prepared,
        native_work(services, lease),
        control,
        Decimal("0.1"),
        datetime.now(UTC),
    )
    assert selected.quote.amount_usd == Decimal("0.010507") < Decimal("0.1")
    assert selected.model.registry_id == prepared.request.registry_id


def capture_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[CodingServices, PreparedCodingRequest, ModelPolicy]:
    """Observe the real route, without replacing its eligibility or quotation result."""
    services, prepared, lease, control = funded_case(tmp_path)
    policies = []

    def observe(
        registry: ModelRegistry,
        policy: ModelPolicy,
        *,
        now: datetime,
        model_observations: tuple[ModelEligibilityObservation, ...] = (),
    ) -> RoutingPlan:
        policies.append(policy)
        return route_models(registry, policy, now=now, model_observations=model_observations)

    monkeypatch.setattr(coding_context, "route_models", observe)
    route_prepared(
        services, prepared, native_work(services, lease), control, Decimal("0.1"), datetime.now(UTC)
    )
    assert len(policies) == 1
    return services, prepared, policies[0]


@pytest.mark.parametrize("missing", ["code", "structured_output", "tools"])
def test_profile_and_actual_request_capability_checks_still_deny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: Capability
) -> None:
    services, prepared, policy = capture_policy(tmp_path, monkeypatch)
    registry = services.management.catalog.models
    changed = ModelRegistry.model_validate(
        registry.model_dump()
        | {
            "models": tuple(
                row.model_dump()
                | {
                    "capabilities": row.capabilities - {missing}
                    if row.registry_id == prepared.request.registry_id
                    else row.capabilities
                }
                for row in registry.models
            )
        }
    )
    with pytest.raises(RoutingDeniedError):
        route_models(changed, policy, now=datetime.now(UTC))


@pytest.mark.parametrize("available", [Decimal("0.010506"), Decimal(0)])
def test_real_c_quote_does_not_relax_the_predeclared_available_slice(
    tmp_path: Path, available: Decimal
) -> None:
    services, prepared, lease, control = funded_case(tmp_path)
    with pytest.raises(RoutingDeniedError):
        route_prepared(
            services, prepared, native_work(services, lease), control, available, datetime.now(UTC)
        )


def test_generic_whole_bound_explicit_tools_denial_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services, _, policy = capture_policy(tmp_path, monkeypatch)
    with pytest.raises(RoutingDeniedError):
        route_models(
            services.management.catalog.models,
            policy.model_copy(
                update={"required_capabilities": policy.required_capabilities | {"tools"}}
            ),
            now=datetime.now(UTC),
        )


def test_actual_prepared_request_and_full_estimator_still_reject_sdk_tools(tmp_path: Path) -> None:
    services, prepared, _, _ = funded_case(tmp_path)
    call = CompanyModelRequest.model_validate(
        prepared.request.model_dump()
        | {
            "output_schema": None,
            "tools": (
                ModelTool(
                    name="not_coding_content",
                    description="A tool schema cannot become a typed coding patch",
                    parameters=JsonSchemaDocument(schema_json='{"type":"object"}'),
                ),
            ),
        }
    )
    with pytest.raises(ValueError):
        services.estimator.estimate(call, services.management.catalog.models, services.recipe)
    with pytest.raises(ValueError):
        PreparedCodingRequest.model_validate_json(
            prepared.model_copy(update={"request": call}).model_dump_json()
        )


def test_original_unaffordable_fixture_is_still_denied(tmp_path: Path) -> None:
    services, prepared, lease = runtime_case(tmp_path)
    row = services.management.catalog.models.models[1]
    assert quote_cost(row.price, prepared.request.bounds, now=datetime.now(UTC)).amount_usd == (
        Decimal("1.049088")
    )
    control = CompanyControl(
        company_id=prepared.request.company_id,
        policy_version="p1",
        price_version=services.management.catalog.models.pricebook_version,
    )
    with pytest.raises(RoutingDeniedError):
        route_prepared(
            services,
            prepared,
            native_work(services, lease),
            control,
            Decimal("0.1"),
            datetime.now(UTC),
        )


def test_pre_r1_coder_quote_uses_the_actual_production_request_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, pending = capture_policy(tmp_path, monkeypatch)
    observed = []

    def observe(
        registry: ModelRegistry,
        policy: ModelPolicy,
        *,
        now: datetime,
        model_observations: tuple[ModelEligibilityObservation, ...] = (),
    ) -> RoutingPlan:
        if "synthetic-nexus-coder" in policy.allowed_models:
            observed.append(policy)
        return route_models(registry, policy, now=now, model_observations=model_observations)

    monkeypatch.setattr(transport, "route_models", observe)
    _, catalog = coding_case()
    upfront = transport.upfront_quotes(priced_catalog(catalog))
    coder = next(row for row in upfront if row.role == "coder")
    assert len(observed) == 1
    assert (
        observed[0].required_capabilities
        == pending.required_capabilities
        == (CODING_REQUEST_CAPABILITIES)
        == frozenset({"code", "structured_output"})
    )
    assert observed[0].profile == pending.profile == "engineering"
    assert coder.quote.amount_usd == Decimal("0.010507")
