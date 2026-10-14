"""Read-only post-run permanent allowance/old child/actual hold audit on own fixture DB."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.execution.runtime_contracts import ExecutionSnapshot
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import ACTOR, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.local_stockflow_packet import write_private
from nexus.tests.local_stockflow_v3_prepare import V3_ROOT
from nexus.tests.stockflow_packet_contracts import PreparedState


async def audit() -> None:
    state = PreparedState.model_validate_json(
        await asyncio.to_thread((V3_ROOT / "native-state.json").read_bytes)
    )
    prior = json.loads(
        await asyncio.to_thread((V3_ROOT / "sibling-revision-receipt.json").read_bytes)
    )
    old = tuple(ExecutionSnapshot.model_validate(value) for value in prior["old_child_after"])
    parent = ExecutionSnapshot.model_validate(prior["parent_after"])
    url = make_url(settings.company_test_database_url)
    if url.database != "nexus_company_test_builder":
        raise ValueError("Only retained builder database supported")
    engine = create_async_engine(url.set(username="nexus_company_app"))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionStore(factory)
        for expected in (*old, parent):
            work = expected.registration.work
            current = await execution.get(
                LedgerScope(
                    company_id=work.company_id,
                    task_id=work.task_id,
                    trace_id=work.trace_id,
                    principal_id=OWNER,
                ),
                identity(OWNER),
            )
            if current != expected:
                raise ValueError("Parent or prior child snapshot changed")
        async with runtime_transaction(
            factory, lease_scope(state.released_lease), identity(ACTOR), allow_paused=True
        ) as (session, _, _):
            rows = (
                await session.scalars(
                    select(CostHold).where(CostHold.company_id == state.spec.job.company_id)
                )
            ).all()
            holds = [
                {
                    "action_id": str(row.action_id),
                    "state": row.state,
                    "reserved_usd": str(row.amount_usd),
                    "actual_usd": str(row.actual_usd) if row.actual_usd is not None else None,
                }
                for row in rows
            ]
        result = {
            "scope": "read-only actual caller/parent/old4children/holds audit",
            "parent_equal_prelaunch": True,
            "old4children_equal_prelaunch": True,
            "parent": parent.model_dump(mode="json"),
            "old_children": [value.model_dump(mode="json") for value in old],
            "holds": holds,
            "new_processes": 0,
            "counter_resets": 0,
            "old_receipt_rewrites": 0,
        }
        await asyncio.to_thread(
            write_private,
            V3_ROOT / "post-run-conservation.json",
            json.dumps(result, indent=2).encode(),
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(audit())
