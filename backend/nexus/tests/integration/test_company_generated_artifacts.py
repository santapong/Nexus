"""Native actor publication preserves source heads and exact M1 counters/intent/accounting."""

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_input_models import BrainArtifactInput, BrainArtifactResourceInput
from nexus.company.brain.derivation_models import BrainDerivation
from nexus.company.brain.source_models import BrainArtifactRevision, BrainSourceHead
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.harness.journal_models import CostHold
from nexus.tests.generated_artifact_fixture import generated_scenario
from nexus.tests.generated_artifact_support import generated_factory as generated_factory
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.integration.test_company_execution_store import identity


async def test_actor_issued_intent_publishes_and_replays_without_head_or_counter_changes(
    generated_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    scenario = await generated_scenario(generated_factory, tmp_path)
    async with generated_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        before_heads = (
            await session.execute(
                select(
                    BrainSourceHead.source_id,
                    BrainSourceHead.current_revision_id,
                    BrainSourceHead.generation,
                )
            )
        ).all()
    reference = await scenario.publisher.publish(
        scenario.lease,
        identity(scenario.lease.actor_id),
        scenario.action.action_id,
        scenario.prepared,
    )
    assert await scenario.blobs.read(reference) == scenario.prepared.raw_bytes
    assert (
        await scenario.publisher.publish(
            scenario.lease,
            identity(scenario.lease.actor_id),
            scenario.action.action_id,
            scenario.prepared,
        )
        == reference
    )
    from nexus.tests.generated_artifact_validator import NativeReportValidator

    assert isinstance(scenario.validator, NativeReportValidator) and scenario.validator.calls >= 3
    async with generated_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        row = await session.get(BrainArtifactRevision, (COMPANY, reference.artifact_revision_id))
        assert (
            row is not None
            and row.resource_id == scenario.rules[0].target.resource_id
            and row.derivation_id is not None
            and row.data_classification == "internal"
        )
        derivation = await session.get(BrainDerivation, (COMPANY, row.derivation_id))
        assert (
            derivation is not None and derivation.recipe_version == scenario.prepared.recipe_version
        )
        edges = (
            await session.scalars(
                select(BrainArtifactInput.input_artifact_revision_id).where(
                    BrainArtifactInput.artifact_revision_id == reference.artifact_revision_id
                )
            )
        ).all()
        assert set(edges) == {
            row.artifact_revision_id for row in scenario.prepared.inputs.artifacts
        }
        resources = (
            await session.scalars(
                select(BrainArtifactResourceInput.resource_id).where(
                    BrainArtifactResourceInput.artifact_revision_id
                    == reference.artifact_revision_id
                )
            )
        ).all()
        assert set(resources) == set(scenario.prepared.inputs.required_resource_ids)
        assert (
            await session.execute(
                select(
                    BrainSourceHead.source_id,
                    BrainSourceHead.current_revision_id,
                    BrainSourceHead.generation,
                )
            )
        ).all() == before_heads
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1
        intent = await session.get(EffectIntent, (COMPANY, scenario.action.action_id))
        hold = await session.get(CostHold, scenario.action.action_id)
        assert intent is not None and intent.state == "intent" and intent.receipt_json is None
        assert hold is not None and hold.state == "held" and hold.actual_usd is None
