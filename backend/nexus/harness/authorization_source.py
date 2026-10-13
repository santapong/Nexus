"""Fresh authorization recheck at the effect boundary, including time spent in a queue."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision, ResourceRevision
from nexus.harness.approvals import ApprovalContext, require_exact_approval
from nexus.harness.authorization_models import ActionAuthority
from nexus.harness.journal_budget import require_registered_access
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.standing_contracts import grant_hash
from nexus.harness.standing_store import require_standing_authority


async def require_action_authority(
    session: AsyncSession,
    control: CompanyControl,
    record: JournalAction,
    scope: LedgerScope,
    identity: VerifiedIdentity,
    now: datetime,
    resources: tuple[ResourceRevision, ...],
) -> None:
    """Validate consumed authority again; do not reserve, refund or issue a permit here."""
    action = ActionProposal.model_validate_json(record.proposal_json)
    await require_registered_access(session, control, action, scope, identity, owner=False)
    if record.consumed_at is None:
        raise ValueError("Effect requires consumed exact action authority")
    source = await session.get(ActionAuthority, (scope.company_id, record.id))
    if record.approval_json is None:
        if source is None:
            raise ValueError("Standing action has no immutable authorization source")
        grant = await require_standing_authority(
            session,
            control,
            action,
            scope,
            identity,
            source.grant_id,
            now,
            resources,
        )
        if grant_hash(grant) != source.grant_hash or source.authorized_at != record.consumed_at:
            raise ValueError("Standing authorization source binding disagrees")
        return
    if source is not None:
        raise ValueError("Action cannot mix standing and exact owner authority")
    context = ApprovalContext(
        company_id=scope.company_id,
        owner_id=control.owner_id,
        actor_id=scope.principal_id,
        now=now,
        policy_version=control.policy_version,
        price_version=control.price_version,
        paused=control.paused,
        resources=resources,
    )
    require_exact_approval(
        action, ApprovalDecision.model_validate_json(record.approval_json), context
    )
