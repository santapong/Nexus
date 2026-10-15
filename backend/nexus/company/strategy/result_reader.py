"""Current protected SV bytes/graph checks; receipt and acceptance gates remain separate."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_provenance import exact_artifact
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.artifact_contracts import StrategyCheckParameters
from nexus.company.strategy.artifact_identity import (
    require_strategy_action_payload,
    strategy_reference,
)
from nexus.company.strategy.check_output import prepare_strategy_check
from nexus.company.strategy.check_rows import require_strategy_check_replay_locked
from nexus.company.strategy.publication_protection import (
    StrategyReadProtection,
    require_credential,
    strategy_publication_scope,
)
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now, execution_row, lease_scope, require_lease
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction

if TYPE_CHECKING:
    from nexus.company.strategy.input_reader import StrategyInputReader
    from nexus.company.strategy.publication_protection import StrategyCheckMaterial


async def protect_strategy_check_result_locked(
    reader: StrategyInputReader,
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    material: StrategyCheckMaterial,
    verifier_action_id: UUID,
    protected_result: ArtifactRevisionRef,
    *,
    credential: AuthenticatedWorkerIdentity,
) -> StrategyReadProtection:
    """Re-resolve actual inputs and full C graph; a supplied material/result is never enough."""
    # This >50-line complete native check artifact boundary retains all old/current clocks.
    await require_strategy_application_role(session)
    current = await reader.load_check_locked(
        session, control, lease, identity, material.command.target.action_id, credential=credential
    )
    require_acceptance(
        (current.command, current.inputs, current.classification)
        == (material.command, material.inputs, material.classification)
    )
    scope = strategy_publication_scope(lease, verifier_action_id)
    prepared = prepare_strategy_check(current.command, current.inputs, current.classification)
    require_acceptance(strategy_reference(prepared, verifier_action_id) == protected_result)
    record = await session.get(JournalAction, verifier_action_id)
    require_acceptance(
        record is not None and record.state == "authorized" and record.consumed_at is not None
    )
    assert record is not None
    action = ActionProposal.model_validate_json(record.proposal_json)
    require_acceptance(
        (record.id, record.company_id, record.task_id, record.trace_id, record.proposal_hash)
        == (
            verifier_action_id,
            lease.company_id,
            lease.task_id,
            lease.trace_id,
            action_hash(action),
        )
        and (action.actor_id, action.task_id, action.trace_id)
        == (lease.actor_id, lease.task_id, lease.trace_id)
    )
    parameters = require_strategy_action_payload(action, reader.rules.check, prepared)
    require_acceptance(isinstance(parameters, StrategyCheckParameters))
    assert isinstance(parameters, StrategyCheckParameters)
    require_acceptance(
        parameters.author_action_id == current.command.target.action_id
        and parameters.verification_target_sha256 == canonical_sha256(current.command.target)
    )
    await reader.artifacts.revalidate_artifact_reference(
        session, control, scope, identity, protected_result, await db_now(session)
    )
    row = await exact_artifact(session, scope, protected_result)
    require_acceptance(
        row.raw_text.encode() == prepared.raw_bytes
        and row.resource_id == reader.rules.check.target.resource_id
        and row.storage_symbol == reader.blobs.storage_symbol
        and row.media_type == "application/json"
        and row.data_classification == current.classification
    )
    await require_strategy_check_replay_locked(
        session,
        scope,
        verifier_action_id,
        prepared,
        reader.rules.check,
        reader.blobs.storage_symbol,
    )
    work = await execution_row(session, lease_scope(lease))
    now = await db_now(session)
    require_acceptance(row.recorded_at <= now)
    require_lease(work, lease, now, execute=True)
    require_credential(credential, identity, scope, now)
    material.protection.require_time(now)
    current.protection.require_time(now)
    return current.protection
