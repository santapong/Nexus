"""Registered target reads require native bindings and preserve all lease publication gates."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.acceptance_support import resolve_native_target, resolve_target
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.native_registered_target import read_registered_verification_target
from nexus.execution.native_report_worker import execute_native_report
from nexus.execution.runtime_support import db_now, runtime_transaction
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_generated_artifact_lifecycle import revoke_source
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.integration.test_company_operating_loop import queued_command
from nexus.tests.operating_loop_support import configured_loop, decide_existing
from nexus.tests.operating_loop_support import loop_factory as loop_factory


async def test_actual_registered_target_has_no_lease_and_false_bindings_or_revoked_sources_deny(
    loop_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    loop, case = await configured_loop(loop_factory, tmp_path)
    author = await loop.tick(control(), identity(OWNER))
    assert author.pending
    await decide_existing(loop_factory, author.pending)
    dispatched = await loop.tick(control(), identity(OWNER))
    assert dispatched.scheduled and dispatched.scheduled.workflow_id
    command = await queued_command(loop_factory, dispatched.scheduled.workflow_id)
    assert (
        await execute_native_report(case.native, command, workflow_id=command.workflow_id)
    ).status == "published"
    binding = case.payload.children[1].binding
    signed = identity(binding.actor_id)
    before = await saved_m1(loop_factory)
    async with runtime_transaction(loop_factory, ledger_scope(binding), signed) as (
        session,
        control_row,
        _,
    ):
        target = await read_registered_verification_target(
            session,
            control_row,
            binding,
            signed,
            loop.registration.action_id("author"),
            case.native.publisher.catalog,
            case.native.artifacts,
            case.native.publisher.freshness,
        )
        assert target.verifier == binding and target.author == case.payload.children[0].binding
        for field, value in (
            ("run_id", uuid4()),
            ("trace_id", uuid4()),
            ("company_id", uuid4()),
            ("workflow_version", "old"),
        ):
            with pytest.raises(ValueError):
                await read_registered_verification_target(
                    session,
                    control_row,
                    binding.model_copy(update={field: value}),
                    signed,
                    loop.registration.action_id("author"),
                    case.native.publisher.catalog,
                    case.native.artifacts,
                    case.native.publisher.freshness,
                )
        with pytest.raises(ValueError):
            await read_registered_verification_target(
                session,
                control_row,
                binding,
                identity(OWNER),
                loop.registration.action_id("author"),
                case.native.publisher.catalog,
                case.native.artifacts,
                case.native.publisher.freshness,
            )
    assert await saved_m1(loop_factory) == before
    lease = await case.native.execution.claim(ledger_scope(binding), signed, uuid4())
    async with runtime_transaction(loop_factory, ledger_scope(binding), signed) as (
        session,
        control_row,
        _,
    ):
        now = await db_now(session)
        assert canonical_sha256(
            await resolve_target(
                session, control_row, lease, loop.registration.action_id("author"), now
            )
        ) == canonical_sha256(target)
        assert (
            await resolve_native_target(
                session, control_row, lease, loop.registration.action_id("author"), now
            )
            == target
        )
        for changed in (
            lease.model_copy(update={"mode": "reconcile"}),
            lease.model_copy(update={"fence": lease.fence + 1}),
        ):
            with pytest.raises(ValueError):
                await resolve_target(
                    session, control_row, changed, loop.registration.action_id("author"), now
                )
    await case.native.execution.release(lease, signed)
    await revoke_source(loop_factory, binding.actor_id)
    async with runtime_transaction(loop_factory, ledger_scope(binding), signed) as (
        session,
        control_row,
        _,
    ):
        with pytest.raises(ValueError):
            await read_registered_verification_target(
                session,
                control_row,
                binding,
                signed,
                loop.registration.action_id("author"),
                case.native.publisher.catalog,
                case.native.artifacts,
                case.native.publisher.freshness,
            )
