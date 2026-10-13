"""Consume an exact routine action under a current explicit standing capability."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ResourceRevision
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dbos_queue import enqueue_authorized_segment
from nexus.harness.authorization_models import ActionAuthority
from nexus.harness.journal import CompanyJournal, _action, _control, _record
from nexus.harness.journal_budget import reserve_registered_cost
from nexus.harness.journal_contracts import ActionRecord, LedgerScope
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.lifecycle import ActionState, require_transition
from nexus.harness.standing_contracts import grant_hash
from nexus.harness.standing_store import require_standing_authority


async def _consume_standing(
    session: AsyncSession,
    control: CompanyControl,
    row: JournalAction,
    scope: LedgerScope,
    grant_id: UUID,
    now: datetime,
    resources: tuple[ResourceRevision, ...],
    identity: VerifiedIdentity,
) -> ActionRecord:
    record = _record(row)
    if row.consumed_at is not None or record.approval is not None:
        raise ValueError("Standing action is consumed or has an exact owner decision")
    grant = await require_standing_authority(
        session,
        control,
        record.proposal,
        scope,
        identity,
        grant_id,
        now,
        resources,
    )
    require_transition(record.state, ActionState.AUTHORIZED)
    await reserve_registered_cost(session, control, record.proposal, scope, now)
    session.add(
        ActionAuthority(
            company_id=scope.company_id,
            action_id=row.id,
            grant_id=grant_id,
            grant_hash=grant_hash(grant),
            authorized_at=now,
        )
    )
    row.consumed_at, row.state = now, ActionState.AUTHORIZED.value
    await session.flush()
    return _record(row)


class StandingJournal(CompanyJournal):
    """Separate policy entrypoint; exact owner decisions retain their original journal path."""

    async def authorize_standing(
        self,
        scope: LedgerScope,
        action_id: UUID,
        grant_id: UUID,
        now: datetime,
        resources: tuple[ResourceRevision, ...],
        *,
        identity: VerifiedIdentity,
    ) -> ActionRecord:
        """Persist source, exact single-use authorization and hold in one locked transaction."""
        async with self._session(scope) as session:
            control = await _control(session, scope)
            row = await _action(session, scope, action_id)
            return await _consume_standing(
                session,
                control,
                row,
                scope,
                grant_id,
                now,
                resources,
                identity,
            )

    async def authorize_and_enqueue_standing(
        self,
        scope: LedgerScope,
        command: SegmentCommand,
        grant_id: UUID,
        now: datetime,
        resources: tuple[ResourceRevision, ...],
        *,
        identity: VerifiedIdentity,
    ) -> str:
        """Commit standing provenance, consumed authority, hold and scheduling together."""
        command = SegmentCommand.model_validate(command.model_dump())
        command.require_scope(scope)
        if command.workspace_id != identity.workspace_id:
            raise ValueError("Continuation and verified workspace disagree")
        async with self._session(scope) as session:
            control = await _control(session, scope)
            row = await _action(session, scope, command.action_id)
            await _consume_standing(
                session,
                control,
                row,
                scope,
                grant_id,
                now,
                resources,
                identity,
            )
            return await enqueue_authorized_segment(session, command, scope)
