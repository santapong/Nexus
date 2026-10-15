"""Actual SV execution-wrapper checks around shared read-only succeeded receipt facts."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.report_input_contracts import native_author
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.artifact_contracts import StrategyArtifactRule
from nexus.company.strategy.publication_protection import strategy_publication_scope
from nexus.company.strategy.verifier_facts import StrategyVerifierReceipt as StrategyVerifierReceipt
from nexus.company.strategy.verifier_facts import require_strategy_verifier_facts_locked
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now, execution_row, lease_scope, require_lease
from nexus.harness.journal_models import CompanyControl


async def require_strategy_verifier_receipt(
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    target: VerificationSpec,
    *,
    verifier_action_id: UUID,
    protected_result: ArtifactRevisionRef,
    rule: StrategyArtifactRule,
    credential: AuthenticatedWorkerIdentity,
    artifacts: BoundedArtifactReader,
) -> StrategyVerifierReceipt:
    """Retain actual execution lease/identity/fence checks; current plan/source gate is separate."""
    require_acceptance(
        session.in_transaction()
        and control.company_id == lease.company_id
        and isinstance(credential, AuthenticatedWorkerIdentity)
        and credential.identity == identity
        and (identity.principal_id, identity.workspace_id) == (lease.actor_id, lease.workspace_id)
    )
    work = await execution_row(session, lease_scope(lease))
    now = await db_now(session)
    require_lease(work, lease, now, execute=True)
    credential.require_time(now)
    binding, _ = native_author(work)
    require_acceptance(binding == target.verifier)
    result = await require_strategy_verifier_facts_locked(
        session,
        control,
        strategy_publication_scope(lease, verifier_action_id),
        identity,
        work,
        target,
        verifier_action_id=verifier_action_id,
        protected_result=protected_result,
        rule=rule,
        credential=credential,
        artifacts=artifacts,
    )
    require_acceptance(0 < result.original_intent_fence <= lease.fence)
    now = await db_now(session)
    require_acceptance(result.receipt.recorded_at <= now)
    require_lease(work, lease, now, execute=True)
    credential.require_time(now)
    return result
