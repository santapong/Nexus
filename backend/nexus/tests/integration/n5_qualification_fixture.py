"""Disposable, restricted PostgreSQL helpers for synthetic model-budget tests.

Set NEXUS_TEST_MODEL_CAP_DATABASE_URL and NEXUS_TEST_MODEL_UNKNOWN_DATABASE_URL
for distinct fresh local test databases and provision ``nexus_company_app``.
A missing URL skips only its scenario. Database names and empty-schema checks do
not prove cluster ownership; the caller must ensure each cluster is disposable.
This module never drops or resets a database.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple, cast
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx2
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.base import SourceTime
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.company import CompanyMandate
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_contracts import CompanyRegistration, WorkRegistration
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.base import RevisionRef
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import (
    DueIntent,
    GoalDefinition,
    GoalMetric,
    GoalRevisionRef,
    UnknownBaseline,
)
from nexus.core.llm.company_adapter_contracts import ServerEndpoint
from nexus.core.llm.qualification_contracts import QualificationRecipe
from nexus.execution.effect_store import EffectStore
from nexus.execution.qualification_service import PreparedQualification
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_contracts import CompanyPolicy, LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, DailyBudget, WorkBudget
from nexus.harness.qualification_client import QualificationClient, QualificationRunResult
from nexus.harness.qualification_evidence import FileQualificationEvidenceStore
from nexus.tests.integration import test_company_model_qualification as existing
from nexus.tests.integration.test_company_directory import migrate
from nexus.tests.unit.test_company_provider_conformance import KEY


@dataclass(frozen=True)
class Namespace:
    company: UUID
    owner: UUID
    workspace: UUID
    goal: UUID

    @classmethod
    def for_database(cls, name: str) -> Namespace:
        company = uuid5(NAMESPACE_URL, f"nexus:n5-reusable:{name}")
        return cls(company, *(uuid5(company, item) for item in ("owner", "workspace", "goal")))

    def control(self, label: str) -> CompanyControlScope:
        return CompanyControlScope(
            company_id=self.company,
            principal_id=self.owner,
            operation_id=uuid5(self.company, label),
            trace_id=uuid5(self.company, "owner-audit"),
        )

    def identity(self) -> VerifiedIdentity:
        return VerifiedIdentity(principal_id=self.owner, workspace_id=self.workspace)

    def scope(self, task: UUID, trace: UUID) -> LedgerScope:
        return LedgerScope(
            company_id=self.company, principal_id=self.owner, task_id=task, trace_id=trace
        )


def _require_local_url(url: URL, expected_database: str) -> None:
    """Reject arbitrary remote hosts, extra connection options and non-test DB names."""
    if (
        url.drivername != "postgresql+asyncpg"
        or url.database != expected_database
        or not url.username
        or url.username == "nexus_company_app"
        or url.password is not None
    ):
        raise ValueError("A fresh named local test database and distinct admin role are required")
    query = dict(url.query)
    if url.host is None:
        if set(query) != {"host", "port"}:
            raise ValueError("A private Unix socket and explicit port are required")
        socket_path = Path(str(query["host"]))
        if not socket_path.is_absolute() or socket_path.is_symlink():
            raise ValueError("The test socket directory must be an absolute private path")
        metadata = socket_path.stat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise ValueError("The test socket directory is not private to this user")
        if not str(query["port"]).isdigit() or not 1024 < int(str(query["port"])) <= 65535:
            raise ValueError("The test socket port is invalid")
    else:
        if query or url.host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Only a direct loopback PostgreSQL endpoint is allowed")
        addresses = socket.getaddrinfo(url.host, url.port or 5432, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(row[4][0]).is_loopback for row in addresses
        ):
            raise ValueError("The test database hostname must resolve only to loopback")


@asynccontextmanager
async def disposable_factory(
    expected_database: str,
) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], Namespace]]:
    """Migrate only a fresh local test DB; retain its contents on every outcome."""
    database_urls = {
        "nexus_company_test_model_cap": "NEXUS_TEST_MODEL_CAP_DATABASE_URL",
        "nexus_company_test_model_unknown": "NEXUS_TEST_MODEL_UNKNOWN_DATABASE_URL",
    }
    if expected_database not in database_urls:
        raise ValueError("Unrecognized disposable database name")
    variable = database_urls[expected_database]
    configured = os.environ.get(variable)
    if not configured:
        pytest.skip(f"Explicit fresh test database is not configured in {variable}")
    other_urls = {
        os.environ.get(name)
        for database, name in database_urls.items()
        if database != expected_database
    }
    if configured in other_urls:
        raise ValueError("Cap and unknown scenarios require distinct databases")
    url = make_url(configured)
    _require_local_url(url, expected_database)
    if configured in {os.environ.get("DATABASE_URL"), os.environ.get("COMPANY_DATABASE_URL")}:
        raise ValueError("Test database must differ from application database configuration")
    admin = create_async_engine(url, poolclass=NullPool)
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    try:
        async with admin.begin() as connection:
            if await connection.scalar(text("SELECT current_database()")) != expected_database:
                raise ValueError(
                    "Connected database differs from the explicitly named test database"
                )
            if await connection.scalar(text("SELECT current_user")) != url.username:
                raise ValueError("Connected admin role differs from the test URL")
            role = (
                await connection.execute(
                    text(
                        "SELECT rolcanlogin,rolsuper,rolbypassrls FROM pg_roles "
                        "WHERE rolname='nexus_company_app'"
                    )
                )
            ).one_or_none()
            if role is None or tuple(role) != (True, False, False):
                raise ValueError(
                    "The separate application role must be restricted before migration"
                )
            if await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_roles r WHERE r.rolname <> 'nexus_company_app' "
                    "AND pg_has_role('nexus_company_app',r.oid,'MEMBER')"
                )
            ):
                raise ValueError("The test application role must not inherit other roles")
            if await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_namespace n WHERE n.nspname='public' "
                    "AND pg_has_role('nexus_company_app',n.nspowner,'MEMBER')"
                )
            ):
                raise ValueError("The test application role must not own the public schema")
            if await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_namespace "
                    "WHERE nspname NOT IN ('public', 'information_schema') "
                    "AND nspname NOT LIKE 'pg_%'"
                )
            ):
                raise ValueError("Test database contains unexpected schemas")
            if await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public'"
                )
            ):
                raise ValueError("Test database public schema contains existing relations")
            if await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='public'"
                )
            ):
                raise ValueError("Test database public schema contains existing functions")
            await connection.run_sync(migrate, "upgrade")
            assert (
                await connection.scalar(text("SELECT version_num FROM company_alembic_version"))
                == "company_017"
            )
            schema = (
                await connection.execute(
                    text(
                        "SELECT count(*),bool_and(c.relrowsecurity AND c.relforcerowsecurity) "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='public' AND c.relkind='r' "
                        "AND c.relname LIKE 'company_%' AND c.relname <> 'company_alembic_version'"
                    )
                )
            ).one()
            assert tuple(schema) == (74, True)
        async with app.connect() as connection:
            assert await connection.scalar(text("SELECT current_user")) == "nexus_company_app"
            assert not await connection.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
            assert not await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_roles r WHERE r.oid <> "
                    "(SELECT oid FROM pg_roles WHERE rolname=current_user) "
                    "AND pg_has_role(current_user,r.oid,'MEMBER')"
                )
            )
            assert not await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_namespace n WHERE n.nspname='public' "
                    "AND pg_has_role(current_user,n.nspowner,'MEMBER')"
                )
            )
            for name in ("fsync", "synchronous_commit", "full_page_writes"):
                assert await connection.scalar(text(f"SHOW {name}")) == "on"
        yield (
            async_sessionmaker(app, expire_on_commit=False),
            Namespace.for_database(expected_database),
        )
    finally:
        await app.dispose()
        await admin.dispose()


async def make_goal(
    factory: async_sessionmaker[AsyncSession], ns: Namespace, root: Path
) -> GoalRevisionRef:
    journal = CompanyJournal(factory)
    control = ns.control("bootstrap")
    await journal.create_company(
        CompanyPolicy(
            company_id=ns.company,
            owner_id=ns.owner,
            policy_version="qualification-policy-v1",
            price_version="qualification-prices-v1",
        ),
        ns.scope(control.operation_id, control.trace_id),
    )
    await PersistentCompanyDirectory(factory).bootstrap(
        CompanyRegistration(company_id=ns.company, workspace_id=ns.workspace, owner_id=ns.owner),
        control,
    )
    mandate = await ManagementControlStore(factory).publish_mandate(
        ns.control("mandate"),
        ns.identity(),
        CompanyMandate(
            company_id=ns.company,
            owner_id=ns.owner,
            version="v1",
            purpose="Public SDK qualification only",
            goals=(ns.goal,),
        ),
        expected_revision_id=None,
    )
    ref = RevisionRef.model_validate_json(
        mandate.model_dump_json(include=set(RevisionRef.model_fields))
    )
    blobs = root / "blobs"
    blobs.mkdir(mode=0o700)
    retriever = PersistentBrainRetriever(
        factory,
        ProtectedBlobStore(blobs, storage_symbol="qualification.public.blobs.v1"),
        limits=RetrievalLimits(),
    )
    saved = await GoalStore(factory, retriever).publish(
        ns.control("goal"),
        ns.identity(),
        GoalDefinition(
            company_id=ns.company,
            goal_id=ns.goal,
            owner_id=ns.owner,
            title="Observe public SDK conformance",
            mandate=ref,
            metrics=(
                GoalMetric(
                    company_id=ns.company,
                    metric_id="qualification.observations",
                    unit="count",
                    comparator="ge",
                    target=Decimal(1),
                    baseline=UnknownBaseline(reason="No live quality or SDK observations"),
                ),
            ),
            due=DueIntent(
                source_time=SourceTime(precision="unknown", value=None, basis="Not scheduled")
            ),
        ),
        version="v1",
        expected_revision_id=None,
    )
    return GoalRevisionRef.model_validate_json(
        saved.model_dump_json(include=set(GoalRevisionRef.model_fields))
    )


class CountedResolver(existing.Resolver):
    async def resolve(self, endpoint_id: str) -> ServerEndpoint:
        endpoint = replace(await super().resolve(endpoint_id), timeout_seconds=30)
        assert isinstance(endpoint.transport, httpx2.MockTransport)
        assert endpoint.api_key.get_secret_value() == KEY
        return endpoint


async def approve_and_authorize(
    journal: CompanyJournal, ns: Namespace, prepared: PreparedQualification
) -> LedgerScope:
    scope = ns.scope(prepared.request.task_id, prepared.request.trace_id)
    await journal.approve_registered(
        scope,
        prepared.request.action_id,
        prepared.action.proposal_hash,
        datetime.now(UTC),
        identity=ns.identity(),
    )
    await journal.authorize_registered(
        scope, prepared.request.action_id, datetime.now(UTC), (), identity=ns.identity()
    )
    return scope


async def known_call(
    factory: async_sessionmaker[AsyncSession],
    ns: Namespace,
    prepared: PreparedQualification,
    recipe: QualificationRecipe,
    root: Path,
) -> QualificationRunResult:
    execution, effects = ExecutionStore(factory), EffectStore(factory)
    scope = await approve_and_authorize(CompanyJournal(factory), ns, prepared)
    lease = await execution.claim(
        scope, ns.identity(), uuid5(prepared.request.action_id, "worker"), ttl_seconds=60
    )
    resolver = CountedResolver(recipe)
    store = FileQualificationEvidenceStore(root)
    client = QualificationClient(
        factory,
        effects,
        lease,
        ns.identity(),
        recipe,
        prepared.request,
        resolver,
        store,
        end_us=clock_us() + 45_000_000,
    )
    result = await client.request_once()
    assert result.provider_result.billing == "known" and result.record is not None
    assert result.record.state == "succeeded" and result.recording_error is None
    assert result.actual_usd is not None and resolver.posts == 1 and not client.pending_owners()
    replay = QualificationClient(
        factory,
        effects,
        lease,
        ns.identity(),
        recipe,
        prepared.request,
        resolver,
        store,
        end_us=clock_us() + 45_000_000,
    )
    assert (await replay.request_once()).provider_result.billing == "not_issued"
    assert resolver.posts == 1 and not replay.pending_owners()
    released = await execution.release(lease, ns.identity())
    assert released.worker_id is None and released.expires_at is None
    assert (await execution.get(scope, ns.identity())).worker_id is None
    return result


async def prepare_overbill(
    factory: async_sessionmaker[AsyncSession], ns: Namespace
) -> tuple[LedgerScope, ActionProposal]:
    """Create a separate synthetic tool Work with a real held action."""
    task, trace = uuid5(ns.company, "overbill-task"), uuid5(ns.company, "overbill-trace")
    scope = ns.scope(task, trace)
    await PersistentCompanyDirectory(factory).register_work(
        WorkRegistration(
            company_id=ns.company,
            workspace_id=ns.workspace,
            task_id=task,
            trace_id=trace,
            actor_id=ns.owner,
            allocation_usd=Decimal("1.00"),
            allowed_principals=(ns.owner,),
        ),
        ns.control("register-overbill"),
    )
    await ExecutionStore(factory).register(
        ExecutionRegistration(
            work=WorkItem(
                company_id=ns.company,
                task_id=task,
                trace_id=trace,
                goal_id=ns.goal,
                department="builder",
                title="Synthetic overbill",
                acceptance=("synthetic",),
                budget_usd=Decimal("1.00"),
            ),
            run_id=uuid5(task, "run"),
            workflow_name="fixture.workflow.v1",
            workflow_version="fixture-v1",
            model_profile="routine",
            model_registry_version="catalog-v1",
            quota=AttemptQuota(
                model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0
            ),
        ),
        scope,
        ns.identity(),
    )
    proposal = ActionProposal(
        company_id=ns.company,
        action_id=uuid5(task, "action"),
        task_id=task,
        trace_id=trace,
        actor_id=ns.owner,
        revision=1,
        tool="offline.tool",
        tool_version="v1",
        resource="fixture:synthetic",
        parameters={"operation": "synthetic"},
        policy_version="qualification-policy-v1",
        price_version="qualification-prices-v1",
        estimated_cost_usd=Decimal("0.10"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(proposal, scope)
    await journal.approve_registered(
        scope, proposal.action_id, action_hash(proposal), datetime.now(UTC), identity=ns.identity()
    )
    await journal.authorize_registered(
        scope, proposal.action_id, datetime.now(UTC), (), identity=ns.identity()
    )
    return scope, proposal


class LedgerSnapshot(NamedTuple):
    day: date
    cap: Decimal
    days: tuple[tuple[date, Decimal, Decimal], ...]
    works: tuple[tuple[UUID, Decimal, Decimal], ...]
    holds: tuple[tuple[UUID, date, str, Decimal, Decimal | None], ...]
    intents: tuple[tuple[UUID, str], ...]
    attempts: tuple[tuple[UUID, UUID, str], ...]
    counters: tuple[tuple[UUID, int, int], ...]


async def snapshot(factory: async_sessionmaker[AsyncSession], ns: Namespace) -> LedgerSnapshot:
    """Read bounded synthetic ledger facts using a restricted RR/READ ONLY transaction."""
    async with factory() as session:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        assert await session.scalar(text("SHOW transaction_read_only")) == "on"
        assert await session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        await session.execute(text("SET LOCAL statement_timeout='5s'"))
        await session.execute(text("SET LOCAL lock_timeout='1s'"))
        await session.execute(text("SET LOCAL idle_in_transaction_session_timeout='10s'"))
        await session.execute(text("SET LOCAL max_parallel_workers_per_gather=0"))
        await session.execute(select(func.set_config("nexus.company_id", str(ns.company), True)))
        now = await session.scalar(select(func.clock_timestamp()))
        control = await session.get(CompanyControl, ns.company)
        assert now is not None and control is not None
        days = (
            await session.execute(
                select(DailyBudget.day, DailyBudget.held_usd, DailyBudget.spent_usd)
                .order_by(DailyBudget.day)
                .limit(101)
            )
        ).all()
        works = (
            await session.execute(
                select(WorkBudget.task_id, WorkBudget.held_usd, WorkBudget.spent_usd)
                .order_by(WorkBudget.task_id)
                .limit(101)
            )
        ).all()
        holds = (
            await session.execute(
                select(
                    CostHold.action_id,
                    CostHold.day,
                    CostHold.state,
                    CostHold.amount_usd,
                    CostHold.actual_usd,
                )
                .order_by(CostHold.action_id)
                .limit(101)
            )
        ).all()
        intents = (
            await session.execute(
                select(EffectIntent.action_id, EffectIntent.state)
                .order_by(EffectIntent.action_id)
                .limit(101)
            )
        ).all()
        attempts = (
            await session.execute(
                select(ExecutionAttempt.task_id, ExecutionAttempt.attempt_id, ExecutionAttempt.kind)
                .order_by(ExecutionAttempt.task_id, ExecutionAttempt.attempt_id)
                .limit(101)
            )
        ).all()
        counters = (
            await session.execute(
                select(
                    ExecutionWork.task_id,
                    ExecutionWork.model_requests_used,
                    ExecutionWork.model_requests_limit,
                )
                .order_by(ExecutionWork.task_id)
                .limit(101)
            )
        ).all()
        if any(len(rows) > 100 for rows in (days, works, holds, intents, attempts, counters)):
            raise ValueError("Synthetic audit exceeded its row bound")
        value = LedgerSnapshot(
            billing_day(now),
            control.daily_cap_usd,
            cast(tuple[tuple[date, Decimal, Decimal], ...], tuple(days)),
            cast(tuple[tuple[UUID, Decimal, Decimal], ...], tuple(works)),
            cast(tuple[tuple[UUID, date, str, Decimal, Decimal | None], ...], tuple(holds)),
            cast(tuple[tuple[UUID, str], ...], tuple(intents)),
            cast(tuple[tuple[UUID, UUID, str], ...], tuple(attempts)),
            cast(tuple[tuple[UUID, int, int], ...], tuple(counters)),
        )
        await session.rollback()
        return value
