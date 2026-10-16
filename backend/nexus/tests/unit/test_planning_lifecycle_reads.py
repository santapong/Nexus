"""Concrete reader/replay orchestration; protected native delivery is supplied."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import ContextAuthorityState, ContextLimits
from nexus.company.brain.context_render import render_context
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.planning_content import PlanningContent, PlanningTask
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.management.planning_origin_contracts import PlanningOriginRef
from nexus.company.management.planning_proposal_bridge import map_content
from nexus.company.management.planning_source_reader import PlanningSource
from nexus.execution import planning_lifecycle_reads as module
from nexus.execution.planning_lifecycle_bindings import PlanningBundle
from nexus.execution.planning_lifecycle_contracts import PlanningLifecycleRead
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.test_planning_lifecycle import lifecycle_case, native_bundle, scope, witness


def source_for(bundle: PlanningBundle) -> PlanningSource:
    """Typed source fixture only; core PlanningSourceReader tests own actual file/native proof."""
    child = bundle.base.payload.children[0].binding
    data = PlanningContent(
        tasks=tuple(
            PlanningTask(
                key=slot.key,
                title="Review Nexus " + slot.key,
                description="Cite Nexus evidence and preserve native gates.",
                acceptance=("Owner reviews the exact proposal",),
                depends_on=(),
                evidence_ids=(),
            )
            for slot in bundle.reader.template.slots
        ),
        questions=("Owner confirms remaining requirements",),
    )
    context = render_context(
        BrainReadScope(
            company_id=child.company_id,
            workspace_id=child.workspace_id,
            principal_id=child.actor_id,
            operation_id=uuid5(child.task_id, "audit"),
            trace_id=child.trace_id,
            task_id=child.task_id,
            task_trace_id=child.trace_id,
            actor_id=child.actor_id,
        ),
        ContextAuthorityState(
            company_id=child.company_id,
            mandate_version="fixture",
            policy_version="fixture",
            budget_version="fixture",
            role_system_text="Describe Nexus work; no permission.",
            data_classification="internal",
            model_profile="reasoning",
        ),
        ContextLimits(policy_version="fixture"),
        (),
        (),
        question="Nexus planning candidate",
    )
    origin = PlanningOriginRef(
        company_id=child.company_id,
        goal=bundle.base.payload.goal,
        source_plan_id=bundle.base.plan_id,
        source_plan_revision_id=bundle.base.plan_revision_id,
        task_id=child.task_id,
        action_id=uuid5(child.task_id, "action"),
        request_id=uuid5(child.task_id, "request"),
        receipt_id=uuid5(child.task_id, "receipt"),
        artifact_id=uuid5(child.task_id, "artifact"),
        artifact_sha256="a" * 64,
        request_sha256="b" * 64,
        context_manifest_sha256=canonical_sha256(context.manifest),
        content_sha256=canonical_sha256(data),
        mapping_revision=bundle.reader.template.revision,
        mapping_sha256=canonical_sha256(bundle.reader.template),
    )
    return PlanningSource(origin, data, context.manifest, datetime.now(UTC))


@pytest.mark.parametrize("fault", [None, "source", "origin", "window", "target"])
async def test_stored_formal_target_replay_uses_same_concrete_reader_and_original_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str | None,
) -> None:
    life = lifecycle_case(tmp_path)
    owner = await witness(life)
    bundle = await native_bundle(life, monkeypatch)
    source = source_for(bundle)
    payload = map_content(source.content, source.origin, bundle.reader.template)
    digest = canonical_sha256(payload)
    target = PlanRevision(
        company_id=life.config.admission.company_id,
        plan_id=bundle.base.plan_id,
        plan_revision_id=uuid5(bundle.base.plan_id, f"plan:2:{digest}"),
        revision=2,
        sha256=digest,
        payload=payload,
        proposed_by=owner.identity.principal_id,
        recorded_at=datetime.now(UTC),
    )
    bundle = replace(bundle, target=target, head_revision_id=target.plan_revision_id)
    fake = cast(AsyncSession, MagicMock(spec=AsyncSession))
    stored = ManagementPlanRevision(
        company_id=target.company_id,
        plan_id=target.plan_id,
        plan_revision_id=target.plan_revision_id,
        revision=target.revision,
        goal_id=target.payload.goal.goal_id,
        goal_revision_id=target.payload.goal.revision_id,
        mandate_revision_id=target.payload.mandate.revision_id,
        sha256=target.sha256,
        snapshot_json=target.payload.model_dump_json(),
        proposed_by=target.proposed_by,
        recorded_at=target.recorded_at,
    )
    cast(MagicMock, fake).get = AsyncMock(return_value=None if fault == "target" else stored)

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        yield fake, MagicMock(), datetime.now(UTC)

    async def observe(*args: object) -> int:
        if fault == "source":
            raise ValueError("Actual source delivery denied before body")
        return cast(int, args[-1])

    monkeypatch.setattr(module, "management_owner_transaction", transaction)
    monkeypatch.setattr(module, "owner_locked", observe)
    monkeypatch.setattr(module, "db_clock", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    load = AsyncMock(return_value=source)
    monkeypatch.setattr(bundle.reader, "_load_locked", load)
    end = clock_us() - 1 if fault == "window" else clock_us() + 30_000_000
    action = UUID(int=999) if fault == "origin" else source.origin.action_id
    if fault is not None:
        with pytest.raises((ValueError, TimeoutError)):
            await module.replay_target(life, bundle, scope(life), owner, action, end)
        if fault in {"source", "origin"}:
            load.assert_not_awaited()
    else:
        actual, actual_end = await module.replay_target(
            life, bundle, scope(life), owner, action, end
        )
        assert actual == target and actual_end <= end
        assert load.await_args is not None
        assert load.await_args.args[-2] == target.plan_revision_id
        assert bundle.plans.planning_reader is bundle.reader


async def test_replay_dispatch_does_not_refresh_actor_or_reissue_native_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.execution import planning_lifecycle as lifecycle_module
    from nexus.execution.dbos_contracts import SegmentCommand
    from nexus.execution.planning_dispatch import PlanningDispatchRecord

    life = lifecycle_case(tmp_path)
    owner = await witness(life)
    bundle = await native_bundle(life, monkeypatch)
    end = clock_us() + 30_000_000
    monkeypatch.setattr(life, "_bundle", AsyncMock(return_value=(bundle, end)))
    actor = bundle.base.payload.children[0].binding
    command = SegmentCommand(
        company_id=actor.company_id,
        task_id=actor.task_id,
        trace_id=actor.trace_id,
        actor_id=actor.actor_id,
        workspace_id=actor.workspace_id,
        run_id=actor.run_id,
        action_id=uuid5(actor.task_id, "action"),
        segment_id=uuid5(actor.task_id, "segment"),
    )
    record = PlanningDispatchRecord(
        command=command, workflow_id=command.workflow_id, disposition="existing"
    )
    monkeypatch.setattr(module, "existing_dispatch", AsyncMock(return_value=(record, end)))
    monkeypatch.setattr(life, "_owner", AsyncMock(return_value=end))
    fresh = AsyncMock(side_effect=AssertionError("No new native dispatch"))
    monkeypatch.setattr(lifecycle_module, "dispatch_action", fresh)
    credential = AsyncMock(side_effect=AssertionError("No actor refresh for metadata replay"))
    monkeypatch.setattr(type(life.services.identities), "current", credential)
    value = await life.dispatch(scope(life), owner, command.action_id, "a" * 64, end_us=end)
    assert value.value == record and isinstance(value, PlanningLifecycleRead)
    fresh.assert_not_awaited()
    credential.assert_not_awaited()


async def test_status_is_native_metadata_without_actor_refresh_or_private_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.management.plan_models import ManagementPlanHead
    from nexus.company.management.plan_registration import registration
    from nexus.execution.runtime_contracts import AttemptQuota
    from nexus.execution.runtime_models import ExecutionWork
    from nexus.execution.runtime_support import registration_digest

    life = lifecycle_case(tmp_path)
    owner = await witness(life)
    bundle = await native_bundle(life, monkeypatch)
    slot = life.config.admission.slots[0]
    binding = slot.child.binding
    registered = registration(binding, slot.work, slot.child.quota)
    work = ExecutionWork(
        company_id=binding.company_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        actor_id=binding.actor_id,
        workspace_id=binding.workspace_id,
        run_id=binding.run_id,
        workflow_name=binding.workflow_name,
        workflow_version=binding.workflow_version,
        model_profile=binding.model_profile,
        model_registry_version=binding.model_registry_version,
        parent_task_id=life.config.admission.procedure.binding.task_id,
        registration_json=registered.model_dump_json(),
        registration_hash=registration_digest(registered),
        state="eligible",
        fence=0,
        segment_number=0,
        worker_id=None,
        lease_principal_id=None,
        lease_until=None,
        segment_id=None,
        waiting_action_id=None,
        **{
            f"{kind}_{suffix}": 0
            for kind in AttemptQuota.model_fields
            for suffix in ("used", "delegated")
        },
        **{f"{kind}_limit": getattr(slot.child.quota, kind) for kind in AttemptQuota.model_fields},
    )
    fake = MagicMock(spec=AsyncSession)
    fake.get = AsyncMock(side_effect=lambda model, key: work if model is ExecutionWork else None)
    scalar = MagicMock()
    scalar.all.return_value = []
    fake.scalars = AsyncMock(return_value=scalar)
    head = ManagementPlanHead(current_revision_id=bundle.base.plan_revision_id, state="approved")
    monkeypatch.setattr(module, "stored_plans", AsyncMock(return_value=(bundle.base, None, head)))

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        yield cast(AsyncSession, fake), CompanyControl(), datetime.now(UTC)

    async def observe(*args: object) -> int:
        return cast(int, args[-1])

    monkeypatch.setattr(module, "management_owner_transaction", transaction)
    monkeypatch.setattr(module, "owner_locked", observe)
    monkeypatch.setattr(module, "db_clock", AsyncMock(side_effect=lambda _: datetime.now(UTC)))
    credential = AsyncMock(side_effect=AssertionError("Metadata cannot refresh actor JWT"))
    body = AsyncMock(side_effect=AssertionError("Status cannot read private input"))
    monkeypatch.setattr(type(life.services.identities), "current", credential)
    monkeypatch.setattr(life.services.prepared, "load_owner", body)
    result = await life.status(
        scope(life), owner, life.config.goal.goal_id, end_us=clock_us() + 30_000_000
    )
    assert result.value.bootstrap and result.value.current_state == "approved"
    assert result.value.work_state == "eligible" and result.value.action_id is None
    assert result.value.native_state is None and not result.value.company_completed
    credential.assert_not_awaited()
    body.assert_not_awaited()


async def test_foreign_genuine_owner_witness_denied_before_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    life = lifecycle_case(tmp_path)
    foreign = await witness(life, foreign=True)
    observation = AsyncMock()
    monkeypatch.setattr(module, "owner_locked", observation)
    with pytest.raises(ValueError, match="owner witness"):
        await life.status(
            scope(life), foreign, life.config.goal.goal_id, end_us=clock_us() + 30_000_000
        )
    observation.assert_not_awaited()
