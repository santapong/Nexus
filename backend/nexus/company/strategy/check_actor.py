"""Fresh issued SV publication gate; no effect issuance, receipt recording or acceptance."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_scope import require_generated_actor
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.artifact_contracts import (
    PreparedStrategyArtifact,
    StrategyCheckParameters,
)
from nexus.company.strategy.artifact_identity import (
    require_strategy_action_payload,
    strategy_reference,
)
from nexus.company.strategy.check_output import prepare_strategy_check
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.publication_intent import require_strategy_intent_locked
from nexus.company.strategy.publication_protection import (
    StrategyCheckMaterial,
    StrategyPublicationProtection,
    require_credential,
    strategy_publication_scope,
)
from nexus.company.strategy.publication_state import require_fresh_strategy_publication_state
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now, execution_row, lease_scope, require_lease
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction


@dataclass(frozen=True)
class StrategyIssuedCheck:
    material: StrategyCheckMaterial
    protection: StrategyPublicationProtection


async def revalidate_strategy_check_actor_locked(
    reader: StrategyInputReader,
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action_id: UUID,
    prepared: PreparedStrategyArtifact,
    *,
    credential: AuthenticatedWorkerIdentity,
) -> StrategyIssuedCheck:
    """Resolve actual action selectors, complete current material and original execute fence."""
    # This >50-line gate keeps actual action, original intent and final windows in one boundary.
    prepared = PreparedStrategyArtifact.model_validate(prepared.model_dump(warnings=False))
    await require_strategy_application_role(session)
    scope = strategy_publication_scope(lease, action_id)
    require_credential(credential, identity, scope, await db_now(session))
    work = await execution_row(session, lease_scope(lease))
    ref = strategy_reference(prepared, action_id)
    old = await session.get(BrainArtifactRevision, (lease.company_id, ref.artifact_revision_id))
    action, _, _ = await require_generated_actor(
        session,
        control,
        work,
        lease,
        identity,
        action_id,
        reader.catalog,
        reader.artifacts,
        reader.freshness,
        known=old is not None,
    )
    pins = require_strategy_action_payload(action, reader.rules.check, prepared)
    require_acceptance(isinstance(pins, StrategyCheckParameters))
    assert isinstance(pins, StrategyCheckParameters)
    material = await reader.load_check_locked(
        session, control, lease, identity, pins.author_action_id, credential=credential
    )
    require_acceptance(
        pins.verification_target_sha256 == canonical_sha256(material.command.target)
        and prepare_strategy_check(material.command, material.inputs, material.classification)
        == prepared
    )
    record = await session.get(JournalAction, action_id)
    require_acceptance(record is not None and record.approval_json is not None)
    assert record is not None and record.approval_json is not None
    approval = ApprovalDecision.model_validate_json(record.approval_json)
    require_acceptance(
        approval.company_id == lease.company_id
        and approval.approver_id == control.owner_id
        and approval.decision == "approved"
        and approval.action_id == action_id
        and approval.action_hash == action_hash(action)
        and approval.action_revision == action.revision
    )
    effect = await require_strategy_intent_locked(session, work, action, record)
    require_acceptance(effect.intent_fence == lease.fence)
    require_fresh_strategy_publication_state(
        effect, exists=old is not None, output=ref, action_id=action_id
    )
    protection = StrategyPublicationProtection(material.protection, lease, approval)
    now = await db_now(session)
    require_acceptance(effect.created_at <= now)
    require_lease(work, lease, now, execute=True)
    protection.require_time(now)
    return StrategyIssuedCheck(material, protection)
