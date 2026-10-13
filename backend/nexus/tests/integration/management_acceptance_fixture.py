"""Public plan/effect/ingestion/publisher fixture; no native direct SQL acceptance inserts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import CitationHandle, RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_evidence import ProtectedReportEvidenceResolver
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_store import WorkAcceptanceStore
from nexus.company.management.acceptance_support import acceptance_scope, resolve_target
from nexus.company.management.check_contracts import (
    SemanticClaim,
    SourceQuoteClaim,
    StructuredInternalReport,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.company.management.report_checker import check_internal_report
from nexus.company.management.report_rules import project_report
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import db_now, runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope
from nexus.settings import settings
from nexus.tests.integration.management_acceptance_inputs_fixture import (
    FixtureActualInputLoader,
    input_source,
)
from nexus.tests.integration.management_acceptance_report_fixture import (
    bindings,
    declared_candidate,
    report_facts,
)
from nexus.tests.integration.management_acceptance_source_fixture import Policies, protected_text
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import authorized_action, configured_plan


def ledger(binding: RunBinding) -> LedgerScope:
    return LedgerScope(
        company_id=binding.company_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        principal_id=binding.actor_id,
    )


@pytest.fixture
async def acceptance_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_acceptance"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    migrated = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        migrated = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if migrated:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@dataclass(frozen=True)
class AcceptanceScenario:
    store: WorkAcceptanceStore
    plans: ManagementPlanStore
    payload: PlanPayload
    execution: ExecutionStore
    author_lease: ExecutionLease
    verifier_lease: ExecutionLease
    inputs: FixtureActualInputLoader
    reader: PersistentBrainRetriever
    artifacts: BoundedArtifactReader
    protected_result: ArtifactRevisionRef
    action_id: UUID
    policies: Policies
    freshness: RegisteredSourceFreshness


async def configured_acceptance(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    actual_usd: Decimal | None = Decimal("0.025000"),
    result_ttl: int | None = 300,
    with_dependent: bool = False,
    semantic_claim: str | None = None,
) -> AcceptanceScenario:
    # This public fixture keeps its exact protocol/receipt/byte identities together beyond 50 lines.
    plans, payload = await configured_plan(factory, root)
    if with_dependent:
        payload = add_ordinary_dependency(payload)
    proposal = await plans.propose(
        control(), identity(OWNER), payload, expected_current_revision_id=None
    )
    await plans.approve_and_register(
        control(),
        identity(OWNER),
        proposal.plan_revision_id,
        proposal.sha256,
        expected_current_revision_id=proposal.plan_revision_id,
    )
    _, author, verifier = bindings(payload)
    blobs = ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    artifacts = BoundedArtifactReader(factory, blobs)
    reader = PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits())
    policies = Policies()
    freshness = RegisteredSourceFreshness(factory, policies)
    execution = ExecutionStore(
        factory,
        management_catalog=plans.catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    effects = EffectStore(
        factory,
        management_catalog=plans.catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    action = await authorized_action(factory, author)
    author_lease = await execution.claim(ledger(author), identity(author.actor_id), uuid4())
    await effects.begin(author_lease, identity(author.actor_id), action.action_id)
    source, handles, observed = await input_source(factory, reader)
    receipt = ActionReceipt(
        company_id=COMPANY,
        receipt_id=uuid4(),
        action_id=action.action_id,
        task_id=author.task_id,
        trace_id=author.trace_id,
        proposal_hash=action_hash(action),
        outcome="succeeded",
        recorded_at=observed,
    )
    text = await authored_report(
        factory, reader, source, handles, observed, payload, receipt, semantic_claim
    )
    output = await protected_text(factory, blobs, policies, text, 200)
    receipt = receipt.model_copy(
        update={
            "artifacts": (
                ArtifactRef(
                    company_id=COMPANY,
                    artifact_id=output.artifact_id,
                    reference="protected:report",
                    sha256=output.sha256,
                    revision=output.revision,
                ),
            )
        }
    )
    await effects.record_receipt(
        author_lease, identity(author.actor_id), receipt, actual_usd=actual_usd
    )
    verifier_lease = await execution.claim(ledger(verifier), identity(verifier.actor_id), uuid4())
    inputs = FixtureActualInputLoader(factory, reader, source, handles, observed, payload)
    scope = acceptance_scope(verifier_lease, action.action_id)
    async with runtime_transaction(factory, ledger(verifier), identity(verifier.actor_id)) as (
        session,
        current,
        _,
    ):
        target = await resolve_target(
            session, current, verifier_lease, action.action_id, await db_now(session)
        )
    command = await inputs.load(scope, identity(verifier.actor_id), target)
    result = check_internal_report(command)
    protected = await protected_text(
        factory, blobs, policies, result.model_dump_json(), 300, result_ttl
    )
    resolver = ProtectedReportEvidenceResolver(reader, inputs, freshness)
    return AcceptanceScenario(
        WorkAcceptanceStore(factory, resolver),
        plans,
        payload,
        execution,
        author_lease,
        verifier_lease,
        inputs,
        reader,
        artifacts,
        protected,
        action.action_id,
        policies,
        freshness,
    )


async def authored_report(
    factory: async_sessionmaker[AsyncSession],
    reader: PersistentBrainRetriever,
    source: ArtifactSlice,
    handles: tuple[CitationHandle, ...],
    observed: datetime,
    payload: PlanPayload,
    receipt: ActionReceipt,
    semantic_claim: str | None,
) -> str:
    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, current, _):
        facts = await report_facts(
            session, current, owner_scope(), identity(OWNER), source, observed, payload
        )
    operating = project_report(declared_candidate(facts, receipt, payload))
    evidence = handles[0].record
    quote = SourceQuoteClaim(
        kind="source_quote",
        evidence_id=evidence.evidence_id,
        source_revision_id=evidence.source.source_revision_id,
        artifact_revision_id=evidence.artifact.artifact_revision_id,
        span_sha256=evidence.span_sha256,
        quote=source.text,
        source_event=evidence.source_event,
        source_state="current",
        freshness="fresh",
    )
    return StructuredInternalReport(
        schema_version="nexus.company.internal-report.v1",
        company_id=COMPANY,
        operating=operating,
        claims=(quote,)
        if semantic_claim is None
        else (quote, SemanticClaim(kind="semantic", text=semantic_claim)),
    ).model_dump_json()


async def issue_accepted_report_fixture(
    factory: async_sessionmaker[AsyncSession], root: Path, *, with_dependent: bool = False
) -> tuple[AcceptanceScenario, WorkAcceptance]:
    scenario = await configured_acceptance(factory, root, with_dependent=with_dependent)
    verifier = scenario.payload.children[1].binding
    record = await scenario.store.publish_verified_result(
        scenario.verifier_lease,
        identity(verifier.actor_id),
        action_id=scenario.action_id,
        protected_result=scenario.protected_result,
    )
    assert record.verdict == "pass"
    return scenario, record


def add_ordinary_dependency(payload: PlanPayload) -> PlanPayload:
    author = payload.children[0]
    binding = author.binding.model_copy(
        update={"task_id": uuid4(), "trace_id": uuid4(), "run_id": uuid4()}
    )
    allocation = author.model_copy(update={"binding": binding})
    item = payload.plan.items[0].model_copy(
        update={
            "task_id": binding.task_id,
            "trace_id": binding.trace_id,
            "title": "Ordinary accepted dependency conformance",
            "depends_on": (author.binding.task_id,),
        }
    )
    return PlanPayload.model_validate_json(
        payload.model_copy(
            update={
                "children": (*payload.children, allocation),
                "plan": payload.plan.model_copy(update={"items": (*payload.plan.items, item)}),
            }
        ).model_dump_json(by_alias=True)
    )
