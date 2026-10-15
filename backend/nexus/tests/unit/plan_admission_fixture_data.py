"""Genuine ordinary four-child declarations and ORM metadata; no SQL/native activation."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.base import SourceTime
from nexus.company.brain.source_models import BrainSource, BrainSourceHead
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.contracts.company import CompanyMandate, DepartmentCharter
from nexus.company.contracts.work import WorkItem, WorkPlan
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import (
    DueIntent,
    GoalDefinition,
    GoalMetric,
    GoalRevisionRef,
    UnknownBaseline,
)
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.governance_models import (
    ManagementCharterHead,
    ManagementCharterRevision,
    ManagementGoalHead,
    ManagementGoalRevision,
    ManagementMandateHead,
    ManagementMandateRevision,
)
from nexus.company.management.plan_catalog import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.management.plans import (
    ChildAllocation,
    PlanPayload,
    ProcedureRoot,
    RunBinding,
    VerificationIntent,
)
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.journal_models import CompanyControl
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.unit.plan_admission_fixture_values import (
    COMPANY as COMPANY,
)
from nexus.tests.unit.plan_admission_fixture_values import (
    NOW as NOW,
)
from nexus.tests.unit.plan_admission_fixture_values import (
    OWNER as OWNER,
)
from nexus.tests.unit.plan_admission_fixture_values import (
    WORKSPACE as WORKSPACE,
)
from nexus.tests.unit.plan_admission_fixture_values import (
    ordinary_catalog,
    source_values,
)


@dataclass
class AdmissionFixture:
    payload: PlanPayload
    catalog: PlanAdmissionCatalog
    control: CompanyControl
    scope: CompanyControlScope
    identity: VerifiedIdentity
    objects: dict[tuple[object, object], object]
    grants: list[BrainResourceAccess]
    source: BrainSource
    head: BrainSourceHead
    policy: SourcePolicy


def ordinary_fixture() -> AdmissionFixture:
    # This >50-line cohesive pure declaration keeps real governance refs and all four roles exact.
    objects: dict[tuple[object, object], object] = {}

    def put(row: object, key: object) -> None:
        objects[type(row), key] = row

    mandate = CompanyMandate(
        company_id=COMPANY,
        owner_id=OWNER,
        version="v1",
        purpose="Pure temporal protocol",
        goals=(UUID(int=11),),
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(2),
    )
    mref = RevisionRef(
        company_id=COMPANY, revision_id=UUID(int=50), version="v1", sha256=canonical_sha256(mandate)
    )
    put(
        ManagementMandateHead(
            company_id=COMPANY, current_revision_id=mref.revision_id, active=True
        ),
        COMPANY,
    )
    put(
        ManagementMandateRevision(
            company_id=COMPANY,
            revision_id=mref.revision_id,
            version="v1",
            owner_id=OWNER,
            sha256=mref.sha256,
            payload_json=mandate.model_dump_json(),
            recorded_by=OWNER,
            recorded_at=NOW,
        ),
        (COMPANY, mref.revision_id),
    )
    bound = []
    children = []
    items = []
    charters = []
    resources: list[NamedPlanResource] = []
    tools = []
    grants = []
    verifier = UUID(int=203)
    for index, role in enumerate(("strategy", "strategy_check", "presentation", "support")):
        number = (index + 1) * 100
        actor = UUID(int=number + 3)
        resource = UUID(int=2000 + (0 if index < 2 else index))
        symbol = "fixture.base" if index < 2 else f"fixture.{role}"
        tool = ToolPermission(tool=f"{symbol}.read.v1", tool_version="v1", resource=symbol)
        b = RunBinding(
            company_id=COMPANY,
            workspace_id=WORKSPACE,
            actor_id=actor,
            task_id=UUID(int=number),
            trace_id=UUID(int=number + 1),
            run_id=UUID(int=number + 2),
            workflow_name="fixture.internal",
            workflow_version="v1",
            model_profile="engineering" if index == 2 else "routine",
            model_registry_version="catalog-v1",
        )
        bound.append(b)
        charter = DepartmentCharter(
            company_id=COMPANY,
            department_id=UUID(int=3000 + index),
            name=role,
            version="v1",
            responsibilities=("Pure mocked temporal qualification",),
            allowed_tools=(tool.tool,),
            resource_scopes=(symbol,),
            deliverables=("Mechanical test only",),
            verifier_id=verifier,
        )
        cref = CharterRevisionRef(
            company_id=COMPANY,
            department_id=charter.department_id,
            revision_id=UUID(int=4000 + index),
            version="v1",
            sha256=canonical_sha256(charter),
        )
        charters.append(cref)
        put(
            ManagementCharterHead(
                company_id=COMPANY,
                department_id=cref.department_id,
                current_revision_id=cref.revision_id,
                active=True,
            ),
            (COMPANY, cref.department_id),
        )
        put(
            ManagementCharterRevision(
                company_id=COMPANY,
                revision_id=cref.revision_id,
                department_id=cref.department_id,
                version="v1",
                mandate_revision_id=mref.revision_id,
                sha256=cref.sha256,
                payload_json=charter.model_dump_json(),
                recorded_by=OWNER,
                recorded_at=NOW,
            ),
            (COMPANY, cref.revision_id),
        )
        children.append(
            ChildAllocation(
                company_id=COMPANY,
                binding=b,
                charter=cref,
                allocation_usd=Decimal(".25"),
                quota=AttemptQuota(
                    model_requests=1, tool_attempts=1, rework_rounds=0, plan_revisions=0
                ),
            )
        )
        items.append(
            WorkItem(
                company_id=COMPANY,
                task_id=b.task_id,
                trace_id=b.trace_id,
                goal_id=UUID(int=11),
                department=role,
                title="Pure ordinary role",
                acceptance=("mechanical.fixture",),
                budget_usd=Decimal(".25"),
            )
        )
        put(
            DirectoryMembership(
                company_id=COMPANY,
                principal_id=actor,
                role="member",
                principal_active=True,
                membership_active=True,
            ),
            (COMPANY, actor),
        )
        if resource not in {x.resource.resource_id for x in resources}:
            resources.append(
                NamedPlanResource(
                    symbol=symbol, resource=ResourceRef(company_id=COMPANY, resource_id=resource)
                )
            )
            tools.append(tool)
            put(
                BrainResource(
                    company_id=COMPANY,
                    resource_id=resource,
                    kind="source" if index == 0 else "artifact",
                    active=True,
                    acl_generation=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                (COMPANY, resource),
            )
        for principal in {actor, verifier}:
            if (BrainResourceAccess, (COMPANY, resource, principal)) not in objects:
                grant = BrainResourceAccess(
                    company_id=COMPANY,
                    resource_id=resource,
                    principal_id=principal,
                    active=True,
                    generation=1,
                    expires_at=NOW + timedelta(seconds=5)
                    if index == 2 and principal == actor
                    else None,
                )
                grants.append(grant)
                put(grant, (COMPANY, resource, principal))
    goal = GoalDefinition(
        company_id=COMPANY,
        goal_id=UUID(int=11),
        title="Pure future composition",
        owner_id=bound[0].actor_id,
        mandate=mref,
        metrics=(
            GoalMetric(
                company_id=COMPANY,
                metric_id="mechanical",
                unit="state",
                comparator="eq",
                target=Decimal(1),
                baseline=UnknownBaseline(reason="No business claim"),
            ),
        ),
        due=DueIntent(
            source_time=SourceTime(precision="unknown", value=None, basis="No deadline supplied")
        ),
    )
    gref = GoalRevisionRef(
        company_id=COMPANY,
        goal_id=goal.goal_id,
        revision_id=UUID(int=60),
        version="v1",
        sha256=canonical_sha256(goal),
    )
    put(
        ManagementGoalHead(
            company_id=COMPANY,
            goal_id=goal.goal_id,
            current_revision_id=gref.revision_id,
            active=True,
        ),
        (COMPANY, goal.goal_id),
    )
    put(
        ManagementGoalRevision(
            company_id=COMPANY,
            revision_id=gref.revision_id,
            goal_id=goal.goal_id,
            version="v1",
            mandate_revision_id=mref.revision_id,
            responsible_id=goal.owner_id,
            sha256=gref.sha256,
            payload_json=goal.model_dump_json(),
            recorded_by=OWNER,
            recorded_at=NOW,
        ),
        (COMPANY, gref.revision_id),
    )
    parent = bound[0].model_copy(
        update={
            "task_id": UUID(int=4),
            "trace_id": UUID(int=5),
            "run_id": UUID(int=6),
            "actor_id": OWNER,
        }
    )
    payload = PlanPayload(
        company_id=COMPANY,
        goal=gref,
        mandate=mref,
        charters=tuple(charters),
        children=tuple(children),
        verification=(
            VerificationIntent(
                company_id=COMPANY,
                author_task_id=bound[0].task_id,
                verifier_task_id=bound[1].task_id,
                check_recipe="fixture.check.v1",
            ),
        ),
        procedure=ProcedureRoot(
            company_id=COMPANY,
            procedure_id=UUID(int=73),
            goal_id=goal.goal_id,
            binding=parent,
            allocation_usd=Decimal(2),
            quota=AttemptQuota(
                model_requests=4, tool_attempts=4, rework_rounds=0, plan_revisions=1
            ),
        ),
        plan=WorkPlan(
            company_id=COMPANY,
            plan_id=UUID(int=70),
            goal_id=goal.goal_id,
            revision=1,
            items=tuple(items),
        ),
    )

    catalog = ordinary_catalog(resources, tools)
    control = CompanyControl(
        company_id=COMPANY,
        owner_id=OWNER,
        policy_version="fixture-policy",
        price_version="fixture-prices",
        paused=False,
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(2),
    )
    put(
        DirectoryCompany(
            company_id=COMPANY,
            workspace_id=WORKSPACE,
            owner_id=OWNER,
            company_active=True,
            workspace_active=True,
        ),
        COMPANY,
    )
    put(
        DirectoryMembership(
            company_id=COMPANY,
            principal_id=OWNER,
            role="owner",
            principal_active=True,
            membership_active=True,
        ),
        (COMPANY, OWNER),
    )
    policy, source, head = source_values()
    put(source, (COMPANY, source.source_id))
    put(head, (COMPANY, source.source_id))
    return AdmissionFixture(
        payload,
        catalog,
        control,
        CompanyControlScope(
            company_id=COMPANY, principal_id=OWNER, operation_id=UUID(int=7), trace_id=UUID(int=8)
        ),
        VerifiedIdentity(principal_id=OWNER, workspace_id=WORKSPACE),
        objects,
        grants,
        source,
        head,
        policy,
    )
