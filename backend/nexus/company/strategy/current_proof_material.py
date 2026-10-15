"""Taskless real-reader Strategy material; actual SV work is provenance, never impersonation."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_provenance import exact_artifact
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.native_report_inputs import native_manifest
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.artifact_identity import (
    require_strategy_action_payload,
    strategy_reference,
)
from nexus.company.strategy.check_output import prepare_strategy_check
from nexus.company.strategy.check_rows import require_strategy_check_replay_locked
from nexus.company.strategy.contracts import (
    STRATEGY_CHECK_CRITERIA,
    STRATEGY_CHECK_RECIPE,
    StrategyCheckInput,
)
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.publication_protection import (
    StrategyCheckMaterial,
    StrategyProtectedPublication,
    require_credential,
)
from nexus.company.strategy.verifier_facts import StrategyVerifierReceipt
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


async def load_current_material_locked(
    reader: StrategyInputReader,
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    author_action_id: UUID,
    *,
    credential: AuthenticatedWorkerIdentity,
) -> tuple[StrategyCheckMaterial, StrategyProtectedPublication]:
    """Derive the same immutable target and M+B+S inputs without an SV execution lease."""
    # Keep original target identity and complete manifest comparison in this one read boundary.
    protected = await reader.load_original_locked(
        session, control, scope, identity, author_action_id, credential=credential
    )
    loaded, pair = protected.publication, protected.protection.pair
    require_acceptance(
        all(
            work.state not in {"blocked", "outcome_unknown"}
            for work in (pair.author, pair.verifier)
        )
    )
    original = loaded.prepared.original.snapshot
    target = VerificationSpec(
        company_id=scope.company_id,
        author=original.scope.author,
        verifier=original.scope.verifier,
        action_id=author_action_id,
        proposal_sha256=loaded.receipt.proposal_hash,
        receipt_id=loaded.receipt.receipt_id,
        receipt_sha256=canonical_sha256(loaded.receipt),
        work_snapshot_sha256=original.scope.author_registration_sha256,
        criterion_ids=STRATEGY_CHECK_CRITERIA,
        artifacts=(loaded.prepared.brief,),
        check_recipe=STRATEGY_CHECK_RECIPE,
    )
    inputs, actual_class = await native_manifest(
        session,
        scope,
        (
            *original.inputs.artifacts,
            loaded.prepared.compiled.original_bundle.artifact,
            loaded.prepared.brief,
        ),
        original.inputs.contributors,
        original.inputs.evidence,
        original.inputs.required_resource_ids,
    )
    expected = {ref.artifact_revision_id for ref in original.inputs.artifacts} | {
        loaded.prepared.compiled.original_bundle.artifact.artifact_revision_id,
        loaded.prepared.brief.artifact_revision_id,
    }
    require_acceptance({ref.artifact_revision_id for ref in inputs.artifacts} == expected)
    levels = ("public", "internal", "confidential", "restricted")
    require_acceptance(
        levels.index(actual_class) <= levels.index(reader.rules.check_policy.data_classification)
    )
    command = StrategyCheckInput(
        company_id=scope.company_id,
        target=target,
        output=loaded.prepared.brief,
        output_utf8=loaded.prepared.compiled.prepared.raw_bytes,
        snapshot=original,
    )
    now = await db_now(session)
    require_credential(credential, identity, scope, now)
    protected.protection.require_time(now)
    return StrategyCheckMaterial(
        command, inputs, reader.rules.check_policy.data_classification, protected.protection
    ), protected


async def protect_current_check_locked(
    reader: StrategyInputReader,
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    material: StrategyCheckMaterial,
    facts: StrategyVerifierReceipt,
    *,
    credential: AuthenticatedWorkerIdentity,
) -> bytes:
    """READ precedes C bytes; exact production pins, every graph edge and final clock must agree."""
    prepared = prepare_strategy_check(material.command, material.inputs, material.classification)
    require_acceptance(
        strategy_reference(prepared, facts.action.action_id) == facts.protected_result
    )
    require_acceptance(
        require_strategy_action_payload(facts.action, reader.rules.check, prepared)
        == facts.parameters
    )
    await reader.artifacts.revalidate_artifact_reference(
        session, control, scope, identity, facts.protected_result, await db_now(session)
    )
    row = await exact_artifact(session, scope, facts.protected_result)
    require_acceptance(
        row.raw_text.encode() == prepared.raw_bytes
        and row.resource_id == reader.rules.check.target.resource_id
        and row.storage_symbol == reader.blobs.storage_symbol
        and row.media_type == "application/json"
        and row.data_classification == material.classification
        and row.recorded_at <= facts.receipt.recorded_at
    )
    await require_strategy_check_replay_locked(
        session,
        scope,
        facts.action.action_id,
        prepared,
        reader.rules.check,
        reader.blobs.storage_symbol,
    )
    now = await db_now(session)
    require_acceptance(row.recorded_at <= now)
    material.protection.require_time(now)
    require_credential(credential, identity, scope, now)
    return prepared.raw_bytes
