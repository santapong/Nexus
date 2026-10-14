"""Actual existing exact decisions commit atomically with current native credential checks."""

# TASK: Consume an existing approved sender decision without issuing a decision or effect.
# FILES: NEW worker_authorization.py, this test and exclusive authorization fixture.
# DONE: Exact replay conserves allowance; final credential expiry rolls new consumption back.
# RISK: High authorization boundary; actual restricted PG and immutable native source required.

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ResourceRevision
from nexus.company.control_store import CompanyControls
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.managed_admission import ManagedNotificationAdmission
from nexus.company.notifications.managed_contracts import NativeNotificationSelection
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.worker_authorization import authorize_prepared_notification
from nexus.company.notifications.worker_intent import CredentialNotificationIntentCheck
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.authorization_source import require_action_authority
from nexus.harness.journal_contracts import ActionRecord, LedgerScope
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_privacy import owner_source
from nexus.tests.notification_worker_authorization_fixture import (
    authorization_case,
    authorization_facts,
)
from nexus.tests.notification_worker_authorization_fixture import (
    worker_authorization_factory as worker_authorization_factory,
)
from nexus.tests.notification_worker_credential_fixture import worker_witness


async def test_existing_exact_owner_decision_authorization_replay_conserves_hold(
    worker_authorization_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await authorization_case(worker_authorization_factory, tmp_path)
    witness = await worker_witness(case.binding)
    result = await authorize_prepared_notification(
        case.preparation, case.selection, case.binding, witness
    )
    assert result.approval is not None
    before = await authorization_facts(worker_authorization_factory, case)
    assert before.holds == 1 and before.intents == 0 and before.slots == 0
    assert (
        await authorize_prepared_notification(
            case.preparation, case.selection, case.binding, witness
        )
        == result
    )
    assert await authorization_facts(worker_authorization_factory, case) == before


async def test_authorization_replay_after_source_revocation_preserves_existing_hold(
    worker_authorization_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await authorization_case(worker_authorization_factory, tmp_path)
    witness = await worker_witness(case.binding)
    await authorize_prepared_notification(case.preparation, case.selection, case.binding, witness)
    await owner_source(worker_authorization_factory, active=False)
    before = await authorization_facts(worker_authorization_factory, case)
    with pytest.raises(ValueError):
        await authorize_prepared_notification(
            case.preparation, case.selection, case.binding, witness
        )
    assert before.holds == 1 and before.intents == before.slots == 0
    assert await authorization_facts(worker_authorization_factory, case) == before


async def test_already_issued_unknown_intent_cannot_be_reauthorized_or_refunded(
    worker_authorization_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await authorization_case(worker_authorization_factory, tmp_path)
    witness = await worker_witness(case.binding)
    await authorize_prepared_notification(case.preparation, case.selection, case.binding, witness)
    lease = await case.native.runtime.claim(
        case.native.scope, witness.identity, uuid4(), ttl_seconds=60
    )
    prepared = case.preparation
    effects = ManagedNotificationEffectStore(
        worker_authorization_factory,
        prepared.drafts,
        prepared.catalog,
        prepared.artifacts,
        prepared.freshness,
        policy=prepared.policy,
    )
    started = await effects.begin(
        lease,
        witness.identity,
        case.prepared.action.proposal.action_id,
        before_intent=CredentialNotificationIntentCheck(
            lease,
            witness,
            case.selection.draft_id,
            prepared.drafts,
            prepared.policy.target,
            prepared.policy.resource_symbol,
        ),
    )
    assert started.permit_external_call
    await case.native.runtime.release(lease, witness.identity, blocked=True)
    before = await authorization_facts(worker_authorization_factory, case)
    with pytest.raises(ValueError):
        await authorize_prepared_notification(
            case.preparation, case.selection, case.binding, witness
        )
    assert before.holds == before.intents == before.slots == 1
    assert before.counters.tool_attempts == 1 and before.counters.model_requests == 0
    assert len(before.hold_states) == 1
    state, amount, actual = before.hold_states[0]
    assert state == "unknown" and amount > 0 and actual is None
    assert await authorization_facts(worker_authorization_factory, case) == before


async def test_final_credential_expiry_rolls_back_new_authorization_and_hold(
    worker_authorization_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.company.notifications.worker_authorization as module

    case = await authorization_case(worker_authorization_factory, tmp_path)
    witness = await worker_witness(case.binding, seconds=3)
    before = await authorization_facts(worker_authorization_factory, case)
    original = module.current_prepared_admission
    calls = 0

    async def delayed(
        preparation: ManagedNotificationPreparation,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        signed: VerifiedIdentity,
        selection: NativeNotificationSelection,
        binding: RunBinding,
        record: ActionRecord,
    ) -> ManagedNotificationAdmission:
        nonlocal calls
        calls += 1
        value = await original(
            preparation, session, control, work, signed, selection, binding, record
        )
        if calls == 2:
            await asyncio.sleep(
                max(0, (witness.expires_at - datetime.now(UTC)).total_seconds()) + 0.03
            )
        return value

    monkeypatch.setattr(module, "current_prepared_admission", delayed)
    with pytest.raises(ValueError):
        await authorize_prepared_notification(
            case.preparation, case.selection, case.binding, witness
        )
    assert calls == 2
    assert await authorization_facts(worker_authorization_factory, case) == before


async def test_final_recipient_file_loss_rolls_back_approval_consumption(
    worker_authorization_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.company.notifications.worker_authorization as module

    case = await authorization_case(worker_authorization_factory, tmp_path)
    witness = await worker_witness(case.binding)
    before = await authorization_facts(worker_authorization_factory, case)
    original = require_action_authority
    calls = 0

    async def remove_after_authority(
        session: AsyncSession,
        control: CompanyControl,
        row: JournalAction,
        scope: LedgerScope,
        signed: VerifiedIdentity,
        now: datetime,
        resources: tuple[ResourceRevision, ...],
    ) -> None:
        nonlocal calls
        await original(session, control, row, scope, signed, now, resources)
        calls += 1
        (tmp_path / "synthetic-worker-recipient.json").unlink()

    monkeypatch.setattr(module, "require_action_authority", remove_after_authority)
    denied = False
    try:
        await authorize_prepared_notification(
            case.preparation, case.selection, case.binding, witness
        )
    except ValueError:
        denied = True
    after = await authorization_facts(worker_authorization_factory, case)
    assert calls == 1
    assert denied, f"Missing registry committed authorization; holds {before.holds}->{after.holds}"
    assert after == before


@pytest.mark.parametrize(
    "reason", ["missing_decision", "expired_decision", "paused", "binding", "source"]
)
async def test_current_native_authorization_denials_create_no_hold_or_intent(
    worker_authorization_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    reason: str,
) -> None:
    case = await authorization_case(
        worker_authorization_factory,
        tmp_path,
        approved=reason != "missing_decision",
        approval_age=timedelta(hours=25) if reason == "expired_decision" else timedelta(0),
    )
    witness = await worker_witness(case.binding)
    bound = case.binding
    if reason == "paused":
        await CompanyControls(worker_authorization_factory).set_paused_registered(
            control(), identity(OWNER), True
        )
    elif reason == "binding":
        bound = bound.model_copy(update={"run_id": uuid4()})
    elif reason == "source":
        await owner_source(worker_authorization_factory, active=False)
    before = await authorization_facts(worker_authorization_factory, case)
    with pytest.raises(ValueError):
        await authorize_prepared_notification(case.preparation, case.selection, bound, witness)
    assert before.holds == before.intents == before.slots == 0
    assert await authorization_facts(worker_authorization_factory, case) == before
