"""Concrete current original B/Brief reader; no source clock or receipt is invented."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_provenance import exact_artifact
from nexus.company.management.acceptance_support import actual_receipt
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.artifact_identity import (
    require_strategy_action_payload,
    strategy_artifact_id,
)
from nexus.company.strategy.producer_contracts import StrategyOriginalInputBundle
from nexus.company.strategy.publication_contracts import StrategyLoadedPublication
from nexus.company.strategy.publication_identity import (
    prepare_strategy_publication,
    strategy_bundle_id,
)
from nexus.company.strategy.publication_intent import require_strategy_intent_locked
from nexus.company.strategy.publication_protection import (
    StrategyProtectedPublication,
    require_credential,
)
from nexus.company.strategy.publication_rows import require_strategy_publication_replay_locked
from nexus.execution.runtime_support import db_now
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction

if TYPE_CHECKING:
    from nexus.company.strategy.input_reader import StrategyInputReader


async def load_strategy_original_locked(
    reader: StrategyInputReader,
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    author_action_id: UUID,
    *,
    credential: AuthenticatedWorkerIdentity,
) -> StrategyProtectedPublication:
    """Read only an actual succeeded S and exact B/Brief graphs under current signed READ."""
    # This >50-line native read keeps receipt/identity/body binding and final time together.
    await require_strategy_application_role(session)
    require_credential(credential, identity, scope, await db_now(session))
    await require_brain_scope(session, control, scope, identity)
    record = await session.get(JournalAction, author_action_id)
    require_acceptance(
        record is not None
        and record.company_id == scope.company_id
        and record.state == "authorized"
        and record.consumed_at is not None
    )
    assert record is not None
    action = ActionProposal.model_validate_json(record.proposal_json)
    require_acceptance(
        action.action_id == record.id == author_action_id
        and action_hash(action) == record.proposal_hash
        and (action.company_id, action.task_id, action.trace_id)
        == (record.company_id, record.task_id, record.trace_id)
    )
    ids = (
        uuid5(strategy_bundle_id(scope.company_id, author_action_id), "revision:v2"),
        uuid5(strategy_artifact_id(scope.company_id, author_action_id), "revision:v1"),
    )
    rows: list[BrainArtifactRevision] = []
    references: list[ArtifactRevisionRef] = []
    for key in ids:
        # Full raw_text is selected only after the actual complete artifact READ gate.
        metadata = (
            await session.execute(
                select(
                    BrainArtifactRevision.artifact_id,
                    BrainArtifactRevision.artifact_revision_id,
                    BrainArtifactRevision.revision,
                    BrainArtifactRevision.sha256,
                    BrainArtifactRevision.byte_length,
                ).where(
                    BrainArtifactRevision.company_id == scope.company_id,
                    BrainArtifactRevision.artifact_revision_id == key,
                )
            )
        ).one_or_none()
        require_acceptance(metadata is not None)
        assert metadata is not None
        artifact_id, revision_id, revision, digest, size = metadata
        reference = ArtifactRevisionRef(
            company_id=scope.company_id,
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            revision=revision,
            sha256=digest,
            byte_length=size,
        )
        await reader.artifacts.revalidate_artifact_reference(
            session, control, scope, identity, reference, await db_now(session)
        )
        row = await exact_artifact(session, scope, reference)
        rows.append(row)
        references.append(reference)
    bundle_row = rows[0]
    assert bundle_row is not None
    original = StrategyOriginalInputBundle.model_validate_json(bundle_row.raw_text)
    prepared = prepare_strategy_publication(
        original.snapshot, original.policy, author_action_id, reader.rules.write.target
    )
    require_acceptance(
        (prepared.compiled.original_bundle.artifact, prepared.brief) == tuple(references)
    )
    require_strategy_action_payload(action, reader.rules.write, prepared.compiled.prepared)
    protection = await reader._read_gate(session, control, scope, identity, prepared, credential)
    author = protection.pair.author
    require_acceptance(
        (action.actor_id, action.task_id, action.trace_id)
        == (author.actor_id, author.task_id, author.trace_id)
    )
    effect = await require_strategy_intent_locked(session, author, action, record)
    receipt = await actual_receipt(session, author, author_action_id)
    require_acceptance(
        len(receipt.artifacts) == 1
        and (
            receipt.artifacts[0].company_id,
            receipt.artifacts[0].artifact_id,
            receipt.artifacts[0].revision,
            receipt.artifacts[0].sha256,
        )
        == (
            prepared.brief.company_id,
            prepared.brief.artifact_id,
            prepared.brief.revision,
            prepared.brief.sha256,
        )
    )
    await require_strategy_publication_replay_locked(
        session, scope, prepared, reader.blobs.storage_symbol
    )
    now = await db_now(session)
    assert record.consumed_at is not None
    require_acceptance(
        effect.created_at <= receipt.recorded_at <= now
        and record.consumed_at <= now
        and all(
            row is not None
            and effect.created_at <= row.recorded_at <= receipt.recorded_at
            and original.snapshot.observed_at <= row.recorded_at
            for row in rows
        )
    )
    protection.require_time(now)
    return StrategyProtectedPublication(
        StrategyLoadedPublication(
            prepared=prepared,
            action=action,
            receipt=receipt,
            original_intent_fence=effect.intent_fence,
        ),
        protection,
    )
