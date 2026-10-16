"""Actual qualification predicates over supplied native rows; no database or owner authority."""

from datetime import timedelta
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import SourceTime
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.contracts.company import CompanyMandate
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import DueIntent, GoalDefinition, GoalMetric, UnknownBaseline
from nexus.company.management.governance_models import (
    ManagementGoalHead,
    ManagementGoalRevision,
    ManagementMandateHead,
    ManagementMandateRevision,
)
from nexus.core.llm.company_pricing import quote_cost
from nexus.core.llm.qualification_contracts import (
    PROFILE,
    TOOL,
    WORKFLOW,
    financial_bounds,
    qualification_parameters,
    qualification_request,
    target_set_hash,
)
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionLease, ExecutionRegistration
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.canonical import action_hash
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import (
    CompanyControl,
    CostHold,
    DailyBudget,
    JournalAction,
    WorkBudget,
)
from nexus.harness.qualification_intent import QualificationIntentCheck
from nexus.tests.unit.test_qualification_contracts import NOW, recipe, scope


def native() -> tuple[
    QualificationIntentCheck,
    AsyncSession,
    CompanyControl,
    ExecutionWork,
    JournalAction,
    ManagementGoalHead,
]:
    """Closed finite native row delivery, not permission to use any real store."""
    value = recipe()
    mandate = CompanyMandate(
        company_id=scope().company_id,
        owner_id=scope().principal_id,
        version="v1",
        purpose="Owner requested public qualification",
    )
    mandate_ref = RevisionRef(
        company_id=scope().company_id,
        revision_id=UUID(int=22),
        version="v1",
        sha256=canonical_sha256(mandate),
    )
    goal = GoalDefinition(
        company_id=scope().company_id,
        goal_id=value.goal.goal_id,
        title="Check SDK conformance",
        owner_id=scope().principal_id,
        mandate=mandate_ref,
        metrics=(
            GoalMetric(
                company_id=scope().company_id,
                metric_id="observations",
                unit="count",
                comparator="ge",
                target=Decimal(1),
                baseline=UnknownBaseline(reason="No observations"),
            ),
        ),
        due=DueIntent(
            source_time=SourceTime(precision="unknown", value=None, basis="Not scheduled")
        ),
    )
    value = value.model_copy(
        update={"goal": value.goal.model_copy(update={"sha256": canonical_sha256(goal)})}
    )
    call = qualification_request(value, scope(), action_id=UUID(int=5), request_id=UUID(int=6))
    lease = ExecutionLease(
        company_id=scope().company_id,
        task_id=scope().task_id,
        trace_id=scope().trace_id,
        actor_id=scope().principal_id,
        workspace_id=UUID(int=7),
        run_id=UUID(int=10),
        workflow_version="v1",
        segment_id=UUID(int=11),
        worker_id=UUID(int=12),
        fence=1,
        expires_at=NOW + timedelta(minutes=5),
        mode="execute",
    )
    identity = VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id)
    registration = ExecutionRegistration(
        work=WorkItem(
            company_id=lease.company_id,
            task_id=lease.task_id,
            trace_id=lease.trace_id,
            goal_id=value.goal.goal_id,
            department="management",
            title="Public qualification",
            acceptance=(
                value.purpose,
                "target-set:"
                + target_set_hash(value.registry_revision, value.qualification_target_sha256s),
            ),
            budget_usd=Decimal("1"),
        ),
        run_id=lease.run_id,
        workflow_name=WORKFLOW,
        workflow_version="v1",
        model_profile=PROFILE,
        model_registry_version=value.registry_revision,
        quota=AttemptQuota(model_requests=12, tool_attempts=0, rework_rounds=0, plan_revisions=0),
    )
    work = ExecutionWork(
        company_id=lease.company_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        actor_id=lease.actor_id,
        workspace_id=lease.workspace_id,
        parent_task_id=None,
        run_id=lease.run_id,
        registration_json=registration.model_dump_json(),
        registration_hash=registration_digest(registration),
        workflow_name=WORKFLOW,
        workflow_version="v1",
        model_profile=PROFILE,
        model_registry_version=value.registry_revision,
        state="running",
        fence=1,
        worker_id=lease.worker_id,
        lease_principal_id=lease.actor_id,
        lease_until=lease.expires_at,
        lease_mode="execute",
        segment_number=1,
        segment_id=lease.segment_id,
        waiting_action_id=None,
        **{
            f"{kind}_{suffix}": 0
            for kind in AttemptQuota.model_fields
            for suffix in ("used", "delegated")
        },
        **{
            f"{kind}_limit": getattr(registration.quota, kind) for kind in AttemptQuota.model_fields
        },
    )
    amount = quote_cost(value.target.price, financial_bounds(value), now=NOW).amount_usd
    proposal = ActionProposal(
        company_id=lease.company_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        actor_id=lease.actor_id,
        action_id=call.action_id,
        revision=1,
        tool=TOOL,
        tool_version="v1",
        resource=f"model-qualification:{value.target.registry_id}",
        parameters=qualification_parameters(value, call),
        policy_version="policy-v1",
        price_version=call.price_version,
        estimated_cost_usd=amount,
    )
    approval = ApprovalDecision(
        company_id=lease.company_id,
        decision_id=UUID(int=15),
        action_id=call.action_id,
        action_revision=1,
        action_hash=action_hash(proposal),
        approver_id=lease.actor_id,
        decision="approved",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=4),
    )
    action = JournalAction(
        id=call.action_id,
        company_id=lease.company_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        proposal_json=proposal.model_dump_json(),
        proposal_hash=action_hash(proposal),
        state="authorized",
        consumed_at=NOW,
        approval_json=approval.model_dump_json(),
    )
    control = CompanyControl(
        company_id=lease.company_id,
        owner_id=lease.actor_id,
        policy_version="policy-v1",
        price_version=call.price_version,
        paused=False,
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(1),
    )
    head = ManagementGoalHead(
        company_id=lease.company_id,
        goal_id=value.goal.goal_id,
        current_revision_id=value.goal.revision_id,
        active=True,
    )
    rows: dict[type[object], object] = {
        ManagementGoalHead: head,
        ManagementGoalRevision: ManagementGoalRevision(
            company_id=lease.company_id,
            goal_id=value.goal.goal_id,
            revision_id=value.goal.revision_id,
            version="v1",
            mandate_revision_id=mandate_ref.revision_id,
            responsible_id=lease.actor_id,
            sha256=canonical_sha256(goal),
            payload_json=goal.model_dump_json(),
            actionable_at=None,
            recorded_by=lease.actor_id,
            recorded_at=NOW,
        ),
        ManagementMandateHead: ManagementMandateHead(
            company_id=lease.company_id, current_revision_id=mandate_ref.revision_id, active=True
        ),
        ManagementMandateRevision: ManagementMandateRevision(
            company_id=lease.company_id,
            revision_id=mandate_ref.revision_id,
            version="v1",
            owner_id=lease.actor_id,
            sha256=canonical_sha256(mandate),
            payload_json=mandate.model_dump_json(),
            recorded_by=lease.actor_id,
            recorded_at=NOW,
        ),
        CostHold: CostHold(
            action_id=call.action_id,
            company_id=lease.company_id,
            task_id=lease.task_id,
            day=billing_day(NOW),
            amount_usd=amount,
            state="held",
            actual_usd=None,
        ),
        DailyBudget: DailyBudget(
            company_id=lease.company_id, day=billing_day(NOW), held_usd=amount, spent_usd=Decimal(0)
        ),
        WorkBudget: WorkBudget(
            company_id=lease.company_id,
            task_id=lease.task_id,
            held_usd=amount,
            spent_usd=Decimal(0),
        ),
        RegisteredWork: RegisteredWork(
            company_id=lease.company_id,
            task_id=lease.task_id,
            allocation_usd=Decimal(1),
            delegated_usd=Decimal(0),
            parent_task_id=None,
        ),
    }

    async def get(model: type[object], key: object) -> object:
        return rows[model]

    mock_session = MagicMock(spec=AsyncSession)
    mock_session.get = AsyncMock(side_effect=get)
    mock_session.in_transaction = MagicMock(return_value=True)
    session = cast(AsyncSession, mock_session)
    factory = cast(async_sessionmaker[AsyncSession], object())
    check = QualificationIntentCheck(factory, EffectStore(factory), lease, identity, value, call)
    return check, session, control, work, action, head


