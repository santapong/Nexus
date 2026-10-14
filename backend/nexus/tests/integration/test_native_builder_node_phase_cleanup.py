"""Actual one-container M1 phase transition and nofollow denial on normal company015."""

import base64
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.tests.builder_node_phase_support import phase_repository
from nexus.tests.builder_node_support import empty_config, node_scenario
from nexus.tests.builder_node_support import node_factory as node_factory
from nexus.tests.integration.test_company_directory import ACTOR
from nexus.tests.integration.test_company_execution_store import identity


@pytest.mark.parametrize("splice", [False, True])
async def test_actual_m1_phase_cleanup_preserves_records_or_denies_spliced_baseline(
    node_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    splice: bool,
) -> None:
    repository, pin = phase_repository(tmp_path, splice_baseline=splice)
    item = await node_scenario(
        node_factory, tmp_path, qualified=(repository, pin, empty_config(tmp_path))
    )
    result = await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    assert result is not None
    logs = b"".join(base64.b64decode(row.content_base64) for row in result.logs)
    assert b"actual_baseline_phase_retained" in logs
    if splice:
        assert result.outcome == "commands_failed"
        assert "phase_cleanup_failed" in result.limitations
        assert len(result.commands) == 4 and all(row.phase == "baseline" for row in result.commands)
        assert all(row.exit_code == 0 for row in result.commands)
        assert b"actual_post_cleanup" not in logs
    else:
        assert result.outcome == "commands_succeeded"
        assert len(result.commands) == 8 and len(result.artifacts) == 8
        assert b"actual_post_cleanup_baseline_outputs_logs_ro_source_retained" in logs
    assert (
        await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
        == result
    )
