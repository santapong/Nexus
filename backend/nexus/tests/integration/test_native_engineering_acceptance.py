"""Actual model-free public native receipts/protected engineering proof/independent acceptance."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.execution.management_checks import current_accepted_work
from nexus.execution.runtime_support import execution_row, runtime_transaction
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.engineering_fixture import EngineeringScenario, engineering_scenario
from nexus.tests.engineering_fixture import engineering_factory as engineering_factory
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import VERIFIER


async def test_actual_engineering_acceptance_replays_without_completion_or_extra_attempt(
    engineering_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await engineering_scenario(engineering_factory, tmp_path)
    arguments = {
        "author_action_id": item.author.spec.job.action_id,
        "verifier_action_id": item.verifier.spec.job.action_id,
    }
    before = await _m1_facts(engineering_factory)
    proof = await item.acceptance.prepare_verified_result(
        item.lease, identity(VERIFIER), **arguments
    )
    record = await item.acceptance.publish_verified_result(
        item.lease, identity(VERIFIER), protected_result=proof, **arguments
    )
    assert record.verdict == "pass" and len(record.proofs) == 1
    assert await _m1_facts(engineering_factory) == before
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
    job = item.author.spec.job
    scope = LedgerScope(
        company_id=COMPANY, task_id=job.task_id, trace_id=job.trace_id, principal_id=ACTOR
    )
    async with runtime_transaction(engineering_factory, scope, identity(ACTOR)) as (
        session,
        control,
        _,
    ):
        work = await execution_row(session, scope)
        accepted = await current_accepted_work(
            session,
            control,
            work,
            work,
            identity(ACTOR),
            item.acceptance.inputs.reader,
            item.acceptance.inputs.freshness,
        )
        assert accepted == record and work.state == "verifying"
        assert work.tool_attempts_used == 1 and work.model_requests_used == 0


async def test_registered_engineering_declaration_cannot_name_another_procedure(
    engineering_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    from uuid import uuid4

    import pytest

    item = await engineering_scenario(engineering_factory, tmp_path)
    before = await _m1_facts(engineering_factory)
    inputs = item.acceptance.inputs
    goal, declaration = next(iter(inputs.declarations.items()))
    inputs.declarations[goal] = declaration.model_copy(update={"procedure_id": uuid4()})
    with pytest.raises(ValueError):
        await item.acceptance.prepare_verified_result(
            item.lease,
            identity(VERIFIER),
            author_action_id=item.author.spec.job.action_id,
            verifier_action_id=item.verifier.spec.job.action_id,
        )
    assert await _acceptance_count(engineering_factory) == 0
    assert await _m1_facts(engineering_factory) == before


async def _m1_facts(factory: async_sessionmaker[AsyncSession]) -> tuple[str, ...]:
    from nexus.execution.runtime_models import EffectIntent, ExecutionWork
    from nexus.harness.journal_models import CostHold

    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        holds = (
            await session.execute(select(CostHold.state, CostHold.amount_usd, CostHold.actual_usd))
        ).all()
        assert len(holds) == 2 and all(
            state == "unknown" and amount > 0 and actual is None for state, amount, actual in holds
        )
        facts: list[str] = []
        for query in (
            select(
                ExecutionWork.task_id,
                ExecutionWork.state,
                ExecutionWork.tool_attempts_used,
                ExecutionWork.model_requests_used,
                ExecutionWork.registration_hash,
            ),
            select(
                EffectIntent.action_id,
                EffectIntent.state,
                EffectIntent.intent_fence,
                EffectIntent.receipt_json,
            ),
            select(CostHold.action_id, CostHold.state, CostHold.amount_usd, CostHold.actual_usd),
        ):
            facts.extend(str(tuple(row)) for row in (await session.execute(query)).all())
        return tuple(sorted(facts))


async def _acceptance_count(factory: async_sessionmaker[AsyncSession]) -> int:
    from sqlalchemy import func, select

    from nexus.company.management.acceptance_models import ManagementWorkAcceptance

    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        return int(
            await session.scalar(select(func.count()).select_from(ManagementWorkAcceptance)) or 0
        )


async def _change_read(
    item: EngineeringScenario,
    factory: async_sessionmaker[AsyncSession],
    proof: ArtifactRevisionRef,
    resource_id: UUID,
    *,
    active: bool,
    seconds: float | None = None,
) -> None:
    from nexus.company.brain.access import ResourceAccessStore
    from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
    from nexus.company.management.acceptance_support import acceptance_scope
    from nexus.tests.integration.test_company_brain_ingestion import owner_scope
    from nexus.tests.integration.test_company_directory import OWNER

    artifact = await item.acceptance.inputs.reader.bounded_artifact(
        acceptance_scope(item.lease, item.author.spec.job.action_id),
        identity(VERIFIER),
        proof.artifact_revision_id,
        start_byte=0,
        max_bytes=16384,
        include_history=False,
    )
    generation = next(
        row.generation for row in artifact.contributors if row.resource_id == resource_id
    )
    async with factory() as session:
        now = await session.scalar(select(func.clock_timestamp()))
    assert now is not None
    await ResourceAccessStore(factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=resource_id),
            principal_id=VERIFIER,
            active=active,
            expected_generation=generation,
            expires_at=None if seconds is None else now + timedelta(seconds=seconds),
        ),
    )


@pytest.mark.parametrize("resource", ["source", "proof"])
async def test_current_source_or_proof_revoke_denies_new_acceptance(
    engineering_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    resource: str,
) -> None:
    item = await engineering_scenario(engineering_factory, tmp_path)
    arguments = {
        "author_action_id": item.author.spec.job.action_id,
        "verifier_action_id": item.verifier.spec.job.action_id,
    }
    before = await _m1_facts(engineering_factory)
    proof = await item.acceptance.prepare_verified_result(
        item.lease, identity(VERIFIER), **arguments
    )
    target = item.acceptance.proof.target.resource_id if resource == "proof" else UUID(int=9501)
    await _change_read(item, engineering_factory, proof, target, active=False)
    with pytest.raises(ValueError):
        await item.acceptance.publish_verified_result(
            item.lease, identity(VERIFIER), protected_result=proof, **arguments
        )
    assert await _acceptance_count(engineering_factory) == 0
    assert await _m1_facts(engineering_factory) == before


async def test_exact_acceptance_replay_does_not_bypass_current_proof_read(
    engineering_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await engineering_scenario(engineering_factory, tmp_path)
    arguments = {
        "author_action_id": item.author.spec.job.action_id,
        "verifier_action_id": item.verifier.spec.job.action_id,
    }
    before = await _m1_facts(engineering_factory)
    proof = await item.acceptance.prepare_verified_result(
        item.lease, identity(VERIFIER), **arguments
    )
    record = await item.acceptance.publish_verified_result(
        item.lease, identity(VERIFIER), protected_result=proof, **arguments
    )
    await _change_read(
        item, engineering_factory, proof, item.acceptance.proof.target.resource_id, active=False
    )
    with pytest.raises(ValueError):
        await item.acceptance.publish_verified_result(
            item.lease, identity(VERIFIER), protected_result=proof, **arguments
        )
    assert record.verdict == "pass" and await _acceptance_count(engineering_factory) == 1
    assert await _m1_facts(engineering_factory) == before


async def test_proof_read_expiry_during_final_work_lookup_rolls_back_publication(
    engineering_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.builder.engineering_acceptance as publisher
    from nexus.builder.engineering_inputs import PreparedEngineeringInput
    from nexus.execution.runtime_contracts import ExecutionLease
    from nexus.execution.runtime_models import ExecutionWork
    from nexus.harness.journal_contracts import LedgerScope

    item = await engineering_scenario(engineering_factory, tmp_path)
    arguments = {
        "author_action_id": item.author.spec.job.action_id,
        "verifier_action_id": item.verifier.spec.job.action_id,
    }
    before = await _m1_facts(engineering_factory)
    proof = await item.acceptance.prepare_verified_result(
        item.lease, identity(VERIFIER), **arguments
    )
    await _change_read(
        item,
        engineering_factory,
        proof,
        item.acceptance.proof.target.resource_id,
        active=True,
        seconds=3,
    )
    in_final = False
    original_final, original_row = item.acceptance._final_time, execution_row

    async def final(
        session: AsyncSession, lease: ExecutionLease, prepared: PreparedEngineeringInput
    ) -> None:
        nonlocal in_final
        in_final = True
        try:
            await original_final(session, lease, prepared)
        finally:
            in_final = False

    async def delayed(session: AsyncSession, scope: LedgerScope) -> ExecutionWork:
        result = await original_row(session, scope)
        if in_final:
            await session.execute(select(func.pg_sleep(3.3)))
        return result

    monkeypatch.setattr(item.acceptance, "_final_time", final)
    monkeypatch.setattr(publisher, "execution_row", delayed)
    with pytest.raises(ValueError):
        await item.acceptance.publish_verified_result(
            item.lease, identity(VERIFIER), protected_result=proof, **arguments
        )
    assert await _acceptance_count(engineering_factory) == 0
    assert await _m1_facts(engineering_factory) == before


async def test_spliced_action_actor_or_fence_cannot_prepare_engineering_proof(
    engineering_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    item = await engineering_scenario(engineering_factory, tmp_path)
    before = await _m1_facts(engineering_factory)
    for case in ("author_action", "verifier_action", "actor", "fence"):
        arguments = {
            "author_action_id": uuid4()
            if case == "author_action"
            else item.author.spec.job.action_id,
            "verifier_action_id": uuid4()
            if case == "verifier_action"
            else item.verifier.spec.job.action_id,
        }
        lease = (
            item.lease.model_copy(update={"fence": item.lease.fence + 1})
            if case == "fence"
            else item.lease
        )
        caller = identity(ACTOR if case == "actor" else VERIFIER)
        with pytest.raises(ValueError):
            await item.acceptance.prepare_verified_result(lease, caller, **arguments)
    assert await _acceptance_count(engineering_factory) == 0
    assert await _m1_facts(engineering_factory) == before


async def test_current_source_revoke_after_actual_input_load_denies_proof_commit(
    engineering_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.builder.engineering_inputs import PreparedEngineeringInput
    from nexus.company.access import VerifiedIdentity
    from nexus.company.brain.base import BrainReadScope
    from nexus.company.management.acceptance import VerificationSpec

    item = await engineering_scenario(engineering_factory, tmp_path)
    before = await _m1_facts(engineering_factory)
    original = item.acceptance.inputs.load

    async def revoke_after_load(
        scope: BrainReadScope,
        caller: VerifiedIdentity,
        target: VerificationSpec,
        verifier_action_id: UUID,
    ) -> PreparedEngineeringInput:
        result = await original(scope, caller, target, verifier_action_id)
        await _change_read(
            item, engineering_factory, result.command.author_output, UUID(int=9501), active=False
        )
        return result

    monkeypatch.setattr(item.acceptance.inputs, "load", revoke_after_load)
    with pytest.raises(ValueError):
        await item.acceptance.prepare_verified_result(
            item.lease,
            identity(VERIFIER),
            author_action_id=item.author.spec.job.action_id,
            verifier_action_id=item.verifier.spec.job.action_id,
        )
    assert await _acceptance_count(engineering_factory) == 0
    assert await _m1_facts(engineering_factory) == before


async def test_new_publisher_reconciles_known_result_from_durable_witness_without_reissue(
    engineering_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    from nexus.builder.engineering_artifacts import EngineeringArtifactPublisher

    item = await engineering_scenario(engineering_factory, tmp_path)
    before = await _m1_facts(engineering_factory)
    old = item.runner.publisher
    assert isinstance(old, EngineeringArtifactPublisher)
    item.runner.publisher = EngineeringArtifactPublisher(
        engineering_factory, old.blobs, old.target, old.policy, old.jobs_root
    )
    assert not item.runner.publisher.witnesses
    recovered = await item.runner.reconcile(
        item.lease,
        identity(VERIFIER),
        item.verifier_action,
        item.verifier.spec,
        item.verifier_guard,
    )
    assert recovered == item.verifier and not item.runner.publisher.witnesses
    assert await _m1_facts(engineering_factory) == before
    assert await _acceptance_count(engineering_factory) == 0