async def test_actual_predicates_accept_unknown_model_but_require_current_goal_and_expiry() -> None:
    check, session, control, work, action, head = native()
    await check.validate(session, control, work, action, NOW)
    check.validate_time(NOW)
    with pytest.raises(ValueError, match="expired"):
        check.validate_time(NOW + timedelta(minutes=4))
    head.active = False
    with pytest.raises(ValueError, match="active"):
        await check.validate(session, control, work, action, NOW)


@pytest.mark.parametrize(
    "fault", ["owner", "goal", "profile", "tool", "factory", "quota", "target-set"]
)
async def test_native_configuration_splices_are_denied(fault: str) -> None:
    check, session, control, work, action, _ = native()
    if fault == "owner":
        control.owner_id = UUID(int=99)
    elif fault == "goal":
        row = ExecutionRegistration.model_validate_json(work.registration_json)
        row = row.model_copy(update={"work": row.work.model_copy(update={"goal_id": UUID(int=99)})})
        work.registration_json = row.model_dump_json()
        work.registration_hash = registration_digest(row)
    elif fault in {"quota", "target-set"}:
        row = ExecutionRegistration.model_validate_json(work.registration_json)
        if fault == "quota":
            row = row.model_copy(
                update={"quota": row.quota.model_copy(update={"model_requests": 1})}
            )
        else:
            row = row.model_copy(
                update={"work": row.work.model_copy(update={"acceptance": ("wrong-set",)})}
            )
        work.registration_json = row.model_dump_json()
        work.registration_hash = registration_digest(row)
    elif fault == "profile":
        work.model_profile = "reasoning"
    elif fault == "tool":
        proposal = ActionProposal.model_validate_json(action.proposal_json).model_copy(
            update={"tool": "model.request.v1"}
        )
        action.proposal_json = proposal.model_dump_json()
    else:
        check._effects._factory = cast(async_sessionmaker[AsyncSession], object())
    with pytest.raises(ValueError):
        await check.validate(session, control, work, action, NOW)


def test_correlated_factory_store_splice_before_first_use_is_denied() -> None:
    check, *_ = native()
    replacement = cast(async_sessionmaker[AsyncSession], object())
    check._factory = replacement
    check._effects = EffectStore(replacement)
    with pytest.raises(ValueError, match="composition"):
        check.require_composition()
