"""Read-only report arithmetic from exact authorized facts, never authority or completion."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.access import Capability, PrincipalAccess, require_capability
from nexus.company.brain.base import Flag, Name, require_company
from nexus.company.contracts.results import ActionReceipt, VerificationResult
from nexus.company.management.base import SHA256, ManagementContract
from nexus.company.management.eligibility_rules import (
    AcceptedWork,
    CurrentReadGrant,
    acceptance_binds,
    acceptance_valid,
)
from nexus.company.management.operations import (
    LedgerSnapshot,
    LedgerUSD,
    ReportSnapshot,
    WorkProjection,
)
from nexus.company.management.plans import RunBinding
from nexus.execution.runtime_contracts import ExecutionState


class ReportScope(ManagementContract):
    access: PrincipalAccess
    company_report: Flag
    allowed_task_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    grants: tuple[CurrentReadGrant, ...] = Field(default=(), max_length=32)


class WorkLineage(ManagementContract):
    work: RunBinding
    parent_task_id: UUID | None
    root_task_id: UUID


class ChargeProjection(ManagementContract):
    charge_id: UUID
    task_id: UUID
    root_task_id: UUID
    amount_usd: LedgerUSD
    actual_usd: LedgerUSD | None
    state: Literal["held", "unknown", "reconciled"]
    issued: Flag
    required_resources: tuple[UUID, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def truthful_cost(self) -> Self:
        if (self.state == "reconciled") != (self.actual_usd is not None):
            raise ValueError("Only reconciled charges have an actual known amount")
        if self.state == "unknown" and not self.issued:
            raise ValueError("Unknown billing describes an issued or possibly issued call")
        if len(set(self.required_resources)) != len(self.required_resources):
            raise ValueError("Charge contributor resources must be unique")
        return self


class WorkReportFacts(ManagementContract):
    work: RunBinding
    execution_state: ExecutionState
    registered_active: Flag
    cancelled: Flag
    acceptance: AcceptedWork
    receipt: ActionReceipt | None
    verification_candidate: VerificationResult | None
    required_resources: tuple[UUID, ...] = Field(default=(), max_length=32)
    blockers: tuple[Name, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        require_company(
            self.company_id, self.work, self.acceptance, self.receipt, self.verification_candidate
        )
        if self.acceptance.work != self.work:
            raise ValueError("Report acceptance binds another immutable work identity")
        if self.receipt and (self.receipt.task_id, self.receipt.trace_id) != (
            self.work.task_id,
            self.work.trace_id,
        ):
            raise ValueError("Report receipt binds another work trace")
        return self


class ReportInput(ManagementContract):
    report_id: UUID
    scope: ReportScope
    period_start: AwareDatetime
    period_end: AwareDatetime
    observed_at: AwareDatetime
    ledger_source_sha256: SHA256
    lineage: tuple[WorkLineage, ...] = Field(min_length=1, max_length=101)
    work: tuple[WorkReportFacts, ...] = Field(default=(), max_length=100)
    charges: tuple[ChargeProjection, ...] = Field(default=(), max_length=1000)
    owner_decision_ids: tuple[UUID, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        require_company(
            self.company_id,
            self.scope,
            self.scope.access,
            *self.scope.grants,
            *self.lineage,
            *self.work,
            *self.charges,
            *(row.work for row in self.lineage),
        )
        if any(row.work.workspace_id != self.scope.access.workspace_id for row in self.lineage):
            raise ValueError("Report lineage belongs to another current workspace")
        if self.period_end <= self.period_start:
            raise ValueError("Operating report period must be ordered")
        if len({row.work.task_id for row in self.work}) != len(self.work):
            raise ValueError("Report logical work must be unique")
        return self


class OperatingProjection(ManagementContract):
    snapshot: ReportSnapshot
    actual_total_usd: LedgerUSD | None
    unknown_charge_ids: tuple[UUID, ...] = Field(default=(), max_length=1000)
    accepted_task_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    receipt_task_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    cancelled_task_ids: tuple[UUID, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def declared_uncertainty(self) -> Self:
        require_company(self.company_id, self.snapshot)
        if bool(self.unknown_charge_ids) != (self.actual_total_usd is None):
            raise ValueError("An unconfirmed charge cannot become a fabricated known total")
        if (
            self.actual_total_usd is not None
            and self.actual_total_usd != self.snapshot.ledger.spent_usd
        ):
            raise ValueError("Known total differs from its exact reconciled ledger")
        return self


def _lineage(rows: tuple[WorkLineage, ...]) -> dict[UUID, WorkLineage]:
    result = {row.work.task_id: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Report lineage must have unique immutable work")
    for row in rows:
        cursor, seen = row, set()
        while cursor.parent_task_id is not None:
            if cursor.work.task_id in seen or cursor.parent_task_id not in result:
                raise ValueError("Report ancestry is cyclic or missing")
            seen.add(cursor.work.task_id)
            cursor = result[cursor.parent_task_id]
        if cursor.work.task_id != row.root_task_id:
            raise ValueError("Reported root differs from actual ancestry")
    return result


def _authorized(facts: ReportInput) -> tuple[set[UUID], set[UUID]]:
    access = facts.scope.access
    require_capability(access, Capability.READ)
    owner = access.principal_id == access.owner_id and access.membership_role == "owner"
    if facts.scope.company_report and not owner:
        raise ValueError("Company totals require the actual current owner report scope")
    grants = {
        row.resource_id
        for row in facts.scope.grants
        if row.grant_active
        and row.resource_active
        and row.source_current
        and row.current_generation == row.expected_generation
        and (row.expires_at is None or row.expires_at > facts.observed_at)
    }
    tasks = {
        row.work.task_id
        for row in facts.work
        if (facts.scope.company_report or row.work.task_id in facts.scope.allowed_task_ids)
        and (owner or row.work.actor_id == access.principal_id)
        and set(row.required_resources) <= grants
    }
    return tasks, grants


def _charges(
    facts: ReportInput,
    lineage: dict[UUID, WorkLineage],
    tasks: set[UUID],
    grants: set[UUID],
) -> tuple[ChargeProjection, ...]:
    unique: dict[UUID, ChargeProjection] = {}
    for row in facts.charges:
        work = lineage.get(row.task_id)
        if work is None or row.root_task_id != work.root_task_id:
            raise ValueError("Charge belongs to an absent or incorrectly rooted work")
        previous = unique.get(row.charge_id)
        if previous is not None and previous != row:
            raise ValueError("Conflicting replay copies of one actual charge")
        unique[row.charge_id] = row
    return tuple(
        row
        for row in sorted(unique.values(), key=lambda row: row.charge_id)
        if row.task_id in tasks and set(row.required_resources) <= grants
    )


def _work_projection(row: WorkReportFacts, charges: tuple[ChargeProjection, ...]) -> WorkProjection:
    record = row.acceptance.publication.acceptance
    state = _acceptance_state(row)
    billing = "unconfirmed" if _unknown_billing(row, charges) else "known"
    return WorkProjection.model_validate(
        {
            "company_id": row.company_id,
            "work": row.work,
            "execution_state": row.execution_state,
            "registered_active": row.registered_active,
            "acceptance": state,
            "acceptance_id": record.acceptance_id if record else None,
            "billing": billing,
        }
    )


def _acceptance_state(row: WorkReportFacts) -> str:
    record = row.acceptance.publication.acceptance
    if record is None:
        return "pending"
    if row.acceptance.publication.invalidated or not acceptance_binds(row.acceptance):
        return "invalidated"
    if acceptance_valid(row.acceptance):
        return "accepted"
    return "rejected" if record.verdict == "reject" else "inconclusive"


def _unknown_billing(row: WorkReportFacts, charges: tuple[ChargeProjection, ...]) -> bool:
    own = tuple(value for value in charges if value.task_id == row.work.task_id)
    return bool(_unknown_ids((row,), own))


def _unknown_ids(
    rows: tuple[WorkReportFacts, ...], charges: tuple[ChargeProjection, ...]
) -> tuple[UUID, ...]:
    result = {
        value.charge_id
        for value in charges
        if value.state == "unknown" or (value.state == "held" and value.issued)
    }
    for row in rows:
        if row.receipt and not any(
            value.charge_id == row.receipt.action_id
            and value.task_id == row.work.task_id
            and value.state == "reconciled"
            for value in charges
        ):
            result.add(row.receipt.action_id)
    return tuple(sorted(result))


def project_report(facts: ReportInput) -> OperatingProjection:
    facts = ReportInput.model_validate_json(facts.model_dump_json())
    lineage = _lineage(facts.lineage)
    if any(
        lineage.get(row.work.task_id) is None or lineage[row.work.task_id].work != row.work
        for row in facts.work
    ):
        raise ValueError("Report work differs from its immutable lineage")
    tasks, grants = _authorized(facts)
    charges = _charges(facts, lineage, tasks, grants)
    rows = tuple(row for row in facts.work if row.work.task_id in tasks)
    unknown = _unknown_ids(rows, charges)
    spent = sum((row.actual_usd for row in charges if row.actual_usd is not None), Decimal(0))
    held = sum((row.amount_usd for row in charges if row.state != "reconciled"), Decimal(0))
    snapshot = ReportSnapshot(
        company_id=facts.company_id,
        report_id=facts.report_id,
        period_start=facts.period_start,
        period_end=facts.period_end,
        ledger=LedgerSnapshot(
            held_usd=held,
            spent_usd=spent,
            source_sha256=facts.ledger_source_sha256,
            observed_at=facts.observed_at,
        ),
        work=tuple(_work_projection(row, charges) for row in rows),
        blockers=tuple(dict.fromkeys(reason for row in rows for reason in row.blockers)),
        owner_decision_ids=facts.owner_decision_ids if facts.scope.company_report else (),
    )
    return OperatingProjection(
        company_id=facts.company_id,
        snapshot=snapshot,
        actual_total_usd=None if unknown else spent,
        unknown_charge_ids=unknown,
        accepted_task_ids=tuple(
            row.work.task_id for row in rows if acceptance_valid(row.acceptance)
        ),
        receipt_task_ids=tuple(row.work.task_id for row in rows if row.receipt is not None),
        cancelled_task_ids=tuple(row.work.task_id for row in rows if row.cancelled),
    )
