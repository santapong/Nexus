"""Fresh Nexus E/EV/report/sender gates use ACTUAL begin; supplied existing authority/SQL only."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.tests.unit.nexus_intent_fixture import boundary


@pytest.mark.parametrize("index", [0, 1, 2, 3, 4, 5])
@pytest.mark.parametrize("mode", ["missing", "noop"])
async def test_none_and_protocol_noop_deny_before_hold_counter_attempt_intent(
    monkeypatch: pytest.MonkeyPatch,
    index: int,
    mode: str,
) -> None:
    value = boundary(index)
    store = value.install(monkeypatch)
    supplied: BeforeIntentCheck | None = AsyncMock() if mode == "noop" else None
    with pytest.raises(ExecutionDeniedError):
        await store.begin(
            value.lease,
            value.identity,
            value.action.id,
            kind="model_requests" if index == 0 else "tool_attempts",
            before_intent=supplied,
        )
    assert value.added == [] and value.work.tool_attempts_used == 0 and value.hold.state == "held"
    value.move.assert_not_awaited()
    value.session.flush.assert_not_awaited()
    if supplied is not None:
        assert isinstance(supplied, AsyncMock)
        supplied.validate.assert_not_awaited()


@pytest.mark.parametrize("index", [0, 1, 2, 3, 4, 5])
async def test_known_unknown_issued_history_returns_before_new_guard_or_authority(
    monkeypatch: pytest.MonkeyPatch,
    index: int,
) -> None:
    value = boundary(index)
    store = value.install(monkeypatch)
    value.known()
    before = value.previous
    result = await store.begin(
        value.lease,
        value.identity,
        value.action.id,
        kind="model_requests" if index == 0 else "tool_attempts",
        before_intent=None,
    )
    assert not result.permit_external_call and result.record.intent_fence == 1
    assert (
        value.previous is before
        and (value.work.model_requests_used if index == 0 else value.work.tool_attempts_used) == 1
        and value.hold.state == "unknown"
    )
    assert not value.added
    value.move.assert_not_awaited()
    value.session.flush.assert_not_awaited()


async def test_stale_original_lease_denies_before_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    value = boundary()
    store = value.install(monkeypatch)
    noop = AsyncMock()
    with pytest.raises(ExecutionDeniedError, match="lease"):
        await store.begin(
            value.lease.model_copy(update={"fence": 2}),
            value.identity,
            value.action.id,
            before_intent=noop,
        )
    noop.validate.assert_not_awaited()
    assert not value.added


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "factory",
        "catalog",
        "credential",
        "parent",
        "original-source",
        "expired",
        "model-expired",
    ],
)
async def test_real_builder_guard_signed_witness_and_source_parent_checks_stay_original(
    tmp_path: "Path",
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    from datetime import timedelta
    from unittest.mock import MagicMock

    from nexus.builder.contained_intent_check import ContainedParentIntentCheck
    from nexus.builder.nexus_source_guard import NexusBuilderSourceGuard
    from nexus.builder.source_guard import BuilderSourceGuard
    from nexus.tests.contained_observer_fixture import parent
    from nexus.tests.unit.nexus_builder_intent_fixture import builder_check
    from nexus.tests.unit.nexus_cycle_fixture import key

    value = boundary()
    store = value.install(monkeypatch)
    check = await builder_check(value, store, tmp_path)
    source, parent_check = check._checks
    assert isinstance(source, BuilderSourceGuard) and isinstance(
        parent_check, ContainedParentIntentCheck
    )
    called = []

    async def source_read(self: BuilderSourceGuard, *args: object) -> None:
        assert isinstance(self, NexusBuilderSourceGuard) and self.containment is not None
        called.append("source")
        self.deadlines = (value.lease.expires_at,)
        if fault == "factory":
            self.artifacts.factory = MagicMock()
        elif fault == "catalog":
            self.catalog = self.catalog.model_copy()
        elif fault == "credential":
            self.credential = MagicMock()
        elif fault == "parent":
            self.containment.expectation = self.containment.expectation.model_copy(
                update={"run_id": key("foreign")}
            )
        elif fault == "original-source":
            self._original.source = type(self.source)(tmp_path / "other", self.source.metadata)
        elif fault == "expired":
            value.now = value.lease.expires_at + timedelta(microseconds=1)
        elif fault == "model-expired":
            value.now = value.catalog.models.models[0].health.expires_at + timedelta(microseconds=1)

    async def parent_read(self: ContainedParentIntentCheck, *args: object) -> None:
        called.append("parent")
        assert self.services.deadline is not None
        self.observed = parent().model_copy(update={"deadline_us": self.services.deadline.end_us})

    monkeypatch.setattr(BuilderSourceGuard, "validate", source_read)
    monkeypatch.setattr(ContainedParentIntentCheck, "validate", parent_read)
    if fault == "none":
        result = await store.begin(
            value.lease, value.identity, value.action.id, before_intent=check
        )
        assert result.permit_external_call and called == ["source", "parent"]
        assert value.work.tool_attempts_used == 1 and len(value.added) == 2
    else:
        with pytest.raises(ValueError):
            await store.begin(value.lease, value.identity, value.action.id, before_intent=check)
        assert value.work.tool_attempts_used == 0 and not value.added


@pytest.mark.parametrize("fault", ["none", "factory", "catalog", "credential", "prepared"])
async def test_real_report_constructor_and_witness_keep_original_composition(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    import hashlib
    from unittest.mock import MagicMock

    from nexus.company.contracts.actions import ActionProposal
    from nexus.company.management.generated_artifact_contracts import (
        GeneratedArtifactActionParameters,
        GeneratedArtifactInputs,
        GeneratedArtifactPayload,
    )
    from nexus.execution.dbos_contracts import SegmentCommand
    from nexus.execution.native_report_intent import NativeReportIntent
    from nexus.execution.nexus_report_auth import acquire_nexus_report
    from nexus.execution.nexus_report_intent import NexusReportIntent
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal_contracts import LedgerScope
    from nexus.tests.unit.nexus_cycle_fixture import key
    from nexus.tests.unit.nexus_report_fixture import services

    value = boundary(3)
    store = value.install(monkeypatch)
    configured = services(value, store)
    admission = value.catalog.nexus_cycle_admission
    assert admission is not None
    slot = admission.slots[3]
    binding = slot.child.binding
    prepared = GeneratedArtifactPayload(
        company_id=binding.company_id,
        raw_bytes=b"{}",
        output_sha256=hashlib.sha256(b"{}").hexdigest(),
        input_snapshot_sha256="a" * 64,
        recipe_version="native-report-profile-v1",
        data_classification="internal",
        inputs=GeneratedArtifactInputs(
            company_id=binding.company_id, required_resource_ids=(key("input-resource"),)
        ),
    )
    proposal = ActionProposal.model_validate_json(value.action.proposal_json)
    parameters = GeneratedArtifactActionParameters(
        recipe_version=prepared.recipe_version,
        output_sha256=prepared.output_sha256,
        input_snapshot_sha256=prepared.input_snapshot_sha256,
        report_id=key("native-report"),
        evidence_ids=(key("evidence"),),
    )
    proposal = proposal.model_copy(update={"parameters": parameters.model_dump(mode="json")})
    value.action.proposal_json = proposal.model_dump_json()
    value.action.proposal_hash = action_hash(proposal)
    command = SegmentCommand(
        company_id=binding.company_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        actor_id=binding.actor_id,
        workspace_id=binding.workspace_id,
        run_id=binding.run_id,
        action_id=value.action.id,
        segment_id=value.lease.segment_id,
    )
    scope = LedgerScope(
        company_id=binding.company_id,
        principal_id=binding.actor_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
    )
    monkeypatch.setattr(
        configured.execution, "recover_dispatched", AsyncMock(return_value=value.lease)
    )
    context = await acquire_nexus_report(
        configured, command, proposal, value.identity, binding, scope
    )
    assert context.credential is not None
    check = NexusReportIntent(NativeReportIntent(context, prepared, ()), context.credential)
    calls = []

    async def native(self: NativeReportIntent, *args: object) -> None:
        assert isinstance(self, NexusReportIntent)
        calls.append("native-report")
        if fault == "factory":
            self.context.services.publisher.factory = MagicMock()
        elif fault == "catalog":
            self.context.services.publisher.catalog = (
                self.context.services.publisher.catalog.model_copy()
            )
        elif fault == "credential":
            self.credential = MagicMock()
        elif fault == "prepared":
            self.prepared = self.prepared.model_copy(update={"input_snapshot_sha256": "b" * 64})

    # Existing report DB/compiler read delivery is supplied; new wrapper/gate are actual.
    monkeypatch.setattr(NativeReportIntent, "validate", native)
    monkeypatch.setattr(NativeReportIntent, "validate_time", lambda *args: None)
    if fault == "none":
        result = await store.begin(
            value.lease, value.identity, value.action.id, before_intent=check
        )
        assert result.permit_external_call and calls == ["native-report"]
    else:
        with pytest.raises(ValueError):
            await store.begin(value.lease, value.identity, value.action.id, before_intent=check)
        assert value.work.tool_attempts_used == 0 and not value.added
