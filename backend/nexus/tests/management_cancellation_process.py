"""Separate actual restricted-role process observes durable cancellation and issues no claim."""

from __future__ import annotations

import asyncio
import json
import sys
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.company.access import VerifiedIdentity
from nexus.company.management.cancellation_support import WorkCancelledError
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal_contracts import LedgerScope


async def main() -> None:
    """Use caller-owned actual test identities/work bindings; no owner/worker record is invented."""
    url, scope_json, identity_json = sys.argv[1:4]
    engine = create_async_engine(url)
    try:
        scope = LedgerScope.model_validate_json(scope_json)
        identity = VerifiedIdentity.model_validate_json(identity_json)
        try:
            await ExecutionStore(async_sessionmaker(engine, expire_on_commit=False)).claim(
                scope, identity, uuid4()
            )
        except WorkCancelledError:
            sys.stdout.write(json.dumps({"outcome": "durable_cancelled", "permit": False}))
        else:
            raise AssertionError("Cancelled task received a fresh claim in another process")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
