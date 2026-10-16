"""Real owner HTTP/native/DBOS qualification with SDK mocks, not live provider qualification.

The cohesive integration keeps one fresh database, authenticated owner, durable
queue, actual worker, conservation checks and retained evidence together. It
intentionally exceeds 400 lines; no reset/drop, preview access or process-restart
claim. All provider responses use the actual SDK with MockTransport/fake keys.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid5

import httpx2
import pytest
from dbos import DBOS, WorkflowHandleAsync
from litestar.testing import AsyncTestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.builder.contained_query import clock_us
from nexus.company.control_store import CompanyControls
from nexus.company.directory_models import RegisteredWork
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.company.pilot_session import PilotSessionService
from nexus.company.pilot_session_store import PilotCredential, PilotCredentialFile, save_credentials
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.core.llm.company_adapter_contracts import ServerEndpoint
from nexus.core.llm.qualification_contracts import APPLICATION, QUEUE, VERSION, WORKFLOW
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.effect_store import EffectStore
from nexus.execution.qualification_dispatch import (
    REGISTRATION,
    QualificationApiServices,
    QualificationDispatchService,
)
from nexus.execution.qualification_read_contracts import QualificationResultView
from nexus.execution.qualification_reads import QualificationReader
from nexus.execution.qualification_service import (
    PreparedQualification,
    QualificationPreparationService,
)
from nexus.execution.qualification_worker import (
    configure_qualification_worker,
    execute_qualification_segment,
    launch_qualification_worker,
)
from nexus.execution.qualification_worker_recovery import QualificationSegmentResult
from nexus.execution.qualification_worker_services import QualificationWorkerServices
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold, DailyBudget, WorkBudget
from nexus.harness.qualification_evidence import FileQualificationEvidenceStore
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import migrate
from nexus.tests.integration.test_company_model_qualification import (
    COMPANY,
    OWNER,
    SOCKET,
    WORKSPACE,
    goal,
    identity,
    recipes,
)
from nexus.tests.unit.test_company_provider_conformance import KEY, response

DATABASE = "nexus_company_test_qualification_runtime_v2"


@dataclass(frozen=True)
class RuntimeDatabase:
    """Only the fixed fresh database's app/admin factories and public DBOS URL."""

    factory: async_sessionmaker[AsyncSession]
    admin: async_sessionmaker[AsyncSession]
    system_url: str


@pytest.fixture
async def database() -> AsyncIterator[RuntimeDatabase]:
    """Install normal lineages once and retain all data on every terminal outcome."""
    if not settings.company_test_database_url:
        pytest.skip("Exact fresh qualification-runtime DB is not configured")
    url = make_url(settings.company_test_database_url)
    assert (url.drivername, url.username, url.password, url.host, url.port, url.database) == (
        "postgresql+asyncpg",
        "santapong",
        None,
        None,
        None,
        DATABASE,
    )
    assert dict(url.query) == {"host": SOCKET, "port": "55438"}
    assert settings.company_test_database_url != settings.database_url
    admin = create_async_engine(url, poolclass=NullPool)
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
            assert (
                await connection.scalar(text("SELECT version_num FROM company_alembic_version"))
                == "company_016"
            )
            assert (
                await connection.execute(
                    text(
                        "SELECT count(*),bool_and(c.relrowsecurity AND c.relforcerowsecurity) "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='public' AND c.relkind='r' AND c.relname LIKE 'company_%' "
                        "AND c.relname <> 'company_alembic_version'"
                    )
                )
            ).one() == (74, True)
        await asyncio.to_thread(
            DBOS.migrate,
            url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
            application_role="nexus_company_app",
        )
        async with app.connect() as connection:
            assert await connection.scalar(text("SELECT current_user")) == "nexus_company_app"
            assert (
                await connection.scalar(
                    text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
                )
                is False
            )
            for name in ("fsync", "synchronous_commit", "full_page_writes"):
                assert await connection.scalar(text(f"SHOW {name}")) == "on"
        yield RuntimeDatabase(
            async_sessionmaker(app, expire_on_commit=False),
            async_sessionmaker(admin, expire_on_commit=False),
            url.set(username="nexus_company_app", drivername="postgresql+psycopg").render_as_string(
                hide_password=False
            ),
        )
    finally:
        await app.dispose()
        await admin.dispose()  # Preserve every schema, row, failure and protected file.


class Credentials:
    """Supply only the token genuinely returned by the test's HTTP login."""

    def __init__(self, token: str) -> None:
        self._token = SecretStr(token)

    async def credential(self) -> SecretStr:
        return self._token


