"""Extracted process observation preserves phase recording without database or effect execution."""

from pathlib import Path
from uuid import UUID

from nexus.execution.dbos_contracts import SegmentCommand
from nexus.tests.integration.backup_native_process import observer


async def test_nonbarrier_hook_records_only_actual_phase(tmp_path: Path) -> None:
    command = SegmentCommand(
        company_id=UUID(int=1),
        task_id=UUID(int=2),
        trace_id=UUID(int=3),
        actor_id=UUID(int=4),
        workspace_id=UUID(int=5),
        run_id=UUID(int=6),
        action_id=UUID(int=7),
        segment_id=UUID(int=8),
    )
    await observer(tmp_path, None)("intent_committed", command)
    assert (tmp_path / "phases.jsonl").read_text() == "intent_committed\n"
    assert not (tmp_path / "barrier-reached").exists()
