"""Direct empty-model CSV plan using current public company/evidence/governance stores."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contracts import BuilderJobSpec, RepositoryPin
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.node_recipe import command_references
from nexus.builder.policy import BuilderToolPolicy
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.source_models import BrainSourceHead
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.work import WorkItem, WorkPlan
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.native_execution_profiles import (
    NATIVE_CRITERIA,
    NativeExecutionProfile,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.plans import (
    ChildAllocation,
    PlanPayload,
    ProcedureRoot,
    RunBinding,
    VerificationIntent,
)
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.csv_native_runtime import limits
from nexus.tests.integration.test_company_brain_ingestion import (
    RESOURCE,
    SOURCE,
    Reader,
    command,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, WORKSPACE, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_goals import goal
from nexus.tests.management_control_support import GOAL, charter, mandate
from nexus.tests.management_plan_support import VERIFIER

RESOURCE_SYMBOL = "engineering.output"
PERMISSION = ToolPermission(
    tool="company.builder.run.v1", tool_version="v1", resource=RESOURCE_SYMBOL
)


def quotas() -> tuple[AttemptQuota, AttemptQuota]:
    return (
        AttemptQuota(model_requests=0, tool_attempts=2, rework_rounds=0, plan_revisions=0),
        AttemptQuota(model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0),
    )


def empty_catalog(output: ResourceRef) -> PlanAdmissionCatalog:
    registry = ModelRegistry(
        company_id=COMPANY, revision="csv-native-empty-v1", pricebook_version="fixture-prices"
    )
    pairs: tuple[
        tuple[
            Literal["engineering.native.v1", "verification.native.v1"],
            Literal["engineering.change", "engineering.verify"],
        ],
        ...,
    ] = (
        ("engineering.native.v1", "engineering.change"),
        ("verification.native.v1", "engineering.verify"),
    )
    profiles = tuple(
        NativeExecutionProfile(
            company_id=COMPANY,
            execution_profile=profile,
            workflow_name=workflow,
            registry_revision=registry.revision,
            registry_sha256=canonical_sha256(registry),
            tools=(PERMISSION,),
        )
        for profile, workflow in pairs
    )
    return PlanAdmissionCatalog(
        company_id=COMPANY,
        models=registry,
        tools=(PERMISSION,),
        resources=(NamedPlanResource(symbol=RESOURCE_SYMBOL, resource=output),),
        admitted_profiles=frozenset(),
        check_recipes=frozenset({"native-engineering-change-v1"}),
        native_profiles=profiles,
    )


async def plan_source(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> tuple[PersistentBrainRetriever, EvidenceRef]:
    raw = b"Citation coverage baseline: 0. Generated public CSV qualification; no acceptance yet."
    ingestion = await configured(factory, root, Reader({"r2": raw}))
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        head = await session.get(BrainSourceHead, (COMPANY, SOURCE))
        assert head is not None and head.availability == "quarantined"
        previous = head.current_revision_id
    receipt = await ingestion.ingest(owner_scope(), identity(OWNER), command(raw, "r2", previous))
    with (root / "goal-source-ingest-r2-receipt.json").open("x") as stream:
        stream.write(receipt.model_dump_json())
    assert receipt.status == "accepted" and receipt.reason_code is None, receipt.model_dump_json()
    await PersistentCompanyDirectory(factory).set_membership(
        MembershipChange(company_id=COMPANY, principal_id=VERIFIER, role="member"), control()
    )
    await ResourceAccessStore(factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=VERIFIER,
            active=True,
            expected_generation=1,
        ),
    )
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        evidence_id = await session.scalar(select(BrainEvidence.evidence_id))
    assert evidence_id is not None
    return (
        PersistentBrainRetriever(
            factory,
            ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
            limits=RetrievalLimits(),
        ),
        EvidenceRef(company_id=COMPANY, evidence_id=evidence_id),
    )


async def plan_charters(
    factory: async_sessionmaker[AsyncSession], mandate_ref: RevisionRef
) -> tuple[CharterRevisionRef, ...]:
    controls, results = ManagementControlStore(factory), []
    for name in ("engineering", "verification"):
        published = await controls.publish_charter(
            control(),
            identity(OWNER),
            charter("csv-native-v4", verifier=VERIFIER).model_copy(
                update={
                    "department_id": uuid4(),
                    "name": name,
                    "allowed_tools": (PERMISSION.tool,),
                    "resource_scopes": (RESOURCE_SYMBOL,),
                    "responsibilities": ("Generated public CSV correctness; no private claim",),
                    "deliverables": ("Actual independent bounded code/check evidence",),
                }
            ),
            mandate=mandate_ref,
            expected_revision_id=None,
        )
        results.append(
            CharterRevisionRef.model_validate_json(
                published.model_dump_json(include=set(CharterRevisionRef.model_fields))
            )
        )
    return tuple(results)


async def create_plan(
    factory: async_sessionmaker[AsyncSession], root: Path, output: ResourceRef
) -> tuple[ManagementPlanStore, PlanPayload]:
    """Build public plan declarations; caller separately registers actual exact owner approval."""
    retriever, evidence = await plan_source(factory, root)
    controls = ManagementControlStore(factory)
    published = await controls.publish_mandate(
        control(), identity(OWNER), mandate("csv-native-v4"), expected_revision_id=None
    )
    mref = RevisionRef.model_validate_json(
        published.model_dump_json(include=set(RevisionRef.model_fields))
    )
    charters = await plan_charters(factory, mref)
    published_goal = await GoalStore(factory, retriever).publish(
        control(),
        identity(OWNER),
        goal(mref, evidence).model_copy(
            update={
                "title": "Qualify generated public full CSV fixture; business readiness unproven"
            }
        ),
        version="csv-native-v4",
        expected_revision_id=None,
    )
    gref = GoalRevisionRef.model_validate_json(
        published_goal.model_dump_json(include=set(GoalRevisionRef.model_fields))
    )
    await ArtifactTargetStore(factory).provision(
        owner_scope(), identity(OWNER), output, readers=(OWNER, ACTOR, VERIFIER)
    )
    catalog = empty_catalog(output)
    return ManagementPlanStore(factory, catalog), _payload(mref, gref, charters, catalog)


def _binding(actor: UUID, profile: NativeExecutionProfile) -> RunBinding:
    return RunBinding(
        company_id=COMPANY,
        workspace_id=WORKSPACE,
        actor_id=actor,
        task_id=uuid4(),
        trace_id=uuid4(),
        run_id=uuid4(),
        workflow_name=profile.workflow_name,
        workflow_version=profile.workflow_version,
        model_profile=profile.execution_profile,
        model_registry_version=profile.registry_revision,
    )


def _payload(
    mref: RevisionRef,
    gref: GoalRevisionRef,
    charters: tuple[CharterRevisionRef, ...],
    catalog: PlanAdmissionCatalog,
) -> PlanPayload:
    parent_quota, child_quota = quotas()
    children = tuple(
        ChildAllocation(
            company_id=COMPANY,
            binding=_binding(actor, profile),
            charter=cref,
            allocation_usd=Decimal("0.20"),
            quota=child_quota,
        )
        for actor, profile, cref in zip(
            (ACTOR, VERIFIER), catalog.native_profiles, charters, strict=True
        )
    )
    return PlanPayload(
        company_id=COMPANY,
        mandate=mref,
        goal=gref,
        charters=charters,
        children=children,
        plan=_work_plan(children),
        procedure=ProcedureRoot(
            company_id=COMPANY,
            procedure_id=uuid4(),
            goal_id=GOAL,
            binding=_binding(OWNER, catalog.native_profiles[0]),
            allocation_usd=Decimal("1.00"),
            quota=parent_quota,
        ),
        verification=(
            VerificationIntent(
                company_id=COMPANY,
                author_task_id=children[0].binding.task_id,
                verifier_task_id=children[1].binding.task_id,
                check_recipe="native-engineering-change-v1",
            ),
        ),
    )


def _work_plan(children: tuple[ChildAllocation, ...]) -> WorkPlan:
    return WorkPlan(
        company_id=COMPANY,
        plan_id=uuid4(),
        goal_id=GOAL,
        revision=1,
        items=tuple(
            WorkItem(
                company_id=COMPANY,
                task_id=row.binding.task_id,
                trace_id=row.binding.trace_id,
                goal_id=GOAL,
                department=name,
                title="Generated public CSV native qualification",
                acceptance=NATIVE_CRITERIA,
                budget_usd=row.allocation_usd,
            )
            for name, row in zip(("engineering", "verification"), children, strict=True)
        ),
    )


def native_spec(
    bound: RunBinding,
    policy: BuilderToolPolicy,
    source: RepositoryPin,
    patch: ArtifactRevisionRef,
    output: ResourceRef,
) -> BuilderExecutionSpec:
    return BuilderExecutionSpec(
        job=BuilderJobSpec(
            company_id=bound.company_id,
            task_id=bound.task_id,
            trace_id=bound.trace_id,
            run_id=bound.run_id,
            workspace_id=bound.workspace_id,
            actor_id=bound.actor_id,
            action_id=uuid4(),
            policy_symbol=policy.policy_symbol,
            resource_symbol=policy.resource_symbol,
            architecture="amd64",
            source=source,
            patch_sha256=patch.sha256,
            write_paths=policy.write_paths,
            artifact_paths=policy.artifact_paths,
            commands=command_references(),
            limits=limits(),
        ),
        policy_sha256=canonical_sha256(policy),
        protected_patch=patch,
        output_resource=output,
        runtime_inputs=policy.runtime_inputs,
    )


def native_action(spec: BuilderExecutionSpec) -> ActionProposal:
    job = spec.job
    return ActionProposal(
        company_id=job.company_id,
        action_id=job.action_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        actor_id=job.actor_id,
        revision=1,
        tool=PERMISSION.tool,
        tool_version=PERMISSION.tool_version,
        resource=PERMISSION.resource,
        parameters=spec.model_dump(mode="json"),
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.01"),
    )


async def approve_action(
    factory: async_sessionmaker[AsyncSession], bound: RunBinding, action: ActionProposal
) -> None:
    scope = ledger_scope(bound)
    journal = CompanyJournal(factory)
    await journal.submit(action, scope)
    await journal.approve_registered(
        scope.model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        scope, action.action_id, datetime.now(UTC), (), identity=identity(bound.actor_id)
    )


def ledger_scope(bound: RunBinding) -> LedgerScope:
    return LedgerScope(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        principal_id=bound.actor_id,
    )
