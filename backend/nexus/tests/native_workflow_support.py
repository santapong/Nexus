"""Exclusive native workflow DB and actual issued report/check public service fixture."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.check_contracts import ReportCheckResult
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactActionParameters
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_store import reserve_dispatch
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_store import next_segment_id
from nexus.execution.runtime_support import runtime_transaction, snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.generated_artifact_fixture import GeneratedScenario, generated_scenario, ledger
from nexus.tests.integration.test_company_directory import OWNER, migrate
from nexus.tests.integration.test_company_execution_store import identity


@pytest.fixture
async def workflow_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Normal company profile on an exact isolated database, with non-superuser runtime."""
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_native_workflow"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@dataclass(frozen=True)
class KnownCheck:
    scenario: GeneratedScenario
    action: ActionProposal
    command: SegmentCommand
    original_lease: ExecutionLease


def artifact_receipt(
    action: ActionProposal,
    reference: ArtifactRef,
) -> ActionReceipt:
    """Bind actual published artifact bytes to the exact issued action identity."""
    return ActionReceipt(
        company_id=action.company_id,
        receipt_id=uuid4(),
        action_id=action.action_id,
        task_id=action.task_id,
        trace_id=action.trace_id,
        proposal_hash=action_hash(action),
        outcome="succeeded",
        recorded_at=datetime.now(UTC),
        artifacts=(reference,),
    )


async def known_check(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
) -> KnownCheck:
    """Actual report→receipt→independent check→receipt, before acceptance exists."""
    scenario = await published_author(factory, root)
    action, command = await prepare_check_dispatch(factory, scenario)
    verifier = scenario.payload.children[1].binding
    lease = await scenario.execution.recover_dispatched(
        ledger(verifier),
        identity(verifier.actor_id),
        uuid4(),
        command.segment_id,
    )
    prepared = await scenario.producer.prepare_check(
        lease, identity(verifier.actor_id), scenario.action.action_id
    )
    await scenario.effects.begin(lease, identity(verifier.actor_id), action.action_id)
    protected = await scenario.publisher.publish(
        lease, identity(verifier.actor_id), action.action_id, prepared
    )
    await scenario.effects.record_receipt(
        lease,
        identity(verifier.actor_id),
        artifact_receipt(
            action,
            ArtifactRef(
                company_id=protected.company_id,
                artifact_id=protected.artifact_id,
                reference="protected:native-check",
                revision=protected.revision,
                sha256=protected.sha256,
            ),
        ),
        actual_usd=Decimal(0),
    )
    return KnownCheck(scenario, action, command, lease)


async def published_author(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
) -> GeneratedScenario:
    """Actual production author output and receipt, before the independent check is issued."""
    scenario = await generated_scenario(factory, root, production=True)
    output = await scenario.publisher.publish(
        scenario.lease,
        identity(scenario.lease.actor_id),
        scenario.action.action_id,
        scenario.prepared,
    )
    await scenario.effects.record_receipt(
        scenario.lease,
        identity(scenario.lease.actor_id),
        artifact_receipt(
            scenario.action,
            ArtifactRef(
                company_id=output.company_id,
                artifact_id=output.artifact_id,
                reference="protected:native-report",
                revision=output.revision,
                sha256=output.sha256,
            ),
        ),
        actual_usd=Decimal(0),
    )
    return scenario


async def prepare_check_dispatch(
    factory: async_sessionmaker[AsyncSession],
    scenario: GeneratedScenario,
    *,
    reserve: bool = True,
) -> tuple[ActionProposal, SegmentCommand]:
    """Pending check preparation releases capacity; actual owner approval pins the dispatch."""
    verifier = scenario.payload.children[1].binding
    lease = await scenario.execution.claim(ledger(verifier), identity(verifier.actor_id), uuid4())
    prepared = await scenario.producer.prepare_check(
        lease, identity(verifier.actor_id), scenario.action.action_id
    )
    result = ReportCheckResult.model_validate_json(prepared.raw_bytes)
    action = ActionProposal(
        company_id=verifier.company_id,
        action_id=uuid4(),
        task_id=verifier.task_id,
        trace_id=verifier.trace_id,
        actor_id=verifier.actor_id,
        revision=1,
        tool=scenario.rules[1].tool,
        tool_version="v1",
        resource=scenario.rules[1].resource_symbol,
        parameters=GeneratedArtifactActionParameters(
            recipe_version=prepared.recipe_version,
            output_sha256=prepared.output_sha256,
            input_snapshot_sha256=prepared.input_snapshot_sha256,
            verification_target_sha256=result.target_sha256,
            author_action_id=scenario.action.action_id,
        ).model_dump(mode="json", exclude_none=True),
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.03"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(action, ledger(verifier))
    await scenario.execution.await_approval(lease, identity(verifier.actor_id), action.action_id)
    await journal.approve_registered(
        ledger(verifier).model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        ledger(verifier),
        action.action_id,
        datetime.now(UTC),
        (),
        identity=identity(verifier.actor_id),
    )
    async with runtime_transaction(factory, ledger(verifier), identity(verifier.actor_id)) as (
        session,
        _,
        _,
    ):
        work = await session.get(ExecutionWork, (verifier.company_id, verifier.task_id))
        assert work is not None
        command = SegmentCommand(
            company_id=verifier.company_id,
            task_id=verifier.task_id,
            trace_id=verifier.trace_id,
            actor_id=verifier.actor_id,
            workspace_id=verifier.workspace_id,
            run_id=verifier.run_id,
            action_id=action.action_id,
            segment_id=next_segment_id(snapshot(work)),
        )
        if reserve:
            await reserve_dispatch(
                session,
                command,
                workflow_name=verifier.workflow_name,
                workflow_version=verifier.workflow_version,
            )
    return action, command
