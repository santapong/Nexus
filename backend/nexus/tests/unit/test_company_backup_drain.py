"""Actual owned handles supply exit evidence; decoding a witness supplies no worker authority."""

import asyncio
import sys
from uuid import UUID

import pytest

from nexus.operations.backup_drain import OwnedWorkerDrain

COMPANY = UUID(int=1)


async def test_live_owned_worker_is_not_drained_then_waited_exit_is_bound() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time;time.sleep(30)"
    )
    drain = OwnedWorkerDrain(COMPANY, "assigned_source", (process,))
    try:
        with pytest.raises(ValueError, match="not drained"):
            await drain.observe(COMPANY)
        process.kill()
        code = await process.wait()
        witness = await drain.observe(COMPANY)
        assert witness.company_id == COMPANY and witness.source_database == "assigned_source"
        assert tuple((row.pid, row.exit_code) for row in witness.workers) == ((process.pid, code),)
        with pytest.raises(ValueError, match="not drained"):
            await drain.observe(UUID(int=2))
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


async def test_duplicate_process_registration_cannot_claim_inventory() -> None:
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
    await process.wait()
    with pytest.raises(ValueError, match="inventory"):
        OwnedWorkerDrain(COMPANY, "assigned_source", (process, process))
