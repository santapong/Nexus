"""Protected-file owner disclosure on supplied native/source delivery; no SQL/provider proof."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.planning_intent import (
    PreparedPlanningRequest,
    prepare_planning_request,
    require_planning_registry,
)
from nexus.company.management.planning_native_facts import clock_us
from nexus.core.llm.company_adapter_contracts import request_hash
from nexus.core.llm.company_pricing import TokenBounds
from nexus.core.llm.company_registry import ModelRegistration, ModelRegistry
from nexus.execution import planning_owner_reads as module
from nexus.execution.planning_owner_reads import PlanningInputReader, PlanningInputReview
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_authorizer_contracts import InputEstimate, WholeRequestInputCeiling
from nexus.tests.unit.test_company_planning_consumer import planning_registry
from nexus.tests.unit.test_planning_prepared_store import Fixture, pending, setup


async def case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_proof: bool = True,
) -> tuple[Fixture, PlanningInputReader]:
    """Actual complete protected bytes; all registry/authority facts are synthetic supplied data."""
    f = setup(tmp_path, monkeypatch)
    registry = planning_registry("openai")
    call = f.prepared.request.model_copy(
        update={
            "bounds": TokenBounds(
                input_tokens=registry.models[0].context_window,
                max_output_tokens=256,
                input_bound_kind="model_input_ceiling_v1",
            )
        }
    )
    recipe = f.prepared.input_recipe
    estimate = InputEstimate(
        request_hash=request_hash(call),
        registry_id=call.registry_id,
        registry_revision=call.registry_revision,
        recipe_id=recipe.recipe_id,
        recipe_revision=recipe.revision,
        input_text_tokens=0,
        system_text_tokens=0,
        tool_schema_tokens=0,
        output_schema_tokens=0,
        sdk_overhead_tokens=0,
        whole_request=WholeRequestInputCeiling(
            tokens=call.bounds.input_tokens,
            registry_sha256=canonical_sha256(registry),
            model_sha256=canonical_sha256(registry.models[0]),
            recipe_sha256=canonical_sha256(recipe),
            conformance_reference=recipe.conformance_reference,
        ),
    )
    old = f.prepared
    f.prepared = prepare_planning_request(
        call,
        old.context,
        old.binding,
        scope=old.scope,
        input_recipe=recipe,
        input_estimate=estimate if with_proof else None,
    )
    end = clock_us() + 30_000_000
    ref = await f.store.save(f.scope, f.owner, f.prepared, end_us=end)
    pending(f, ref)
    control = CompanyControl(
        company_id=f.scope.company_id,
        owner_id=f.owner.principal_id,
        paused=False,
        policy_version="policy-v1",
        price_version=call.price_version,
        work_cap_usd=1,
        daily_cap_usd=5,
    )
    f.rows[CompanyControl] = control

    @asynccontextmanager
    async def transaction(
        factory: async_sessionmaker[AsyncSession],
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        *,
        allow_paused: bool = False,
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        assert factory is f.store.factory
        assert scope.principal_id == identity.principal_id
        yield f.session, control, datetime.now().astimezone()

    monkeypatch.setattr(module, "management_owner_transaction", transaction)
    return f, PlanningInputReader(f.store, registry)


async def test_owner_get_returns_complete_bound_input_and_native_maximum_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f, reader = await case(tmp_path, monkeypatch)
    value = await reader.input(
        f.scope, f.owner, f.prepared.request.action_id, end_us=clock_us() + 30_000_000
    )
    assert value.prepared == f.prepared
    assert value.provider == "openai" and value.model_id == reader.registry.models[0].model_id
    assert value.proposal_sha256 == cast(JournalAction, f.rows[JournalAction]).proposal_hash
    assert value.request_sha256 == f.prepared.request_sha256
    assert value.maximum_reservation_usd == Decimal("0.01")
    assert value.company_completed is value.execution_permitted is False
    assert PlanningInputReview.model_validate_json(value.model_dump_json(by_alias=True)) == value
    assert str(tmp_path) not in value.model_dump_json(by_alias=True)
    assert cast(JournalAction, f.rows[JournalAction]).consumed_at is None
    cast(MagicMock, f.session).add.assert_not_called()


@pytest.mark.parametrize(
    "change",
    ("company", "native-hash", "registry-id", "request-hash", "registry-revision", "factory"),
)
async def test_metadata_rejects_splices_before_any_protected_body_materializes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    f, reader = await case(tmp_path, monkeypatch)
    row = cast(JournalAction, f.rows[JournalAction])
    if change == "company":
        row.company_id = UUID(int=999)
    elif change == "native-hash":
        row.proposal_hash = "f" * 64
    elif change in {"registry-id", "request-hash"}:
        from nexus.company.contracts.actions import ActionProposal

        action = ActionProposal.model_validate_json(row.proposal_json)
        key = "registry_id" if change == "registry-id" else "request_hash"
        changed = action.model_copy(
            update={
                "parameters": action.parameters
                | {key: "absent" if key == "registry_id" else "f" * 64}
            }
        )
        row.proposal_json, row.proposal_hash = changed.model_dump_json(), action_hash(changed)
    elif change == "registry-revision":
        object.__setattr__(
            reader, "registry", reader.registry.model_copy(update={"revision": "other"})
        )
    else:
        f.store.factory = cast(async_sessionmaker[AsyncSession], MagicMock())
    read = MagicMock(side_effect=AssertionError("Private bytes read before metadata rejection"))
    monkeypatch.setattr(f.store.blobs, "read", read)
    with pytest.raises(ValueError):
        await reader.input(
            f.scope, f.owner, f.prepared.request.action_id, end_us=clock_us() + 30_000_000
        )
    read.assert_not_called()


@pytest.mark.parametrize("field", ("model_id", "endpoint_id", "provider"))
async def test_restart_same_version_cannot_relabel_the_frozen_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    f, original = await case(tmp_path, monkeypatch)
    model = original.registry.models[0].model_copy(
        update={field: "google" if field == "provider" else "other"}
    )
    changed = ModelRegistry.model_construct(
        **(original.registry.model_dump() | {"models": (model,)})
    )
    with pytest.raises(ValueError):
        reader = PlanningInputReader(f.store, changed)
        await reader.input(
            f.scope, f.owner, f.prepared.request.action_id, end_us=clock_us() + 30_000_000
        )


async def test_current_source_denial_and_cpu_expiry_return_no_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f, reader = await case(tmp_path, monkeypatch)
    end = clock_us() + 30_000_000
    f.revoked = True
    with pytest.raises(ValueError):
        await reader.input(f.scope, f.owner, f.prepared.request.action_id, end_us=end)
    f.revoked = False
    original = require_planning_registry

    def slow(prepared: PreparedPlanningRequest, registry: ModelRegistry) -> ModelRegistration:
        result = original(prepared, registry)
        monkeypatch.setattr("nexus.company.management.planning_native_facts.clock_us", lambda: end)
        return result

    monkeypatch.setattr(module, "require_planning_registry", slow)
    with pytest.raises(TimeoutError):
        await reader.input(f.scope, f.owner, f.prepared.request.action_id, end_us=end)
    assert not f.store.pending_owners()


async def test_legacy_input_is_not_relabelled_as_a_fresh_frozen_model_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f, reader = await case(tmp_path, monkeypatch, with_proof=False)
    assert f.prepared.input_estimate is None
    with pytest.raises(ValueError, match="fingerprint"):
        await reader.input(
            f.scope, f.owner, f.prepared.request.action_id, end_us=clock_us() + 30_000_000
        )
