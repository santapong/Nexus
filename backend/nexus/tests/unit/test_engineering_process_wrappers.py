"""Process-only result barrier occurs after the original exact durable output save."""

from pathlib import Path
from uuid import uuid4

from nexus.execution.dbos_contracts import SegmentCommand
from nexus.tests.engineering_check_support import check_input
from nexus.tests.engineering_process_wrappers import ObservedResults


async def test_result_store_barrier_observes_actual_saved_bytes(tmp_path: Path) -> None:
    value = check_input()
    result = value.verifier
    job = result.spec.job
    command = SegmentCommand(
        company_id=job.company_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        actor_id=job.actor_id,
        workspace_id=job.workspace_id,
        run_id=job.run_id,
        action_id=job.action_id,
        segment_id=uuid4(),
    )
    phases: list[str] = []
    expected_command = command
    store = None

    async def hook(phase: str, command: SegmentCommand) -> None:
        assert store is not None and await store.load(result.spec) == result
        assert command == expected_command
        phases.append(phase)

    store = ObservedResults(tmp_path / "results", hook, command)
    await store.save(result)
    assert phases == ["result_stored"]
