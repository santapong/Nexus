"""Real empty target, owner-selected native snapshot and source-only report preparation."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from litestar import Litestar
from sqlalchemy import select

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.contracts.actions import ActionProposal
from nexus.company.control_store import CompanyControls
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.action_review_store import OwnerActionReviewStore
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactActionParameters
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import NamedPlanResource
from nexus.company.management.plans import PlanPayload
from nexus.company.management.report_artifact_reader import ReportArtifactReader
from nexus.company.management.report_inputs import PersistentReportInputLoader
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.integration.management_acceptance_source_fixture import Policies, protected_text
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_control_support import charter
from nexus.tests.management_plan_support import VERIFIER, configured_plan
from nexus.tests.management_views_support import ViewsDatabase


@dataclass(frozen=True)
class GeneratedReviewScenario:
    app: Litestar
    action: ActionProposal
    target: UUID
    extra_resource: UUID
    reviews: OwnerActionReviewStore


async def generated_plan(
    database: ViewsDatabase, root: Path
) -> tuple[ManagementPlanStore, PlanPayload, ResourceRef]:
    plans, payload = await configured_plan(database.app, root)
    target = ResourceRef(company_id=COMPANY, resource_id=uuid4())
    await ArtifactTargetStore(database.app).provision(
        owner_scope(), identity(OWNER), target, readers=(OWNER, ACTOR, VERIFIER)
    )
    tool = ToolPermission(
        tool="company.report.write.v1", tool_version="v1", resource="company.report.output"
    )
    catalog = plans.catalog.model_copy(
        update={
            "tools": (*plans.catalog.tools, tool),
            "resources": (
                *plans.catalog.resources,
                NamedPlanResource(symbol=tool.resource, resource=target),
            ),
        }
    )
    declared = charter("native-review-v2", verifier=VERIFIER).model_copy(
        update={
            "allowed_tools": tuple(row.tool for row in catalog.tools),
            "resource_scopes": tuple(row.symbol for row in catalog.resources),
        }
    )
    registered = await ManagementControlStore(database.app).publish_charter(
        control(),
        identity(OWNER),
        declared,
        mandate=payload.mandate,
        expected_revision_id=payload.charters[0].revision_id,
    )
    reference = CharterRevisionRef.model_validate_json(
        registered.model_dump_json(include=set(CharterRevisionRef.model_fields))
    )
    payload = PlanPayload.model_validate_json(
        payload.model_copy(
            update={
                "charters": (reference,),
                "children": tuple(
                    child.model_copy(update={"charter": reference}) for child in payload.children
                ),
            }
        ).model_dump_json(by_alias=True)
    )
    plans = ManagementPlanStore(database.app, catalog)
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
    return plans, payload, target


async def generated_review_scenario(database: ViewsDatabase, root: Path) -> GeneratedReviewScenario:
    plans, payload, target = await generated_plan(database, root)
    blobs = ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    policies = Policies()
    # This cited input is outside the charter/catalog. Complete disclosure still needs its READ.
    extra = await protected_text(database.app, blobs, policies, "PRIVATE_EXTRA_CITATION", 4300)
    reader = PersistentBrainRetriever(database.app, blobs, limits=RetrievalLimits())
    artifacts = BoundedArtifactReader(database.app, blobs)
    freshness = RegisteredSourceFreshness(database.app, policies)
    reports = OperatingReportStore(database.app, plans.catalog, artifacts, freshness)
    async with brain_transaction(database.app, owner_scope(), identity(OWNER)) as (session, _, _):
        binding = await plans.current_binding(session, COMPANY, payload.children[0].binding.task_id)
        assert binding is not None
        evidence_ids = tuple(
            (
                await session.scalars(
                    select(BrainEvidence.evidence_id).where(
                        BrainEvidence.company_id == COMPANY,
                        BrainEvidence.artifact_revision_id == extra.artifact_revision_id,
                    )
                )
            ).all()
        )
    now = datetime.now(UTC)
    saved = await reports.save_snapshot(
        control(),
        identity(OWNER),
        binding.plan.plan_revision_id,
        payload.children[0].binding.task_id,
        (),
        period_start=now - timedelta(days=1),
        period_end=now,
    )
    loader = PersistentReportInputLoader(
        database.app, ReportArtifactReader(reader, artifacts), reports, source_policies=policies
    )
    producer = NativeReportProducer(database.app, reports, loader)
    author = payload.children[0].binding
    brain = BrainReadScope(
        company_id=COMPANY,
        workspace_id=author.workspace_id,
        principal_id=author.actor_id,
        operation_id=uuid4(),
        trace_id=uuid4(),
        task_id=author.task_id,
        task_trace_id=author.trace_id,
        actor_id=author.actor_id,
    )
    prepared = await producer.prepare_report(
        brain, identity(author.actor_id), saved.report_id, evidence_ids
    )
    pins = GeneratedArtifactActionParameters(
        recipe_version=prepared.recipe_version,
        output_sha256=prepared.output_sha256,
        input_snapshot_sha256=prepared.input_snapshot_sha256,
        report_id=saved.report_id,
        evidence_ids=evidence_ids,
    )
    action = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=author.task_id,
        trace_id=author.trace_id,
        actor_id=author.actor_id,
        revision=1,
        tool="company.report.write.v1",
        tool_version="v1",
        resource="company.report.output",
        parameters=pins.model_dump(mode="json", exclude_none=True),
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.03"),
    )
    journal = CompanyJournal(database.app)
    await journal.submit(
        action,
        LedgerScope(
            company_id=COMPANY,
            principal_id=author.actor_id,
            task_id=author.task_id,
            trace_id=author.trace_id,
        ),
    )
    directory = PersistentCompanyDirectory(database.app)
    reviews = OwnerActionReviewStore(
        database.app, plans.catalog, OwnerViewSources(artifacts, freshness), reports
    )
    management = ManagementApiServices(
        directory,
        ManagementControlStore(database.app),
        GoalStore(database.app, reader),
        plans,
        action_reviews=reviews,
    )
    app = create_company_app(
        CompanyServices(directory, journal, CompanyControls(database.app)),
        management_services=management,
    )
    return GeneratedReviewScenario(app, action, target.resource_id, UUID(int=4301), reviews)
