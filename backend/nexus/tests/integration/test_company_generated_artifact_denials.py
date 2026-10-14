"""Concrete actor/action/input/metadata rollback boundaries on actual native issued work."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.management.generated_artifact_identity import generated_reference
from nexus.tests.generated_artifact_fixture import generated_scenario
from nexus.tests.generated_artifact_support import generated_factory as generated_factory
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


@pytest.mark.parametrize(
    "failure", ["owner", "fence", "run", "mode", "action", "bytes", "inputs", "resources"]
)
async def test_native_source_read_and_decoded_payload_never_replace_issued_fence_action_or_inputs(
    generated_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    scenario = await generated_scenario(generated_factory, tmp_path)
    lease, prepared, action_id, signed = (
        scenario.lease,
        scenario.prepared,
        scenario.action.action_id,
        identity(scenario.lease.actor_id),
    )
    if failure == "owner":
        signed = identity(OWNER)
    elif failure in {"fence", "run", "mode"}:
        lease = lease.model_copy(
            update={"fence": lease.fence + 1}
            if failure == "fence"
            else {"run_id": uuid4()}
            if failure == "run"
            else {"mode": "reconcile"}
        )
    elif failure == "action":
        action_id = uuid4()
    elif failure == "bytes":
        raw = b"unsupported caller narrative"
        prepared = prepared.model_copy(
            update={"raw_bytes": raw, "output_sha256": hashlib.sha256(raw).hexdigest()}
        )
    elif failure == "inputs":
        prepared = prepared.model_copy(update={"input_snapshot_sha256": "f" * 64})
    else:
        prepared = prepared.model_copy(
            update={
                "inputs": prepared.inputs.model_copy(
                    update={"required_resource_ids": (scenario.rules[0].target.resource_id,)}
                )
            }
        )
    with pytest.raises(ValueError):
        await scenario.publisher.publish(lease, signed, action_id, prepared)
    reference = generated_reference(scenario.prepared, scenario.action.action_id)
    async with generated_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert (
            await session.get(BrainArtifactRevision, (COMPANY, reference.artifact_revision_id))
            is None
        )


async def test_post_blob_metadata_failure_is_pending_not_known_success_or_receipt(
    generated_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await generated_scenario(generated_factory, tmp_path)
    import nexus.company.management.generated_artifact_rows as rows

    async def interruption(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Explicit fixture interruption before native derivation completion")

    monkeypatch.setattr(rows, "save_derivation", interruption)
    with pytest.raises(RuntimeError, match="Explicit fixture interruption"):
        await scenario.publisher.publish(
            scenario.lease,
            identity(scenario.lease.actor_id),
            scenario.action.action_id,
            scenario.prepared,
        )
    reference = generated_reference(scenario.prepared, scenario.action.action_id)
    assert await scenario.blobs.read(reference) == scenario.prepared.raw_bytes
    async with generated_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert (
            await session.get(BrainArtifactRevision, (COMPANY, reference.artifact_revision_id))
            is None
        )
        from nexus.execution.runtime_models import EffectIntent
        from nexus.harness.journal_models import CostHold

        intent = await session.get(EffectIntent, (COMPANY, scenario.action.action_id))
        hold = await session.get(CostHold, scenario.action.action_id)
        assert intent is not None and intent.state == "intent" and intent.receipt_json is None
        assert hold is not None and hold.state == "held" and hold.actual_usd is None


async def test_artifact_target_reader_without_actual_input_read_cannot_receive_native_report(
    generated_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    scenario = await generated_scenario(generated_factory, tmp_path, extra_reader=True)
    with pytest.raises(ValueError, match="resource access is unavailable"):
        await scenario.publisher.publish(
            scenario.lease,
            identity(scenario.lease.actor_id),
            scenario.action.action_id,
            scenario.prepared,
        )
    reference = generated_reference(scenario.prepared, scenario.action.action_id)
    async with generated_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert (
            await session.get(BrainArtifactRevision, (COMPANY, reference.artifact_revision_id))
            is None
        )
