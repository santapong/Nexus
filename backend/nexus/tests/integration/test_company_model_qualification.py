"""Restricted real PostgreSQL + actual SDK MockTransport; never live model qualification.

Run only against the explicitly prepared fresh named DB. Retain schema/data/files
after success or failure; this fixture never downgrades, resets, or drops a DB.
The complete one-goal preparation/issuance/settlement/conservation flow is kept
together for review, intentionally exceeding the ordinary 400-line guideline.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.base import SourceTime
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.contracts.company import CompanyMandate
from nexus.company.directory_contracts import CompanyRegistration
from nexus.company.directory_models import RegisteredWork
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import (
    DueIntent,
    GoalDefinition,
    GoalMetric,
    GoalRevisionRef,
    UnknownBaseline,
)
from nexus.core.llm.company_adapter_contracts import JsonSchemaDocument, ServerEndpoint
from nexus.core.llm.company_pricing import PriceCard
from nexus.core.llm.company_registry import ModelHealth, ModelRegistration
from nexus.core.llm.qualification_contracts import QualificationRecipe, capture_sdk_pins
from nexus.execution.effect_store import EffectStore
from nexus.execution.qualification_service import (
    PreparedQualification,
    QualificationPreparationService,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import CompanyPolicy, LedgerScope
from nexus.harness.journal_models import CostHold, DailyBudget, WorkBudget
from nexus.harness.qualification_client import QualificationClient, QualificationRunResult
from nexus.harness.qualification_evidence import FileQualificationEvidenceStore
from nexus.tests.integration.test_company_directory import migrate
from nexus.tests.unit.test_company_provider_conformance import KEY, response

DATABASE = "nexus_company_test_model_qualification_v1"
SOCKET = "/tmp/nexus-release-tests-2026-10-13/socket"
COMPANY = uuid5(NAMESPACE_URL, "nexus:model-qualification:postgres-v1")
OWNER, WORKSPACE, GOAL = (uuid5(COMPANY, name) for name in ("owner", "workspace", "goal"))


def control(label: str) -> CompanyControlScope:
    return CompanyControlScope(
        company_id=COMPANY,
        principal_id=OWNER,
        operation_id=uuid5(COMPANY, label),
        trace_id=uuid5(COMPANY, "owner-audit"),
    )


def identity() -> VerifiedIdentity:
    return VerifiedIdentity(principal_id=OWNER, workspace_id=WORKSPACE)


@pytest.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    configured = os.environ.get("COMPANY_TEST_DATABASE_URL")
    if configured is None:
        pytest.skip("Explicit fresh qualification database is not configured")
    url = make_url(configured)
    assert (url.drivername, url.username, url.password, url.host, url.port, url.database) == (
        "postgresql+asyncpg",
        "santapong",
        None,
        None,
        None,
        DATABASE,
    )
    assert dict(url.query) == {"host": SOCKET, "port": "55438"}
    admin = create_async_engine(url, poolclass=NullPool)
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
            assert (
                await connection.scalar(text("SELECT version_num FROM company_alembic_version"))
                == "company_016"
            )
            schema = (
                await connection.execute(
                    text(
                        "SELECT count(*),bool_and(c.relrowsecurity AND c.relforcerowsecurity) "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='public' AND c.relkind='r' AND c.relname LIKE 'company_%' "
                        "AND c.relname <> 'company_alembic_version'"
                    )
                )
            ).one()
            assert tuple(schema) == (74, True)
        async with app.connect() as connection:
            assert await connection.scalar(text("SELECT current_user")) == "nexus_company_app"
            assert not await connection.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
            assert await connection.scalar(text("SHOW fsync")) == "on"
            assert await connection.scalar(text("SHOW synchronous_commit")) == "on"
            assert await connection.scalar(text("SHOW full_page_writes")) == "on"
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        await admin.dispose()  # Intentionally preserve this DB and every row.


async def goal(factory: async_sessionmaker[AsyncSession], root: Path) -> GoalRevisionRef:
    journal = CompanyJournal(factory)
    await journal.create_company(
        CompanyPolicy(
            company_id=COMPANY,
            owner_id=OWNER,
            policy_version="qualification-policy-v1",
            price_version="qualification-prices-v1",
        ),
        LedgerScope(
            company_id=COMPANY,
            principal_id=OWNER,
            task_id=control("bootstrap").operation_id,
            trace_id=control("bootstrap").trace_id,
        ),
    )
    await PersistentCompanyDirectory(factory).bootstrap(
        CompanyRegistration(company_id=COMPANY, workspace_id=WORKSPACE, owner_id=OWNER),
        control("bootstrap"),
    )
    mandate = await ManagementControlStore(factory).publish_mandate(
        control("mandate"),
        identity(),
        CompanyMandate(
            company_id=COMPANY,
            owner_id=OWNER,
            version="v1",
            purpose="Public SDK qualification only; no company delivery claim",
            goals=(GOAL,),
        ),
        expected_revision_id=None,
    )
    reference = RevisionRef.model_validate_json(
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
        control("goal"),
        identity(),
        GoalDefinition(
            company_id=COMPANY,
            goal_id=GOAL,
            owner_id=OWNER,
            title="Observe public SDK conformance without declaring model quality",
            mandate=reference,
            metrics=(
                GoalMetric(
                    company_id=COMPANY,
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


async def recipes(reference: GoalRevisionRef) -> tuple[QualificationRecipe, ...]:
    now, pins = datetime.now(UTC), await capture_sdk_pins()
    targets = []
    for provider, api, model, cap, output, input_rate, output_rate in (
        ("openai", "openai_responses", "gpt-5.4-mini-2026-03-17", 400_000, 128_000, "0.75", "4.5"),
        (
            "google",
            "google_generate_content",
            "gemini-3.5-flash-lite",
            1_048_576,
            65_536,
            "0.3",
            "2.5",
        ),
    ):
        targets.append(
            ModelRegistration(
                registry_id=f"{provider}-qualification",
                provider=provider,
                api_family=api,
                model_id=model,
                endpoint_id=f"{provider}.qualification.v1",
                enabled=False,
                capabilities=frozenset({"text", "structured_output"}),
                allowed_data=frozenset({"public"}),
                context_window=cap,
                max_output_tokens=output,
                health=ModelHealth(
                    status="unknown", checked_at=now, expires_at=now + timedelta(hours=1)
                ),
                evaluations=(),
                price=PriceCard(
                    version="qualification-prices-v1",
                    as_of=now.date(),
                    valid_from=now - timedelta(minutes=1),
                    valid_until=now + timedelta(minutes=30),
                    source_reference="reviewed:official-standard-text-prices-2026-10-16",
                    input_per_million=Decimal(input_rate),
                    output_per_million=Decimal(output_rate),
                    reasoning_semantics="included_in_output",
                ),
            )
        )
    hashes = tuple(sorted(canonical_sha256(target) for target in targets))
    prompt = 'Return exactly {"result":"ready"}.'
    values = tuple(
        QualificationRecipe(
            goal=reference,
            recipe_id=f"{row.provider}-known",
            revision="v1",
            case_id="native-json-known",
            target=row,
            registry_revision="qualification-targets-v1",
            qualification_target_sha256s=hashes,
            input_text=prompt,
            output_schema=JsonSchemaDocument(
                schema_json='{"type":"object","properties":{"result":{"type":"string"}},"required":["result"],"additionalProperties":false}'
            ),
            request_output_cap=64,
            financial_input_ceiling=row.context_window,
            financial_output_ceiling=row.max_output_tokens,
            source_reference="qualification:public-controlled-prompt-v1",
            source_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
            valid_until=now + timedelta(minutes=20),
            sdk_pins=pins,
        )
        for row in targets
    )
    return (
        *values,
        values[1].model_copy(update={"recipe_id": "google-unknown", "case_id": "missing-usage"}),
    )


class Resolver:
    """Fake key plus actual SDK MockTransport only; no settings/credential lookup or network."""

    def __init__(self, recipe: QualificationRecipe, *, unknown: bool = False) -> None:
        self.recipe, self.unknown, self.posts = recipe, unknown, 0

    def wire(self, request: httpx2.Request) -> httpx2.Response:
        assert request.method == "POST"
        self.posts += 1
        provider = self.recipe.target.provider
        body = response(provider)
        body["model" if provider == "openai" else "modelVersion"] = self.recipe.target.model_id
        if self.unknown:
            body.pop("usageMetadata")
        return httpx2.Response(200, json=body)

    async def resolve(self, endpoint_id: str) -> ServerEndpoint:
        row = self.recipe.target
        assert endpoint_id == row.endpoint_id
        return ServerEndpoint(
            endpoint_id=endpoint_id,
            provider=row.provider,
            api_family=row.api_family,
            base_url="https://api.openai.com/v1"
            if row.provider == "openai"
            else "https://generativelanguage.googleapis.com",
            api_key=SecretStr(KEY),
            timeout_seconds=2,
            transport=httpx2.MockTransport(self.wire),
        )


async def run_case(
    factory: async_sessionmaker[AsyncSession],
    prepared: PreparedQualification,
    recipe: QualificationRecipe,
    root: Path,
    *,
    unknown: bool,
) -> QualificationRunResult:
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=OWNER,
        task_id=prepared.request.task_id,
        trace_id=prepared.request.trace_id,
    )
    journal, execution, effects = (
        CompanyJournal(factory),
        ExecutionStore(factory),
        EffectStore(factory),
    )
    await journal.approve_registered(
        scope,
        prepared.request.action_id,
        prepared.action.proposal_hash,
        datetime.now(UTC),
        identity=identity(),
    )
    await journal.authorize_registered(
        scope, prepared.request.action_id, datetime.now(UTC), (), identity=identity()
    )
    lease = await execution.claim(
        scope, identity(), uuid5(prepared.request.action_id, "worker"), ttl_seconds=60
    )
    end = clock_us() + 45_000_000
    if recipe.target.provider == "openai":
        before = await execution.get(scope, identity())
        async with factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            held = await session.get(CostHold, prepared.request.action_id)
            assert held is not None
            prior_hold = (held.state, held.amount_usd, held.actual_usd, held.day)
        with pytest.raises(ValueError):
            await effects.begin(
                lease,
                identity(),
                prepared.request.action_id,
                kind="model_requests",
                before_intent=None,
            )
        assert await execution.get(scope, identity()) == before
        async with factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            held = await session.get(CostHold, prepared.request.action_id)
            assert held is not None
            assert (held.state, held.amount_usd, held.actual_usd, held.day) == prior_hold
            assert await session.get(EffectIntent, (COMPANY, prepared.request.action_id)) is None
    store, resolver = FileQualificationEvidenceStore(root), Resolver(recipe, unknown=unknown)
    client = QualificationClient(
        factory, effects, lease, identity(), recipe, prepared.request, resolver, store, end_us=end
    )
    result = await client.request_once()
    assert not client.pending_owners()
    assert result.recording_error is None and result.evidence and result.record
    assert result.stop_required and not result.profile_quality_evaluated
    assert result.provider_result.billing == ("unknown" if unknown else "known")
    assert result.record.state == ("outcome_unknown" if unknown else "succeeded")
    evidence = await store.load(result.evidence, end_us=end)
    assert evidence.request == prepared.request and evidence.recipe == recipe
    assert (
        result.evidence.sha256
        == hashlib.sha256(Path(result.evidence.reference).read_bytes()).hexdigest()
    )
    assert KEY not in Path(result.evidence.reference).read_text()
    assert Path(result.evidence.reference).stat().st_mode & 0o777 == 0o400
    assert await effects.get(lease, identity(), prepared.request.action_id) == result.record
    replay = QualificationClient(
        factory, effects, lease, identity(), recipe, prepared.request, resolver, store, end_us=end
    )
    denied = await replay.request_once()
    assert denied.provider_result.billing == "not_issued" and resolver.posts == 1
    assert not replay.pending_owners()
    released = await execution.release(lease, identity())
    assert released.worker_id is None and released.expires_at is None
    return result


async def test_two_provider_settlement_and_unknown_share_actual_permanent_allowance(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    started = datetime.now(UTC)
    reference = await goal(factory, tmp_path)
    catalog = await recipes(reference)
    service = QualificationPreparationService(factory, catalog)
    prepared = tuple(
        [
            await service.prepare_qualification(control("prepare"), identity(), r.recipe_id)
            for r in catalog
        ]
    )
    assert len({value.request.task_id for value in prepared}) == 1
    assert len({value.work.registration.run_id for value in prepared}) == 1
    assert all(not value.company_completed for value in prepared)
    evidence_root = tmp_path / "qualification-evidence"
    evidence_root.mkdir(mode=0o700)
    observed = []
    for index, (ready, recipe) in enumerate(zip(prepared, catalog, strict=True)):
        observed.append(await run_case(factory, ready, recipe, evidence_root, unknown=index == 2))
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        work = await session.get(ExecutionWork, (COMPANY, prepared[0].request.task_id))
        assert work and work.model_requests_used == 3 and work.tool_attempts_used == 0
        assert work.model_requests_limit == 12 and work.fence == 6 and work.lease_until is None
        assert work.state == "outcome_unknown"
        effects = (await session.scalars(select(EffectIntent))).all()
        holds = (await session.scalars(select(CostHold))).all()
        attempts = (await session.scalars(select(ExecutionAttempt))).all()
        assert len(effects) == len(holds) == len(attempts) == 3
        assert sorted(row.state for row in effects) == ["outcome_unknown", "succeeded", "succeeded"]
        assert sorted(row.state for row in holds) == ["reconciled", "reconciled", "unknown"]
        unresolved = next(row for row in holds if row.state == "unknown")
        assert (
            unresolved.actual_usd is None and unresolved.amount_usd == prepared[2].quote.amount_usd
        )
        budget = await session.get(WorkBudget, (COMPANY, work.task_id))
        day = await session.scalar(select(DailyBudget))
        assert budget and day and budget.held_usd == day.held_usd == unresolved.amount_usd
        assert (
            budget.spent_usd
            == day.spent_usd
            == sum(result.actual_usd or Decimal(0) for result in observed)
        )
        assert await session.scalar(select(func.count()).select_from(RegisteredWork)) == 1
        assert await session.scalar(select(func.count()).select_from(ExecutionWork)) == 1
        original = await session.get(RegisteredWork, (COMPANY, work.task_id))
        assert original and original.allocation_usd == Decimal(1) and original.delegated_usd == 0
    report = {
        "status": "restricted-PG and actual SDK mock PASS; no live quality/HTTP auth claim",
        "database": DATABASE,
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(UTC).isoformat(),
        "task_id": str(prepared[0].request.task_id),
        "work_allocation": "1.000000",
        "quota": 12,
        "attempts": 3,
        "mock_posts": 3,
        "effects": [r.record.state for r in observed if r.record],
        "known_actual_usd": [str(r.actual_usd) for r in observed],
        "unknown_hold": str(prepared[2].quote.amount_usd),
        "evidence": [r.evidence.model_dump(mode="json") for r in observed if r.evidence],
        "targets_unqualified": all(
            not r.target.enabled
            and r.target.health.status == "unknown"
            and not r.target.evaluations
            for r in catalog
        ),
    }
    path = tmp_path / "qualification-result.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    path.chmod(0o600)