class Resolver:
    """Actual SDK transport with two fixed fake-key endpoints and bounded public replies."""

    def __init__(self) -> None:
        self.posts = {"openai": 0, "google": 0}

    async def resolve(self, endpoint_id: str) -> ServerEndpoint:
        provider = "openai" if endpoint_id == "openai.qualification.v1" else "google"
        assert endpoint_id == f"{provider}.qualification.v1"

        def wire(request: httpx2.Request) -> httpx2.Response:
            assert request.method == "POST"
            self.posts[provider] += 1
            body = response(provider)
            body["model" if provider == "openai" else "modelVersion"] = (
                "gpt-5.4-mini-2026-03-17" if provider == "openai" else "gemini-3.5-flash-lite"
            )
            if provider == "google" and self.posts[provider] == 2:
                body.pop("usageMetadata")
            return httpx2.Response(200, json=body)

        return ServerEndpoint(
            endpoint_id=endpoint_id,
            provider=provider,
            api_family="openai_responses" if provider == "openai" else "google_generate_content",
            base_url="https://api.openai.com/v1"
            if provider == "openai"
            else "https://generativelanguage.googleapis.com",
            api_key=SecretStr(KEY),
            timeout_seconds=2,
            transport=httpx2.MockTransport(wire),
        )


async def workflow_result(workflow_id: str) -> QualificationSegmentResult:
    """Read the actual persisted DBOS execution result within a finite observation bound."""
    handle: WorkflowHandleAsync[str] = await DBOS.retrieve_workflow_async(workflow_id)
    raw = await asyncio.wait_for(handle.get_result(polling_interval_sec=0.05), timeout=60)
    return QualificationSegmentResult.model_validate_json(raw)


async def exact_queue(database: RuntimeDatabase, command: SegmentCommand) -> None:
    """Verify committed fixed workflow metadata and the complete portable command bytes."""
    async with database.admin() as session:
        row = (
            await session.execute(
                text(
                    "SELECT s.name,s.queue_name,s.application_version,s.application_name,"
                    "s.serialization,i.inputs FROM dbos.workflow_status s "
                    "JOIN dbos.workflow_input i ON i.workflow_uuid=s.workflow_uuid "
                    "WHERE s.workflow_uuid=:id"
                ),
                {"id": command.workflow_id},
            )
        ).one()
        assert tuple(row[:5]) == (WORKFLOW, QUEUE, VERSION, APPLICATION, "portable_json")
        assert json.loads(row[5]) == {
            "positionalArgs": [command.model_dump_json()],
            "namedArgs": {},
        }


async def deny_missing_hook(
    database: RuntimeDatabase, ready: PreparedQualification, command: SegmentCommand
) -> None:
    """A real execute lease cannot bypass the mandatory qualification gate or consume quota."""
    scope = LedgerScope(
        company_id=COMPANY, principal_id=OWNER, task_id=command.task_id, trace_id=command.trace_id
    )
    execution = ExecutionStore(database.factory)
    lease = await execution.recover_dispatched(
        scope,
        identity(),
        uuid5(COMPANY, "negative-hook-worker"),
        command.segment_id,
        ttl_seconds=60,
    )
    before = await execution.get(scope, identity())
    try:
        with pytest.raises(ValueError):
            await EffectStore(database.factory).begin(
                lease,
                identity(),
                ready.request.action_id,
                kind="model_requests",
                before_intent=None,
            )
        assert await execution.get(scope, identity()) == before
        async with database.factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            assert await session.get(EffectIntent, (COMPANY, ready.request.action_id)) is None
            held = await session.get(CostHold, ready.request.action_id)
            assert held and held.state == "held" and held.actual_usd is None
    finally:
        await execution.release(lease, identity())


