"""Real public M1 owner dispatch conformance, distinct from native plan/operating-loop admission."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Connection, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_contracts import WorkRegistration
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.proposals import NOTIFICATION_TOOL, NotificationDispatchParameters
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionLease, ExecutionRegistration
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, WORKSPACE, control
from nexus.tests.integration.test_company_execution_store import identity


def migrate014(connection: Connection, direction: str) -> None:
    backend = Path(__file__).resolve().parents[2]
    config = Config(str(backend / "alembic_company.ini"))
    config.set_main_option("script_location", str(backend / "company_alembic"))
    config.attributes["connection"] = connection
    if direction == "upgrade":
        assert set(inspect(connection).get_table_names()) <= {"company_alembic_version"}
        command.upgrade(config, "company_014")
        connection.execute(
            text("GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA public TO nexus_company_app")
        )
    else:
        command.downgrade(config, "base")


@pytest.fixture
async def dispatch_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_notifications"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    installed = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate014, "upgrade")
        installed = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                await connection.run_sync(migrate014, "downgrade")
        await admin.dispose()


async def actual_sender(
    factory: async_sessionmaker[AsyncSession],
    draft: NotificationDraft,
    *,
    approval_now: datetime | None = None,
) -> tuple[ExecutionLease, ActionProposal, EffectStore, ResourceRef]:
    task, trace, run = uuid4(), uuid4(), uuid4()
    directory = PersistentCompanyDirectory(factory)
    await directory.register_work(
        WorkRegistration(
            company_id=COMPANY,
            workspace_id=WORKSPACE,
            task_id=task,
            trace_id=trace,
            actor_id=OWNER,
            allocation_usd=Decimal(".1"),
            allowed_principals=(OWNER,),
        ),
        control(),
    )
    ledger = LedgerScope(company_id=COMPANY, task_id=task, trace_id=trace, principal_id=OWNER)
    execution = ExecutionStore(factory)
    await execution.register(
        ExecutionRegistration(
            work=WorkItem(
                company_id=COMPANY,
                task_id=task,
                trace_id=trace,
                goal_id=uuid4(),
                department="notifications",
                title="Isolated M1 owner dispatch conformance",
                acceptance=("provider-result",),
                budget_usd=Decimal(".1"),
            ),
            run_id=run,
            workflow_name="notify-conformance",
            workflow_version="v1",
            model_profile="no-model",
            model_registry_version="none",
            quota=AttemptQuota(model_requests=0, tool_attempts=2),
        ),
        ledger,
        identity(OWNER),
    )
    target = ResourceRef(company_id=COMPANY, resource_id=uuid4())
    from nexus.tests.integration.test_company_brain_ingestion import owner_scope

    await ArtifactTargetStore(factory).provision(
        owner_scope(), identity(OWNER), target, readers=(OWNER,)
    )
    params = NotificationDispatchParameters(
        draft_id=draft.draft_id,
        payload_sha256=draft.payload_sha256,
        recipient_policy_sha256=draft.recipient_policy.sha256,
    )
    proposal = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=task,
        trace_id=trace,
        actor_id=OWNER,
        revision=1,
        tool=NOTIFICATION_TOOL,
        tool_version="v1",
        resource="owner.notifications",
        parameters=params.model_dump(mode="json"),
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal(".01"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(proposal, ledger)
    await journal.approve_registered(
        ledger,
        proposal.action_id,
        action_hash(proposal),
        approval_now or datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        ledger, proposal.action_id, datetime.now(UTC), (), identity=identity(OWNER)
    )
    lease = await execution.claim(ledger, identity(OWNER), uuid4(), ttl_seconds=60)
    return lease, proposal, EffectStore(factory), target
