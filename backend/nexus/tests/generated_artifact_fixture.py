"""Public owner targets/governance/plan/report plus actual issued actor intent; no pass SQL."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.contracts.actions import ActionProposal
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactPayload,
    GeneratedArtifactRule,
    GeneratedArtifactValidator,
    GeneratedTool,
)
from nexus.company.management.generated_artifact_store import GeneratedArtifactPublisher
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.company.management.native_report_validator import (
    NativeReportValidator as ProductionValidator,
)
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import NamedPlanResource
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.company.management.report_artifact_reader import ReportArtifactReader
from nexus.company.management.report_inputs import PersistentReportInputLoader
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.generated_artifact_validator import NativeReportValidator, rendered_payload
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.integration.operating_report_fixture_sources import current_input_source
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_control_support import charter
from nexus.tests.management_plan_support import VERIFIER, configured_plan


@dataclass(frozen=True)
class GeneratedScenario:
    publisher: GeneratedArtifactPublisher
    prepared: GeneratedArtifactPayload
    rules: tuple[GeneratedArtifactRule, ...]
    plans: ManagementPlanStore
    payload: PlanPayload
    action: ActionProposal
    lease: ExecutionLease
    execution: ExecutionStore
    effects: EffectStore
    blobs: ProtectedBlobStore
    artifacts: BoundedArtifactReader
    validator: GeneratedArtifactValidator
    producer: NativeReportProducer


def ledger(bound: RunBinding) -> LedgerScope:
    return LedgerScope(
        company_id=bound.company_id,
        principal_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )


async def admitted_generated_plan(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    extra_reader: bool = False,
    production: bool = False,
) -> tuple[ManagementPlanStore, PlanPayload, tuple[GeneratedArtifactRule, ...], Policies]:
    plans, payload = await configured_plan(factory, root)
    readers: tuple[UUID, ...] = (OWNER, ACTOR, VERIFIER)
    if extra_reader:
        principal = uuid4()
        await PersistentCompanyDirectory(factory).set_membership(
            MembershipChange(company_id=COMPANY, principal_id=principal, role="viewer"), control()
        )
        readers = (*readers, principal)
    definitions: tuple[tuple[GeneratedTool, str, str, str], ...] = (
        (
            "company.report.write.v1",
            "company.report.output",
            "generated.report.v1",
            "native-report-render-v1" if production else "native-internal-report-v1",
        ),
        (
            "company.report.check.v1",
            "company.check.output",
            "generated.check.v1",
            "internal-report-mechanical-v1",
        ),
    )
    rules = tuple(
        GeneratedArtifactRule(
            company_id=COMPANY,
            tool=tool,
            resource_symbol=symbol,
            target=ResourceRef(company_id=COMPANY, resource_id=uuid4()),
            source_policy=policy,
            recipe_version=recipe,
        )
        for tool, symbol, policy, recipe in definitions
    )
    for rule in rules:
        await ArtifactTargetStore(factory).provision(
            owner_scope(), identity(OWNER), rule.target, readers=readers
        )
    catalog = plans.catalog.model_copy(
        update={
            "tools": (
                *plans.catalog.tools,
                *(
                    ToolPermission(tool=row.tool, tool_version="v1", resource=row.resource_symbol)
                    for row in rules
                ),
            ),
            "resources": (
                *plans.catalog.resources,
                *(
                    NamedPlanResource(symbol=row.resource_symbol, resource=row.target)
                    for row in rules
                ),
            ),
        }
    )
    data = charter("native-v2", verifier=VERIFIER).model_copy(
        update={
            "allowed_tools": tuple(row.tool for row in catalog.tools),
            "resource_scopes": tuple(row.symbol for row in catalog.resources),
        }
    )
    registered = await ManagementControlStore(factory).publish_charter(
        control(),
        identity(OWNER),
        data,
        mandate=payload.mandate,
        expected_revision_id=payload.charters[0].revision_id,
    )
    current = CharterRevisionRef.model_validate_json(
        registered.model_dump_json(include=set(CharterRevisionRef.model_fields))
    )
    payload = PlanPayload.model_validate_json(
        payload.model_copy(
            update={
                "charters": (current,),
                "children": tuple(
                    child.model_copy(update={"charter": current}) for child in payload.children
                ),
            }
        ).model_dump_json(by_alias=True)
    )
    policies = Policies()
    for rule in rules:
        policies.values[rule.source_policy] = SourcePolicy(
            source_symbol=rule.source_policy,
            authority_profile="native.generated.v1",
            data_classification="internal",
            origin_kind="derived",
            media_type="application/json",
            parser_version="native-json-v1",
            chunker_version="utf8-sections-v1",
            search_config="simple",
            freshness_seconds=None,
            max_bytes=262144,
        )
    freshness = RegisteredSourceFreshness(factory, policies)
    plans = ManagementPlanStore(factory, catalog, source_freshness=freshness)
    proposed = await plans.propose(
        control(), identity(OWNER), payload, expected_current_revision_id=None
    )
    await plans.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    return plans, payload, rules, policies


async def generated_scenario(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    ttl_seconds: int = 60,
    extra_reader: bool = False,
    production: bool = False,
    source_grant_seconds: int | None = None,
) -> GeneratedScenario:
    plans, payload, rules, policies = await admitted_generated_plan(
        factory, root, extra_reader=extra_reader, production=production
    )
    blobs = ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    artifacts = BoundedArtifactReader(factory, blobs)
    retriever = PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits())
    freshness = RegisteredSourceFreshness(factory, policies)
    reports = OperatingReportStore(factory, plans.catalog, artifacts, freshness)
    if source_grant_seconds is not None:
        await ResourceAccessStore(factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=ACTOR,
                active=True,
                expected_generation=2,
                expires_at=datetime.now(UTC) + timedelta(seconds=source_grant_seconds),
            ),
        )
    observed = datetime.now(UTC)
    async with factory() as session, session.begin():
        from sqlalchemy import func, select

        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        binding = await plans.current_binding(session, COMPANY, payload.children[0].binding.task_id)
        assert binding is not None
    saved = await reports.save_snapshot(
        control(),
        identity(OWNER),
        binding.plan.plan_revision_id,
        payload.children[0].binding.task_id,
        (),
        period_start=observed - timedelta(days=1),
        period_end=observed,
    )
    loader = PersistentReportInputLoader(
        factory, ReportArtifactReader(retriever, artifacts), reports, source_policies=policies
    )
    _, handles = await current_input_source(factory, retriever)
    author = payload.children[0].binding
    from nexus.company.brain.base import BrainReadScope

    scope = BrainReadScope(
        company_id=COMPANY,
        workspace_id=author.workspace_id,
        principal_id=author.actor_id,
        operation_id=uuid4(),
        trace_id=uuid4(),
        task_id=author.task_id,
        task_trace_id=author.trace_id,
        actor_id=author.actor_id,
    )
    sources = await loader.prepare_sources(
        scope, identity(author.actor_id), tuple(row.evidence_id for row in handles)
    )
    producer = NativeReportProducer(factory, reports, loader)
    prepared = (
        await producer.prepare_report(
            scope,
            identity(author.actor_id),
            saved.report_id,
            tuple(row.evidence_id for row in handles),
        )
        if production
        else rendered_payload(saved, sources)
    )
    validator: GeneratedArtifactValidator = (
        ProductionValidator(producer)
        if production
        else NativeReportValidator(reports, loader, saved, sources)
    )
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
    parameters = GeneratedArtifactActionParameters(
        recipe_version=prepared.recipe_version,
        output_sha256=prepared.output_sha256,
        input_snapshot_sha256=prepared.input_snapshot_sha256,
        report_id=saved.report_id,
        evidence_ids=tuple(row.evidence_id for row in handles),
    )
    action = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=author.task_id,
        trace_id=author.trace_id,
        actor_id=author.actor_id,
        revision=1,
        tool=rules[0].tool,
        tool_version="v1",
        resource=rules[0].resource_symbol,
        parameters=parameters.model_dump(mode="json", exclude_none=True),
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.03"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(action, ledger(author))
    await journal.approve_registered(
        ledger(author).model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        ledger(author), action.action_id, datetime.now(UTC), (), identity=identity(author.actor_id)
    )
    lease = await execution.claim(
        ledger(author), identity(author.actor_id), uuid4(), ttl_seconds=ttl_seconds
    )
    await effects.begin(lease, identity(author.actor_id), action.action_id)
    publisher = GeneratedArtifactPublisher(
        factory, blobs, plans.catalog, artifacts, policies, validator, rules=rules
    )
    return GeneratedScenario(
        publisher,
        prepared,
        rules,
        plans,
        payload,
        action,
        lease,
        execution,
        effects,
        blobs,
        artifacts,
        validator,
        producer,
    )
