"""Actual native zero-model sender with synthetic credentials and one mock provider boundary."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ResourceRevision
from nexus.company.notifications import worker_dispatch
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.notifications.worker_transport import CredentialedResendTransport
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.runtime_contracts import AttemptKind, EffectStart, ExecutionLease
from nexus.execution.runtime_models import EffectIntent
from nexus.harness.journal import CompanyJournal
from nexus.harness.lifecycle import ActionState
from nexus.tests.integration.test_company_notification_privacy import owner_source
from nexus.tests.notification_worker_credential_fixture import (
    WorkerCredentialCase,
    credential_case,
    credential_dispatcher,
    credential_facts,
    worker_credentials_factory,
    worker_witness,
)

__all__ = ["worker_credentials_factory"]


async def test_exact_native_sender_credential_issues_one_mock_post(
    worker_credentials_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await credential_case(worker_credentials_factory, tmp_path)
    assert case.native.catalog.models.models == ()
    assert case.native.sender.model_profile == "notification.native.v1"
    assert case.source_action.action_id != case.prepared.action.proposal.action_id
    calls: list[str] = []
    dispatcher = credential_dispatcher(worker_credentials_factory, case, calls)
    witness = await worker_witness(case.native.sender)
    result = await dispatcher.dispatch_with_credential(
        case.lease, witness, case.selection.draft_id, case.prepared.action.proposal.action_id
    )
    assert result is not None and result.outcome == "accepted" and calls == ["POST"]
    assert (
        await dispatcher.dispatch_with_credential(
            case.lease, witness, case.selection.draft_id, case.prepared.action.proposal.action_id
        )
        is None
    )
    assert calls == ["POST"]
    facts = await credential_facts(worker_credentials_factory, case)
    assert facts.intent_state == "succeeded" and facts.slot_present
    assert facts.tool_attempts == 1 and facts.model_requests == 0
    assert facts.hold_state == "unknown" and facts.hold_amount > 0 and facts.actual_usd is None
    source = await CompanyJournal(worker_credentials_factory).get_action(
        case.native.scope, case.source_action.action_id
    )
    assert source.state == ActionState.AWAITING_APPROVAL and source.approval is None


async def await_expiry(witness: AuthenticatedWorkerIdentity) -> None:
    """An actual wait crosses the signed integer credential deadline; no fake server clock."""
    remaining = (witness.expires_at - datetime.now(UTC)).total_seconds()
    assert remaining < 10
    await asyncio.sleep(max(0, remaining) + 0.03)


def delay_expiry(
    case: WorkerCredentialCase,
    witness: AuthenticatedWorkerIdentity,
    phase: str,
    monkeypatch: pytest.MonkeyPatch,
    seen: list[str],
) -> None:
    original_flush, original_begin = AsyncSession.flush, case.effects.begin

    async def flush(self: AsyncSession, objects: Sequence[object] | None = None) -> None:
        relevant = any(
            isinstance(row, EffectIntent)
            and row.action_id == case.prepared.action.proposal.action_id
            for row in self.new
        )
        await original_flush(self, objects)
        if relevant and phase == "after_flush":
            seen.append(phase)
            await await_expiry(witness)

    async def begin(
        current: ExecutionLease,
        actor: VerifiedIdentity,
        current_action_id: UUID,
        *,
        resources: tuple[ResourceRevision, ...] = (),
        kind: AttemptKind = "tool_attempts",
        before_intent: BeforeIntentCheck | None = None,
    ) -> EffectStart:
        start = await original_begin(
            current,
            actor,
            current_action_id,
            resources=resources,
            kind=kind,
            before_intent=before_intent,
        )
        if phase == "after_commit":
            assert start.permit_external_call
            seen.append(phase)
            await await_expiry(witness)
        return start

    monkeypatch.setattr(AsyncSession, "flush", flush)
    monkeypatch.setattr(case.effects, "begin", begin)


@pytest.mark.parametrize("phase", ["after_flush", "after_commit"])
async def test_credential_expiry_at_actual_intent_boundary_preserves_native_conservation(
    worker_credentials_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    case = await credential_case(worker_credentials_factory, tmp_path)
    before = await credential_facts(worker_credentials_factory, case)
    witness = await worker_witness(case.native.sender, seconds=5)
    seen: list[str] = []
    delay_expiry(case, witness, phase, monkeypatch, seen)
    calls: list[str] = []
    dispatcher = credential_dispatcher(worker_credentials_factory, case, calls)
    with pytest.raises(ValueError):
        await dispatcher.dispatch_with_credential(
            case.lease, witness, case.selection.draft_id, case.prepared.action.proposal.action_id
        )
    assert seen == [phase] and calls == []
    after = await credential_facts(worker_credentials_factory, case)
    assert after.hold_amount == before.hold_amount > 0 and after.actual_usd is None
    if phase == "after_flush":
        assert after == before and after.intent_state is None and not after.slot_present
    else:
        assert after.intent_state == "intent" and after.slot_present and after.tool_attempts == 1
        await case.native.runtime.release(case.lease, witness.identity, blocked=True)
        unknown = await credential_facts(worker_credentials_factory, case)
        assert unknown.intent_state == "outcome_unknown" and unknown.slot_present
        assert unknown.tool_attempts == 1 and unknown.model_requests == 0
        assert unknown.hold_state == "unknown" and unknown.hold_amount == before.hold_amount


async def test_context_setup_await_cannot_consume_credential_before_first_http_stream(
    worker_credentials_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await credential_case(worker_credentials_factory, tmp_path)
    witness = await worker_witness(case.native.sender, seconds=5)
    seen: list[str] = []

    class SlowSetup(CredentialedResendTransport):
        async def __aenter__(self) -> CredentialedResendTransport:
            seen.append("setup")
            await await_expiry(self.witness)
            await super().__aenter__()
            return self

    monkeypatch.setattr(worker_dispatch, "CredentialedResendTransport", SlowSetup)
    calls: list[str] = []
    dispatcher = credential_dispatcher(worker_credentials_factory, case, calls)
    with pytest.raises(ValueError):
        await dispatcher.dispatch_with_credential(
            case.lease, witness, case.selection.draft_id, case.prepared.action.proposal.action_id
        )
    assert seen == ["setup"] and calls == []
    await case.native.runtime.release(case.lease, witness.identity, blocked=True)
    facts = await credential_facts(worker_credentials_factory, case)
    assert (
        facts.intent_state == "outcome_unknown" and facts.tool_attempts == 1 and facts.slot_present
    )
    assert facts.hold_state == "unknown" and facts.hold_amount > 0 and facts.actual_usd is None


async def test_already_issued_receipt_replay_with_expired_witness_has_no_second_post(
    worker_credentials_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await credential_case(worker_credentials_factory, tmp_path)
    calls: list[str] = []
    dispatcher = credential_dispatcher(worker_credentials_factory, case, calls)
    witness = await worker_witness(case.native.sender)
    await dispatcher.dispatch_with_credential(
        case.lease, witness, case.selection.draft_id, case.prepared.action.proposal.action_id
    )
    before = await credential_facts(worker_credentials_factory, case)
    expired = await worker_witness(case.native.sender, seconds=1)
    await await_expiry(expired)
    assert (
        await dispatcher.dispatch_with_credential(
            case.lease, expired, case.selection.draft_id, case.prepared.action.proposal.action_id
        )
        is None
    )
    assert calls == ["POST"] and await credential_facts(worker_credentials_factory, case) == before


async def test_current_source_revocation_still_denies_fresh_credentialed_sender(
    worker_credentials_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await credential_case(worker_credentials_factory, tmp_path)
    before = await credential_facts(worker_credentials_factory, case)
    witness = await worker_witness(case.native.sender)
    await owner_source(worker_credentials_factory, active=False)
    calls: list[str] = []
    with pytest.raises(ValueError):
        await credential_dispatcher(
            worker_credentials_factory, case, calls
        ).dispatch_with_credential(
            case.lease, witness, case.selection.draft_id, case.prepared.action.proposal.action_id
        )
    assert calls == [] and await credential_facts(worker_credentials_factory, case) == before


async def test_source_revoked_during_client_setup_never_reaches_first_post(
    worker_credentials_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await credential_case(worker_credentials_factory, tmp_path)
    witness = await worker_witness(case.native.sender)
    seen: list[str] = []

    class RevokingSetup(CredentialedResendTransport):
        async def __aenter__(self) -> CredentialedResendTransport:
            await owner_source(worker_credentials_factory, active=False)
            seen.append("revoked")
            await super().__aenter__()
            return self

    monkeypatch.setattr(worker_dispatch, "CredentialedResendTransport", RevokingSetup)
    calls: list[str] = []
    with pytest.raises(ValueError):
        await credential_dispatcher(
            worker_credentials_factory, case, calls
        ).dispatch_with_credential(
            case.lease, witness, case.selection.draft_id, case.prepared.action.proposal.action_id
        )
    assert seen == ["revoked"] and calls == []
    await case.native.runtime.release(case.lease, witness.identity, blocked=True)
    facts = await credential_facts(worker_credentials_factory, case)
    assert (
        facts.intent_state == "outcome_unknown" and facts.slot_present and facts.tool_attempts == 1
    )
    assert facts.model_requests == 0 and facts.hold_state == "unknown" and facts.hold_amount > 0
