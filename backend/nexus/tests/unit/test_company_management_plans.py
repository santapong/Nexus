"""Approved declaration payloads retain root quota, selected charter and both edge kinds."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.contracts.work import WorkItem, WorkPlan
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_json, canonical_sha256
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.lifecycle import PlanRevision, PlanSnapshot
from nexus.company.management.plans import (
    ChildAllocation,
    PlanPayload,
    ProcedureRoot,
    VerificationIntent,
)
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.tests.unit.test_company_management_contracts import COMPANY, binding


def payload() -> PlanPayload:
    charter = CharterRevisionRef(
        company_id=COMPANY,
        department_id=UUID(int=60),
        revision_id=UUID(int=61),
        version="v1",
        sha256="a" * 64,
    )
    child_bindings = (
        binding(
            task_id=UUID(int=100),
            trace_id=UUID(int=101),
            run_id=UUID(int=102),
            actor_id=UUID(int=103),
        ),
        binding(
            task_id=UUID(int=200),
            trace_id=UUID(int=201),
            run_id=UUID(int=202),
            actor_id=UUID(int=203),
        ),
    )
    return PlanPayload(
        company_id=COMPANY,
        plan=WorkPlan(
            company_id=COMPANY,
            plan_id=UUID(int=70),
            goal_id=UUID(int=11),
            revision=1,
            items=tuple(
                WorkItem(
                    company_id=COMPANY,
                    task_id=ref.task_id,
                    trace_id=ref.trace_id,
                    goal_id=UUID(int=11),
                    department="research",
                    title="Bounded internal work",
                    acceptance=("citation.coverage",),
                    budget_usd=Decimal("0.50"),
                )
                for ref in child_bindings
            ),
        ),
        goal=GoalRevisionRef(
            company_id=COMPANY,
            goal_id=UUID(int=11),
            revision_id=UUID(int=71),
            version="v1",
            sha256="b" * 64,
        ),
        mandate=RevisionRef(
            company_id=COMPANY, revision_id=UUID(int=72), version="v1", sha256="c" * 64
        ),
        charters=(charter,),
        procedure=ProcedureRoot(
            company_id=COMPANY,
            procedure_id=UUID(int=73),
            goal_id=UUID(int=11),
            binding=binding(),
            allocation_usd=Decimal(1),
            quota=AttemptQuota(),
        ),
        children=tuple(
            ChildAllocation(
                company_id=COMPANY,
                binding=ref,
                charter=charter,
                allocation_usd=Decimal("0.5"),
                quota=AttemptQuota(
                    model_requests=6, tool_attempts=10, rework_rounds=1, plan_revisions=0
                ),
            )
            for ref in child_bindings
        ),
        verification=(
            VerificationIntent(
                company_id=COMPANY,
                author_task_id=UUID(int=100),
                verifier_task_id=UUID(int=200),
                check_recipe="report.check.v1",
            ),
        ),
    )


def test_plan_has_nonexecuting_root_and_verification_trigger_not_an_accepted_dependency() -> None:
    value = payload()
    assert value.procedure.non_executing and value.plan.items[1].depends_on == ()
    assert value.verification[0].author_task_id == value.plan.items[0].task_id
    assert sum(row.quota.plan_revisions for row in value.children) == 0


@pytest.mark.parametrize("bad", [True, 1.0, "1"])
def test_raw_legacy_plan_revision_cannot_be_coerced_into_approval_snapshot(bad: object) -> None:
    data = payload().model_dump()
    data["plan"]["revision"] = bad
    with pytest.raises(ValidationError):
        PlanPayload.model_validate(data)


@pytest.mark.parametrize(
    "problem",
    [
        "quota",
        "usd",
        "charter",
        "duplicate_charter",
        "duplicate_verifier",
        "self_verifier",
        "cycle",
    ],
)
def test_declared_partitions_and_exact_trigger_charter_mappings_fail_closed(problem: str) -> None:
    value = payload()
    data = value.model_dump()
    if problem == "quota":
        data["children"][0]["quota"]["model_requests"] = 12
    elif problem == "usd":
        data["procedure"]["allocation_usd"] = Decimal("0.9")
    elif problem == "charter":
        data["children"][0]["charter"]["revision_id"] = UUID(int=99)
    elif problem == "duplicate_charter":
        data["charters"] += data["charters"]
    elif problem == "duplicate_verifier":
        data["verification"] += data["verification"]
    elif problem == "self_verifier":
        data["children"][1]["binding"]["actor_id"] = data["children"][0]["binding"]["actor_id"]
    else:
        data["plan"]["items"][0]["depends_on"] = (UUID(int=200),)
    with pytest.raises(ValidationError):
        PlanPayload.model_validate(data)


def test_canonical_usd_is_exact_six_places_and_lifecycle_is_not_payload_authority() -> None:
    value = payload()
    assert '"allocation_usd":"1.000000"' in canonical_json(value)
    same = value.model_dump()
    same["procedure"]["allocation_usd"] = Decimal("1.00")
    assert canonical_sha256(PlanPayload.model_validate(same)) == canonical_sha256(value)
    row = PlanRevision(
        company_id=COMPANY,
        plan_id=value.plan.plan_id,
        plan_revision_id=UUID(int=80),
        revision=1,
        sha256=canonical_sha256(value),
        payload=value,
        proposed_by=UUID(int=103),
        recorded_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError):
        PlanSnapshot(company_id=COMPANY, revision=row, state="approved")
    assert PlanSnapshot(company_id=COMPANY, revision=row, state="proposed").decision is None
