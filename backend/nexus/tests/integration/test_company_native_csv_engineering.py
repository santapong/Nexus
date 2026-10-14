"""Actual NEW public CSV permits/protected proof/replay; launch is separately Root gated."""

import asyncio
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.builder.csv_artifact_loader import actual_csv_behavior
from nexus.builder.process import engine_environment
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_support import acceptance_scope
from nexus.execution.management_checks import current_accepted_work
from nexus.execution.runtime_support import execution_row, runtime_transaction
from nexus.harness.journal_contracts import LedgerScope
from nexus.settings import settings
from nexus.tests.csv_native_fixture import load_registered, run_pair, source_guard
from nexus.tests.csv_native_plan import ledger_scope
from nexus.tests.csv_native_runtime import job_scope_gate
from nexus.tests.csv_native_scope import ROOT, require_database
from nexus.tests.engineering_fixture import EngineeringScenario
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_native_engineering_acceptance import _change_read, _m1_facts
from nexus.tests.management_plan_support import VERIFIER


async def test_actual_public_native_csv_pair_proof_known_replay_and_current_read() -> None:
    """No migration/registration here; earlier exact setup and launch packet must be approved."""
    url = make_url(settings.company_test_database_url)
    require_database(url, application=False)
    app = create_async_engine(url.set(username="nexus_company_app"))
    factory = async_sessionmaker(app, expire_on_commit=False)
    item: EngineeringScenario | None = None
    try:
        await job_scope_gate(ROOT)
        prepared = await load_registered(factory, ROOT)
        item = await run_pair(prepared)
        before = await _m1_facts(factory)
        proof, record = await _prove(item)
        item = await _known_replay(item)
        assert await _m1_facts(factory) == before
        await _proof_replay(item, proof, record)
        await _accepted_projection(factory, item, record)
        for result in (item.author, item.verifier):
            await _assert_absent(result.container_name)
        await _current_proof_revoke(factory, item, proof)
        assert await _m1_facts(factory) == before
    finally:
        try:
            if item is not None:
                await item.runner.execution.release(item.lease, identity(VERIFIER))
        finally:
            try:
                await _terminal_state(factory)
            finally:
                await app.dispose()


async def _prove(item: EngineeringScenario) -> tuple[ArtifactRevisionRef, WorkAcceptance]:
    arguments = {
        "author_action_id": item.author.spec.job.action_id,
        "verifier_action_id": item.verifier.spec.job.action_id,
    }
    proof = await item.acceptance.prepare_verified_result(
        item.lease, identity(VERIFIER), **arguments
    )
    record = await item.acceptance.publish_verified_result(
        item.lease, identity(VERIFIER), protected_result=proof, **arguments
    )
    assert record.verdict == "pass"
    loaded = await item.acceptance.inputs.load(
        acceptance_scope(item.lease, item.author.spec.job.action_id),
        identity(VERIFIER),
        record.target,
        item.verifier.spec.job.action_id,
    )
    behaviors = actual_csv_behavior(loaded.command)
    assert len(behaviors) == 2 and all(len(row.cases) == 7 for row in behaviors)
    for result in (item.author, item.verifier):
        assert len(result.commands) == 8 and all(row.exit_code == 0 for row in result.commands)
    return proof, record


async def _known_replay(item: EngineeringScenario) -> EngineeringScenario:
    fresh = await load_registered(item.runner.factory, ROOT)
    bound = fresh.config.payload.children[0].binding
    assert fresh.runner.publisher is not item.runner.publisher
    lease = await fresh.runner.execution.claim(
        ledger_scope(bound), identity(ACTOR), uuid4(), ttl_seconds=60
    )
    assert lease.mode == "execute"
    guard = source_guard(fresh, 0, lease)
    assert (
        await fresh.runner.run(
            lease, identity(ACTOR), fresh.config.actions[0], fresh.config.specs[0], guard
        )
        == item.author
    )
    await fresh.runner.execution.release(guard.lease, identity(ACTOR))
    renewed = await item.runner.execution.renew(item.lease, identity(VERIFIER), ttl_seconds=60)
    return replace(item, lease=renewed)


async def _proof_replay(
    item: EngineeringScenario, proof: ArtifactRevisionRef, record: WorkAcceptance
) -> None:
    arguments = {
        "author_action_id": item.author.spec.job.action_id,
        "verifier_action_id": item.verifier.spec.job.action_id,
    }
    assert (
        await item.acceptance.prepare_verified_result(item.lease, identity(VERIFIER), **arguments)
        == proof
    )
    assert (
        await item.acceptance.publish_verified_result(
            item.lease, identity(VERIFIER), protected_result=proof, **arguments
        )
        == record
    )


async def _accepted_projection(
    factory: async_sessionmaker[AsyncSession], item: EngineeringScenario, record: WorkAcceptance
) -> None:
    job = item.author.spec.job
    scope = LedgerScope(
        company_id=COMPANY, task_id=job.task_id, trace_id=job.trace_id, principal_id=ACTOR
    )
    async with runtime_transaction(factory, scope, identity(ACTOR)) as (session, control, _):
        work = await execution_row(session, scope)
        assert (
            await current_accepted_work(
                session,
                control,
                work,
                work,
                identity(ACTOR),
                item.acceptance.inputs.reader,
                item.acceptance.inputs.freshness,
            )
            == record
        )
        assert work.state == "verifying"
        assert work.tool_attempts_used == 1 and work.model_requests_used == 0


async def _current_proof_revoke(
    factory: async_sessionmaker[AsyncSession], item: EngineeringScenario, proof: ArtifactRevisionRef
) -> None:
    await _change_read(item, factory, proof, item.acceptance.proof.target.resource_id, active=False)
    with pytest.raises(ValueError):
        await item.acceptance.publish_verified_result(
            item.lease,
            identity(VERIFIER),
            protected_result=proof,
            author_action_id=item.author.spec.job.action_id,
            verifier_action_id=item.verifier.spec.job.action_id,
        )


async def _assert_absent(name: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/podman",
        "--remote=false",
        "container",
        "exists",
        name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=engine_environment(),
    )
    try:
        assert await asyncio.wait_for(process.wait(), timeout=5) == 1
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def _terminal_state(factory: async_sessionmaker[AsyncSession]) -> None:
    tables = (
        "company_execution_work",
        "company_execution_attempts",
        "company_cost_holds",
        "company_effect_intents",
        "company_action_journal",
        "company_action_authority",
        "company_management_acceptance_proofs",
        "company_management_work_acceptances",
        "company_brain_artifact_revisions",
    )
    values = {}
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        for name in tables:
            values[name] = (
                (await session.execute(text("SELECT row_to_json(t)::text FROM " + name + " t")))
                .scalars()
                .all()
            )
    with (ROOT / "native-terminal-state.json").open("x") as stream:
        json.dump(values, stream, indent=2)
