"""Actual distinct M1 verification remains descriptive and never publishes work acceptance."""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.verifier import independent_candidate
from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.tests.builder_runtime_support import builder_factory as builder_factory
from nexus.tests.builder_runtime_support import scenario
from nexus.tests.builder_verifier_support import verifier
from nexus.tests.integration.test_company_directory import ACTOR
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import VERIFIER


async def test_actual_distinct_native_verifier_uses_protected_bytes_but_no_acceptance(
    builder_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    author = await scenario(builder_factory, tmp_path)
    first = await author.runner.run(
        author.lease, identity(ACTOR), author.action, author.spec, author.guard
    )
    assert first is not None
    check = await verifier(author)
    second = await check.runner.run(
        check.lease, identity(VERIFIER), check.action, check.spec, check.guard
    )
    assert second is not None
    candidate = await independent_candidate(
        builder_factory, check.lease, identity(VERIFIER), first, second, check.guard
    )
    assert candidate.verdict == "pass" and "mechanical_candidate_only" in candidate.limitations
    with pytest.raises(ValueError):
        await independent_candidate(
            builder_factory, author.lease, identity(ACTOR), first, first, author.guard
        )
    async with runtime_transaction(
        builder_factory, lease_scope(check.lease), identity(VERIFIER)
    ) as (session, _, _):
        assert await session.scalar(select(func.count()).select_from(ManagementWorkAcceptance)) == 0
