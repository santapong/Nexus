"""Actual restricted M1 intent, one local sandbox, known replay and honest unknown intent."""

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder import runner as runner_module
from nexus.builder.process import ProcessCapture, bounded_call
from nexus.company.brain.artifact_input_models import BrainArtifactInput
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.tests.builder_runtime_support import builder_factory as builder_factory
from nexus.tests.builder_runtime_support import scenario
from nexus.tests.integration.test_company_directory import ACTOR
from nexus.tests.integration.test_company_execution_store import identity


async def test_actual_intent_one_native_process_private_output_and_no_replay(
    builder_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await scenario(builder_factory, tmp_path)
    invoked = 0

    async def counted(
        argv: tuple[str, ...],
        *,
        name: str,
        action_id: str,
        company_id: str,
        seconds: int,
        stdout_limit: int,
        stderr_limit: int,
        watchdog: Callable[[], Awaitable[None]],
    ) -> ProcessCapture:
        nonlocal invoked
        invoked += 1
        return await bounded_call(
            argv,
            name=name,
            action_id=action_id,
            company_id=company_id,
            seconds=seconds,
            stdout_limit=stdout_limit,
            stderr_limit=stderr_limit,
            watchdog=watchdog,
        )

    monkeypatch.setattr(runner_module, "bounded_call", counted)
    result = await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    assert result is not None and result.outcome == "commands_succeeded"
    assert result.observed_memory_max == 67108864 and len(result.commands) == 2
    assert len(result.artifacts) == 2
    assert (
        await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
        == result
    )
    assert invoked == 1
    async with runtime_transaction(
        builder_factory, lease_scope(item.lease), identity(ACTOR), allow_paused=True
    ) as (session, _, _):
        row = await session.get(EffectIntent, (item.lease.company_id, item.action.action_id))
        assert row is not None and row.state == "succeeded"
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1
        assert item.runner.publisher is not None
        reference = item.runner.publisher.reference(result)
        stored = await session.get(
            BrainArtifactRevision, (reference.company_id, reference.artifact_revision_id)
        )
        assert stored is not None and stored.sha256 == reference.sha256
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainArtifactInput)
                .where(BrainArtifactInput.artifact_revision_id == reference.artifact_revision_id)
            )
            == 1
        )


async def test_existing_unobserved_native_intent_never_invokes_again(
    builder_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await scenario(builder_factory, tmp_path)
    start = await item.runner.effects.begin(
        item.lease, identity(ACTOR), item.action.action_id, before_intent=item.guard
    )
    assert start.permit_external_call
    assert (
        await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
        is None
    )
    async with runtime_transaction(builder_factory, lease_scope(item.lease), identity(ACTOR)) as (
        session,
        _,
        _,
    ):
        row = await session.get(EffectIntent, (item.lease.company_id, item.action.action_id))
        assert row is not None and row.state == "intent" and row.receipt_json is None


async def test_actual_missing_tool_baseline_is_failed_not_verified(
    builder_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await scenario(builder_factory, tmp_path, argv=("/definitely-absent-node", "--version"))
    result = await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    assert result is not None and result.outcome == "tool_missing"
    assert len(result.commands) == 1 and result.commands[0].phase == "baseline"
    assert not result.artifacts


async def test_exact_protected_patch_changes_only_post_and_all_input_edges(
    builder_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    patch = (
        b"diff --git a/answer.txt b/answer.txt\n"
        b"index c0b9cbd..fcfa213 100644\n--- a/answer.txt\n+++ b/answer.txt\n"
        b"@@ -1 +1 @@\n-actual committed fixture\n\\ No newline at end of file\n"
        b"+actual protected post patch\n\\ No newline at end of file\n"
    )
    item = await scenario(builder_factory, tmp_path, patch_raw=patch)
    result = await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    assert (
        result is not None and result.outcome == "commands_succeeded" and len(result.artifacts) == 2
    )
    assert result.artifacts[0].metadata.sha256 != result.artifacts[1].metadata.sha256
    assert item.runner.publisher is not None
    reference = item.runner.publisher.reference(result)
    async with runtime_transaction(builder_factory, lease_scope(item.lease), identity(ACTOR)) as (
        session,
        _,
        _,
    ):
        edges = tuple(
            (
                await session.scalars(
                    select(BrainArtifactInput.input_artifact_revision_id).where(
                        BrainArtifactInput.artifact_revision_id == reference.artifact_revision_id,
                    )
                )
            ).all()
        )
        assert item.spec.protected_patch is not None
        assert set(edges) == {
            item.guard.source.metadata.artifact_revision_id,
            item.spec.protected_patch.artifact_revision_id,
        }
