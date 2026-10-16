"""Path-free whole-family financial data; none of these values authorizes a read or effect."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import SourceHead
from nexus.company.contracts.base import USD
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.base import SHA256, ManagementContract, Name, ValueContract
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_model_facts import CycleModelFact
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.planning_prepared_contracts import PlanningPreparedDescriptor
from nexus.execution.runtime_contracts import EffectRecord, ExecutionSnapshot
from nexus.execution.runtime_models import ExecutionAttempt
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CostHold

if TYPE_CHECKING:
    from nexus.company.management.cycle_coding_sources import CodingCostProof

MAX_FAMILY_ROWS, MAX_CHARGES, SNAPSHOT_LIMIT = 1000, 1000, 2_097_152


class FamilyCharge(ValueContract):
    action_id: UUID
    task_id: UUID
    attempt_kind: Name
    native_state: Name | None
    hold_state: Name | None
    reserved_usd: USD | None
    ledger_actual_usd: USD | None
    receipt_id: UUID | None
    day: date | None = None
    confirmation: Literal["known", "unconfirmed", "unissued"]
    blockers: tuple[Name, ...] = Field(default=(), max_length=32)
    model_fact: CycleModelFact | None = None

    @model_validator(mode="after")
    def truthful_confirmation(self) -> Self:
        if self.confirmation == "known" and (
            self.blockers
            or self.hold_state != "reconciled"
            or self.ledger_actual_usd is None
            or self.native_state not in {"succeeded", "failed"}
            or self.receipt_id is None
            or (
                self.attempt_kind == "model_requests"
                and (
                    self.model_fact is None
                    or self.model_fact.billing != "known"
                    or self.model_fact.ledger_actual_usd != self.ledger_actual_usd
                    or (self.model_fact.action_id, self.model_fact.task_id)
                    != (self.action_id, self.task_id)
                )
            )
        ):
            raise ValueError("Confirmed family cost lacks exact native/model proof")
        if self.confirmation == "unconfirmed" and not self.blockers:
            raise ValueError("Unconfirmed family cost needs explicit blockers")
        if self.confirmation == "unissued" and (
            self.native_state is not None or self.ledger_actual_usd is not None
        ):
            raise ValueError("Issued/reconciled work cannot be labelled unissued")
        return self


class FamilyChargeTotals(ValueContract):
    action_count: int = Field(ge=0, le=MAX_CHARGES, strict=True)
    known_spent_usd: USD
    held_usd: USD | None
    actual_total_usd: USD | None
    unconfirmed_action_ids: tuple[UUID, ...] = Field(max_length=MAX_CHARGES)


def family_charge_totals(charges: tuple[FamilyCharge, ...]) -> FamilyChargeTotals:
    if len(charges) > MAX_CHARGES:
        raise ValueError("Whole-family charge bound exceeded")
    unique: dict[UUID, FamilyCharge] = {}
    for supplied in charges:
        row = FamilyCharge.model_validate_json(supplied.model_dump_json())
        if row.action_id in unique and unique[row.action_id] != row:
            raise ValueError("Conflicting duplicate family charge")
        unique[row.action_id] = row
    rows = tuple(unique.values())
    unknown = tuple(
        sorted(
            row.action_id
            for row in rows
            if row.confirmation == "unconfirmed" or row.hold_state in {"held", "unknown"}
        )
    )
    spent = sum(
        (row.ledger_actual_usd or Decimal(0) for row in rows if row.hold_state == "reconciled"),
        Decimal(0),
    )
    held = (
        None
        if any(row.confirmation == "unconfirmed" and row.hold_state is None for row in rows)
        else sum(
            (
                row.reserved_usd or Decimal(0)
                for row in rows
                if row.hold_state in {"held", "unknown"}
            ),
            Decimal(0),
        )
    )
    return FamilyChargeTotals(
        action_count=len(rows),
        known_spent_usd=spent,
        held_usd=held,
        actual_total_usd=None if unknown else spent,
        unconfirmed_action_ids=unknown,
    )


class CycleCostSnapshot(ManagementContract):
    basis: Literal["registered_family_lifetime"] = "registered_family_lifetime"
    goal: GoalRevisionRef
    root_task_id: UUID
    procedure_id: UUID
    admission_sha256: SHA256
    observed_at: AwareDatetime
    profile_bound: bool = Field(strict=True)
    complete_membership: bool = Field(strict=True)
    expected_task_ids: tuple[UUID, ...] = Field(min_length=11, max_length=11)
    observed_task_ids: tuple[UUID, ...] = Field(max_length=MAX_FAMILY_ROWS)
    missing_task_ids: tuple[UUID, ...] = Field(max_length=MAX_FAMILY_ROWS)
    extra_task_ids: tuple[UUID, ...] = Field(max_length=MAX_FAMILY_ROWS)
    mismatched_task_ids: tuple[UUID, ...] = Field(max_length=MAX_FAMILY_ROWS)
    unissued_task_ids: tuple[UUID, ...] = Field(max_length=MAX_FAMILY_ROWS)
    charges: tuple[FamilyCharge, ...] = Field(max_length=MAX_CHARGES)
    totals: FamilyChargeTotals
    blockers: tuple[Name, ...] = Field(max_length=32)
    company_completed: Literal[False] = False

    @model_validator(mode="after")
    def exact_membership_and_money(self) -> Self:
        expected, observed = set(self.expected_task_ids), set(self.observed_task_ids)
        totals = family_charge_totals(self.charges)
        if not self.complete_membership or self.blockers:
            totals = totals.model_copy(update={"actual_total_usd": None})
        if (
            len(expected) != 11
            or len(observed) != len(self.observed_task_ids)
            or set(self.missing_task_ids) != expected - observed
            or set(self.extra_task_ids) != observed - expected
            or self.complete_membership
            != (self.profile_bound and expected == observed and not self.mismatched_task_ids)
            or self.totals != totals
        ):
            raise ValueError("Financial snapshot membership or charge projection differs")
        return self


@dataclass(frozen=True, slots=True)
class CycleCostRead:
    value: CycleCostSnapshot
    read_end_us: int


class DirectoryCostWork(ManagementContract):
    """Internal copied native metadata, never an accepted registered row or permit."""

    task_id: UUID
    trace_id: UUID
    actor_id: UUID
    workspace_id: UUID
    parent_task_id: UUID | None
    root_task_id: UUID
    allocation_usd: USD
    delegated_usd: USD
    active: bool
    work: ExecutionSnapshot | None

    def directory_data(self) -> RegisteredWork:
        return RegisteredWork(**self.model_dump(exclude={"work", "schema_version"}))


class NativeCostHold(ManagementContract):
    action_id: UUID
    task_id: UUID
    day: date
    amount_usd: USD
    actual_usd: USD | None
    state: Name

    def native_data(self) -> CostHold:
        return CostHold(**self.model_dump(exclude={"schema_version"}))


class NativeCostAttempt(ManagementContract):
    task_id: UUID
    trace_id: UUID
    attempt_id: UUID
    kind: Name
    fence: int = Field(gt=0, strict=True)
    reserved_at: AwareDatetime

    def native_data(self) -> ExecutionAttempt:
        return ExecutionAttempt(**self.model_dump(exclude={"schema_version"}))


class NativeCostSelection(ValueContract):
    directory: DirectoryCostWork
    action: ActionRecord
    hold: NativeCostHold | None
    intent: EffectRecord | None
    attempt: NativeCostAttempt | None


class FamilyCostCapture(ValueContract):
    observed_at: AwareDatetime
    owner_id: UUID
    control_policy: Name
    control_prices: Name
    control_paused: bool
    profile_bound: bool
    works: tuple[DirectoryCostWork, ...] = Field(max_length=MAX_FAMILY_ROWS)
    selections: tuple[NativeCostSelection, ...] = Field(max_length=MAX_CHARGES)
    orphan_holds: tuple[NativeCostHold, ...] = Field(max_length=MAX_CHARGES)
    orphan_effects: tuple[EffectRecord, ...] = Field(default=(), max_length=MAX_CHARGES)
    native_budget_sha256: SHA256 | None = None
    blockers: tuple[Name, ...] = Field(max_length=32)


class HistoricalCostSources(ValueContract):
    grants: tuple[ResourceGeneration, ...]
    heads: tuple[SourceHead, ...]
    policies: tuple[SourcePolicy, ...]


class NativeBudgetSignature(ValueContract):
    values: tuple[tuple[UUID, USD | None, USD | None], ...]


def family_capture_signature(captured: FamilyCostCapture) -> str:
    """Ignore only observation time in native equality; never change an authorization clock."""
    normalized = captured.model_copy(update={"observed_at": datetime(1970, 1, 1, tzinfo=UTC)})
    return canonical_sha256(normalized)


@dataclass(frozen=True, slots=True)
class ModelSourceProof:
    """Actual retained read metadata; every consumer must requery current authority."""

    selection: NativeCostSelection
    header: PlanningPreparedDescriptor | None
    signature: str
    coding: CodingCostProof | None = None


@dataclass(frozen=True, slots=True)
class ModelCostRead:
    fact: CycleModelFact | None
    blockers: tuple[str, ...]
    read_end_us: int
    source_signature: str | None = None
    proof: ModelSourceProof | None = None