async def test_real_owner_http_queue_worker_replay_and_unknown_conservation(
    database: RuntimeDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep one complete actual owner/native/queue chain and its conservation facts together."""
    started = datetime.now(UTC)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    reference = await goal(database.factory, root)
    original = await recipes(reference)
    catalog = (
        *original,
        original[2].model_copy(
            update={
                "recipe_id": "google-after-unknown",
                "case_id": "must-not-issue",
            }
        ),
    )
    preparation = QualificationPreparationService(database.factory, catalog)
    execution = ExecutionStore(database.factory)
    evidence = FileQualificationEvidenceStore(root / "evidence")
    dispatch = QualificationDispatchService(preparation, execution)
    api = QualificationApiServices(
        preparation, dispatch, QualificationReader(preparation, evidence)
    )
    signer = secrets.token_urlsafe(48)
    monkeypatch.setattr(settings, "jwt_secret_key", signer)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    invitation, password = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    account = root / "accounts.json"
    save_credentials(
        account,
        PilotCredentialFile(
            accounts=(
                PilotCredential(
                    company_id=COMPANY,
                    workspace_id=WORKSPACE,
                    principal_id=OWNER,
                    email="qualification-runtime@example.invalid",
                    display_name="Synthetic runtime owner",
                    signup_sha256=hashlib.sha256(invitation.encode()).hexdigest(),
                    signup_expires_at=datetime.now(UTC) + timedelta(minutes=10),
                ),
            )
        ),
    )
    directory = PersistentCompanyDirectory(database.factory)
    app = create_company_app(
        CompanyServices(
            directory, CompanyJournal(database.factory), CompanyControls(database.factory)
        ),
        pilot_sessions=PilotSessionService(directory, account),
        qualification_services=api,
    )
    base = f"/api/v2/companies/{COMPANY}"
    endpoint = base + "/model-qualification"
    resolver = Resolver()
    worker: QualificationWorkerServices | None = None
    commands: list[SegmentCommand] = []
    outcomes: list[QualificationSegmentResult] = []
    actual_reads: list[QualificationResultView] = []
    try:
        async with AsyncTestClient(app, raise_server_exceptions=True) as client:
            assert (await client.get(endpoint + "/recipes")).status_code == 401
            signup = await client.post(
                "/api/v2/company-session/signup",
                json={
                    "email": "qualification-runtime@example.invalid",
                    "password": password,
                    "invitation": invitation,
                },
            )
            assert signup.status_code == 201
            login = await client.post(
                "/api/v2/company-session/login",
                json={"email": "qualification-runtime@example.invalid", "password": password},
            )
            assert login.status_code == 200
            token = login.json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            authenticated = NotificationWorkerIdentities(
                Credentials(token), SecretStr(signer), enabled=True
            )
            witness = await authenticated.current()
            assert witness.identity == identity()
            worker = QualificationWorkerServices(
                database.factory,
                execution,
                EffectStore(database.factory),
                preparation,
                authenticated,
                resolver,
                evidence,
                uuid5(COMPANY, "runtime-worker-v1"),
                REGISTRATION,
            )
            listing = await client.get(endpoint + "/recipes", headers=headers)
            assert listing.status_code == 200 and len(listing.json()) == 4
            for index, recipe in enumerate(catalog[:3]):
                prepared_response = await client.post(
                    endpoint + "/prepare", headers=headers, json={"recipe_id": recipe.recipe_id}
                )
                assert prepared_response.status_code == 200
                ready = PreparedQualification.model_validate_json(prepared_response.content)
                if commands:
                    assert ready.request.task_id == commands[0].task_id
                    assert ready.work.registration.run_id == commands[0].run_id
                decision = await client.post(
                    base
                    + f"/work/{ready.request.task_id}/actions/{ready.request.action_id}/decision",
                    headers=headers,
                    json={
                        "trace_id": str(ready.request.trace_id),
                        "expected_hash": ready.action.proposal_hash,
                        "approved": True,
                    },
                )
                assert decision.status_code == 200 and resolver.posts == {
                    "openai": 1 if index else 0,
                    "google": max(0, index - 1),
                }
                sent = await client.post(
                    endpoint + f"/actions/{ready.request.action_id}/dispatch",
                    headers=headers,
                    json={"expected_hash": ready.action.proposal_hash},
                )
                assert sent.status_code == 200
                command = SegmentCommand.model_validate(sent.json()["command"])
                commands.append(command)
                await exact_queue(database, command)
                repeated = await client.post(
                    endpoint + f"/actions/{ready.request.action_id}/dispatch",
                    headers=headers,
                    json={"expected_hash": ready.action.proposal_hash},
                )
                assert (
                    repeated.status_code == 200
                    and repeated.json()["command"] == sent.json()["command"]
                )
                if index == 0:
                    await deny_missing_hook(database, ready, command)
                    configure_qualification_worker(worker, database.system_url)
                    await launch_qualification_worker()
                result = await workflow_result(command.workflow_id)
                outcomes.append(result)
                assert result.status == ("outcome_unknown" if index == 2 else "observed")
                assert (
                    result.lease_released
                    and not result.resources_pending
                    and not worker.pending_owners()
                )
                fetched = await client.get(
                    endpoint + f"/actions/{ready.request.action_id}/result", headers=headers
                )
                assert fetched.status_code == 200
                public = QualificationResultView.model_validate_json(fetched.content)
                actual_reads.append(public)
                assert public.availability == "available" and public.provider_result is not None
                assert public.native_outcome == ("outcome_unknown" if index == 2 else "succeeded")
                assert str(root) not in fetched.text and KEY not in fetched.text
                assert not public.company_completed and not public.profile_quality_evaluated
                if index == 1:
                    scope = LedgerScope(
                        company_id=COMPANY,
                        principal_id=OWNER,
                        task_id=command.task_id,
                        trace_id=command.trace_id,
                    )
                    before = await execution.get(scope, identity())
                    replay = await execute_qualification_segment(
                        worker, commands[0], workflow_id=commands[0].workflow_id
                    )
                    assert (
                        replay.status == "observed"
                        and replay.replayed
                        and not replay.lease_released
                    )
                    assert await execution.get(scope, identity()) == before and resolver.posts == {
                        "openai": 1,
                        "google": 1,
                    }
                    assert await workflow_result(commands[0].workflow_id) == outcomes[0]
            assert resolver.posts == {"openai": 1, "google": 2}
            # Actual native reconciliation re-enters the issued unknown segment;
            # it reads protected bytes and preserves the hold, never another POST.
            unresolved = await execute_qualification_segment(
                worker,
                commands[2],
                workflow_id=commands[2].workflow_id,
            )
            assert unresolved.status == "outcome_unknown" and unresolved.replayed
            assert unresolved.lease_released and not unresolved.resources_pending
            assert resolver.posts == {"openai": 1, "google": 2}
            stopped = await client.post(
                endpoint + "/prepare", headers=headers, json={"recipe_id": catalog[3].recipe_id}
            )
            assert stopped.status_code == 200
            fourth = PreparedQualification.model_validate_json(stopped.content)
            approved = await client.post(
                base
                + f"/work/{fourth.request.task_id}/actions/{fourth.request.action_id}/decision",
                headers=headers,
                json={
                    "trace_id": str(fourth.request.trace_id),
                    "expected_hash": fourth.action.proposal_hash,
                    "approved": True,
                },
            )
            assert approved.status_code == 200
            denied = await client.post(
                endpoint + f"/actions/{fourth.request.action_id}/dispatch",
                headers=headers,
                json={"expected_hash": fourth.action.proposal_hash},
            )
            assert denied.status_code == 403 and resolver.posts == {"openai": 1, "google": 2}
            assert not dispatch.pending_owners() and not worker.pending_owners()
            async with database.factory() as session, session.begin():
                await session.execute(
                    select(func.set_config("nexus.company_id", str(COMPANY), True))
                )
                work = await session.get(ExecutionWork, (COMPANY, commands[0].task_id))
                holds = (await session.scalars(select(CostHold))).all()
                assert work and work.model_requests_used == 3 and work.tool_attempts_used == 0
                assert (
                    work.worker_id is None
                    and work.lease_until is None
                    and work.state == "outcome_unknown"
                )
                assert work.model_requests_limit == 12
                assert len(holds) == 3 and sorted(h.state for h in holds) == [
                    "reconciled",
                    "reconciled",
                    "unknown",
                ]
                unknown = next(h for h in holds if h.state == "unknown")
                assert unknown.actual_usd is None and unknown.amount_usd == Decimal("0.478413")
                budget = await session.get(WorkBudget, (COMPANY, commands[0].task_id))
                day = await session.scalar(select(DailyBudget))
                assert budget and day and budget.held_usd == day.held_usd == unknown.amount_usd
                assert (
                    budget.spent_usd
                    == day.spent_usd
                    == sum((r.actual_usd or Decimal(0)) for r in actual_reads)
                )
                assert await session.scalar(select(func.count()).select_from(RegisteredWork)) == 1
                assert await session.scalar(select(func.count()).select_from(ExecutionWork)) == 1
                assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 3
    finally:
        first = sys.exc_info()[0]
        # Preserve the actual returned prefix before any potentially failing cleanup.
        raw = (
            json.dumps(
                {
                    "database": DATABASE,
                    "started_utc": started.isoformat(),
                    "finished_utc": datetime.now(UTC).isoformat(),
                    "commands": [c.model_dump(mode="json") for c in commands],
                    "outcomes": [r.model_dump(mode="json") for r in outcomes],
                    "mock_posts": resolver.posts,
                    "first_error_type": first.__name__ if first else None,
                    "limitations": [
                        "SDK MockTransport only",
                        "in-process DBOS, no restart proof",
                        "no model activation or quality",
                    ],
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
        fd = os.open(root / "runtime-evidence.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as report:
            report.write(raw)
        # Never destroy a loop/engine while the actual SDK/FS/native owners remain live.
        if worker is not None:
            while worker.pending_owners() and any(
                clock_us() < op.end for op in worker._operations.values()
            ):
                await asyncio.sleep(0.05)
            assert not worker.pending_owners(), (
                "Actual pending owners retained; runtime not disposed"
            )
            await asyncio.to_thread(DBOS.destroy, workflow_completion_timeout_sec=1)
