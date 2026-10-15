"""Actual-shaped owner proof composition with genuine synthetic JWT and mocked native SQL."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid5

from nexus.company.brain.artifact_input_models import BrainArtifactInput, BrainArtifactResourceInput
from nexus.company.brain.derivation_models import (
    BrainDerivation,
    BrainDerivationEvidence,
    BrainDerivationSource,
)
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.strategy.artifact_contracts import StrategyCheckParameters
from nexus.company.strategy.artifact_identity import strategy_derivation_id, strategy_reference
from nexus.company.strategy.check_output import prepare_strategy_check
from nexus.company.strategy.contracts import (
    StrategyCheckInput,
)
from nexus.company.strategy.verifier_facts import StrategyVerifierReceipt
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import JournalAction
from nexus.tests.unit.strategy_publication_reader_fixture import ReaderCase


def add_check_rows(
    base: ReaderCase,
    target: VerificationSpec,
    manifest: GeneratedArtifactInputs,
    command: StrategyCheckInput,
    now: datetime,
) -> tuple[StrategyVerifierReceipt, ArtifactRevisionRef, BrainEvent]:
    """Construct exact original SV rows and full immutable C graph, without any DB writes."""
    # Keep this >50-line immutable row fixture coherent with its production output bytes.
    company_id = target.company_id
    bound = target.verifier
    check = prepare_strategy_check(command, manifest, "internal")
    action_id = UUID(int=910)
    parameters = StrategyCheckParameters(
        author_action_id=base.action.action_id,
        verification_target_sha256=canonical_sha256(target),
        output_sha256=check.output_sha256,
        input_snapshot_sha256=check.input_snapshot_sha256,
    )
    action = ActionProposal(
        company_id=company_id,
        action_id=action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        revision=1,
        tool=base.reader.rules.check.tool,
        tool_version="v1",
        resource=base.reader.rules.check.resource_symbol,
        parameters=parameters.model_dump(mode="json"),
        policy_version="p1",
        price_version="p1",
        estimated_cost_usd=Decimal(".01"),
    )
    ref = strategy_reference(check, action_id)
    receipt = ActionReceipt(
        company_id=company_id,
        receipt_id=UUID(int=911),
        action_id=action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        proposal_hash=action_hash(action),
        outcome="succeeded",
        recorded_at=now,
        artifacts=(
            ArtifactRef(
                company_id=company_id,
                artifact_id=ref.artifact_id,
                reference="protected C",
                revision=ref.revision,
                sha256=ref.sha256,
            ),
        ),
    )
    base.rows[(JournalAction, action_id)] = JournalAction(
        company_id=company_id,
        id=action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        proposal_hash=action_hash(action),
        proposal_json=action.model_dump_json(),
        state="authorized",
        consumed_at=now,
    )
    base.rows[(EffectIntent, (company_id, action_id))] = EffectIntent(
        company_id=company_id,
        action_id=action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        run_id=bound.run_id,
        proposal_hash=action_hash(action),
        attempt_kind="tool_attempts",
        intent_fence=1,
        state="succeeded",
        created_at=now,
        receipt_json=receipt.model_dump_json(),
    )
    base.rows[(ExecutionAttempt, (company_id, bound.task_id, action_id))] = ExecutionAttempt(
        company_id=company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        attempt_id=action_id,
        fence=1,
        kind="tool_attempts",
        reserved_at=now,
    )
    derivation_id = strategy_derivation_id(company_id, action_id)
    base.rows[(BrainArtifactRevision, (company_id, ref.artifact_revision_id))] = (
        BrainArtifactRevision(
            company_id=company_id,
            artifact_id=ref.artifact_id,
            artifact_revision_id=ref.artifact_revision_id,
            revision=ref.revision,
            sha256=ref.sha256,
            byte_length=ref.byte_length,
            raw_text=check.raw_bytes.decode(),
            resource_id=base.reader.rules.check.target.resource_id,
            derivation_id=derivation_id,
            media_type="application/json",
            storage_symbol=base.reader.blobs.storage_symbol,
            data_classification="internal",
            recorded_at=now,
        )
    )
    base.rows[(BrainDerivation, (company_id, derivation_id))] = BrainDerivation(
        company_id=company_id,
        derivation_id=derivation_id,
        artifact_revision_id=ref.artifact_revision_id,
        recipe_version=check.recipe_version,
        kind="context",
        model_recipe=None,
        prompt_sha256=None,
        recorded_at=now,
    )
    event = BrainEvent(
        company_id=company_id,
        event_id=uuid5(company_id, f"strategy-check:{action_id}"),
        kind="derivation_changed",
        resource_id=base.reader.rules.check.target.resource_id,
        action_id=action_id,
        deduplication_key=f"strategy-check:{action_id}",
        recorded_at=now,
    )
    base.rows[(BrainEvent, (company_id, event.event_id))] = event
    for model, parent, values in (
        (
            BrainArtifactInput,
            ref.artifact_revision_id,
            [r.artifact_revision_id for r in manifest.artifacts],
        ),
        (
            BrainArtifactResourceInput,
            ref.artifact_revision_id,
            list(manifest.required_resource_ids),
        ),
        (
            BrainDerivationSource,
            derivation_id,
            [r.source_revision_id for r in manifest.contributors],
        ),
        (BrainDerivationEvidence, derivation_id, [r.evidence_id for r in manifest.evidence]),
    ):
        base.edges[(model.__tablename__, parent)] = values
    facts = StrategyVerifierReceipt(action, receipt, 1, ref, parameters)
    return facts, ref, event
