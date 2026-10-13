"""Pure deterministic read projections; eligibility is never an effect/enqueue permit."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.brain.base import Flag, Name, require_company
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import VerificationSpec, WorkAcceptance
from nexus.company.management.base import SHA256, ManagementContract, RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import DueIntent, GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.operations import (
    Eligibility,
    EligibilityReason,
    EligibilityState,
    LedgerUSD,
)
from nexus.company.management.plans import RunBinding, VerificationIntent
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionState


class PublishedAcceptance(ManagementContract):
    """Facts from a trusted current acceptance/proof store, never a decoded verdict."""

    acceptance: WorkAcceptance | None
    trusted_proofs_resolved: Flag
    invalidated: Flag


class AcceptedWork(ManagementContract):
    work: RunBinding
    work_snapshot_sha256: SHA256
    criterion_ids: tuple[Name, ...] = Field(min_length=1, max_length=32)
    publication: PublishedAcceptance

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        require_company(self.company_id, self.work, self.publication, self.publication.acceptance)
        if len(set(self.criterion_ids)) != len(self.criterion_ids):
            raise ValueError("Acceptance criteria must be unique")
        return self


class ManagementVersions(ManagementContract):
    mandate: RevisionRef
    goal: GoalRevisionRef
    plan: PlanRevisionRef
    charter: CharterRevisionRef
    work_snapshot_sha256: SHA256

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        require_company(self.company_id, self.mandate, self.goal, self.plan, self.charter)
        return self


class CurrentReadGrant(ManagementContract):
    resource_id: UUID
    expected_generation: int = Field(ge=1, strict=True)
    current_generation: int = Field(ge=1, strict=True)
    resource_active: Flag
    grant_active: Flag
    expires_at: AwareDatetime | None
    source_current: Flag


class VerificationTrigger(ManagementContract):
    intent: VerificationIntent
    author: RunBinding
    author_work_sha256: SHA256
    resolved: VerificationSpec | None
    receipt: ActionReceipt | None
    protected_artifacts_available: Flag

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        require_company(self.company_id, self.intent, self.author, self.resolved, self.receipt)
        return self


class EligibilityFacts(ManagementContract):
    """Server-selected fresh facts; root must recheck them in the enqueue transaction."""

    work: RunBinding
    current_work: RunBinding
    expected: ManagementVersions
    current: ManagementVersions | None
    execution_state: ExecutionState
    plan_approved: Flag
    mandate_active: Flag
    scope_available: Flag
    registered_active: Flag
    ancestors_active: Flag
    company_paused: Flag
    cancelled: Flag
    approval_satisfied: Flag
    billing_known: Flag
    already_scheduled: Flag
    available_usd: LedgerUSD
    required_usd: LedgerUSD
    remaining_attempts: AttemptQuota
    required_attempts: AttemptQuota
    grants: tuple[CurrentReadGrant, ...] = Field(default=(), max_length=32)
    own_acceptance: AcceptedWork
    dependencies: tuple[AcceptedWork, ...] = Field(default=(), max_length=100)
    verification: VerificationTrigger | None = None
    due: DueIntent | None = None

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        require_company(
            self.company_id,
            self.work,
            self.current_work,
            self.expected,
            self.current,
            self.own_acceptance,
            self.verification,
            *self.grants,
            *self.dependencies,
        )
        if self.own_acceptance.work != self.work:
            raise ValueError("Own acceptance projection belongs to another immutable work binding")
        if self.own_acceptance.work_snapshot_sha256 != self.expected.work_snapshot_sha256:
            raise ValueError("Own acceptance projection belongs to another selected work snapshot")
        if len({row.work.task_id for row in self.dependencies}) != len(self.dependencies):
            raise ValueError("Dependencies must be unique")
        if len({row.resource_id for row in self.grants}) != len(self.grants):
            raise ValueError("Source/resource grants must be unique")
        return self


def acceptance_valid(facts: AcceptedWork) -> bool:
    facts = AcceptedWork.model_validate_json(facts.model_dump_json())
    record = facts.publication.acceptance
    return bool(
        record
        and facts.publication.trusted_proofs_resolved
        and not facts.publication.invalidated
        and record.verdict == "pass"
        and record.proofs
        and acceptance_binds(facts)
    )


def acceptance_binds(facts: AcceptedWork) -> bool:
    record = facts.publication.acceptance
    return bool(
        record
        and record.target.author == facts.work
        and record.target.work_snapshot_sha256 == facts.work_snapshot_sha256
        and record.target.criterion_ids == facts.criterion_ids
    )


def _verification_ready(trigger: VerificationTrigger, work: RunBinding) -> bool:
    spec, receipt = trigger.resolved, trigger.receipt
    return bool(
        spec
        and receipt
        and trigger.protected_artifacts_available
        and spec.author == trigger.author
        and spec.verifier == work
        and spec.work_snapshot_sha256 == trigger.author_work_sha256
        and trigger.intent.author_task_id == spec.author.task_id
        and trigger.intent.verifier_task_id == work.task_id
        and trigger.intent.check_recipe == spec.check_recipe
        and receipt.company_id == work.company_id
        and receipt.action_id == spec.action_id
        and (receipt.task_id, receipt.trace_id) == (spec.author.task_id, spec.author.trace_id)
        and receipt.receipt_id == spec.receipt_id
        and receipt.proposal_hash == spec.proposal_sha256
        and canonical_sha256(receipt) == spec.receipt_sha256
        and {(row.artifact_id, row.revision, row.sha256) for row in spec.artifacts}
        <= {(row.artifact_id, row.revision, row.sha256) for row in receipt.artifacts}
        and receipt.outcome in {"succeeded", "failed"}
    )


def evaluate_work(facts: EligibilityFacts, as_of: datetime) -> Eligibility:
    facts = EligibilityFacts.model_validate_json(facts.model_dump_json())
    if as_of.utcoffset() is None:
        raise ValueError("Eligibility needs a server-observed aware timestamp")
    state, reason = _reason(facts, as_of)
    return Eligibility(
        company_id=facts.company_id,
        work=facts.work,
        plan=facts.expected.plan,
        state=state,
        reason=reason,
    )


def _reason(facts: EligibilityFacts, as_of: datetime) -> tuple[EligibilityState, EligibilityReason]:
    if facts.cancelled:
        return "cancelled", "work_cancelled"
    if not (facts.scope_available and facts.registered_active and facts.ancestors_active):
        return "blocked", "scope_unavailable"
    if facts.company_paused:
        return "blocked", "company_paused"
    if not facts.mandate_active:
        return "blocked", "mandate_revoked"
    if facts.current != facts.expected or facts.current_work != facts.work:
        return "blocked", "versions_stale"
    if any(
        not (row.resource_active and row.grant_active and row.source_current)
        or row.current_generation != row.expected_generation
        or (row.expires_at is not None and row.expires_at <= as_of)
        for row in facts.grants
    ):
        return "blocked", "source_unavailable"
    if facts.execution_state == "outcome_unknown":
        return "blocked", "outcome_unknown"
    if not facts.billing_known:
        return "blocked", "billing_unknown"
    if facts.execution_state == "blocked":
        return "blocked", "scope_unavailable"
    return _readiness(facts, as_of)


def _readiness(
    facts: EligibilityFacts, as_of: datetime
) -> tuple[EligibilityState, EligibilityReason]:
    if acceptance_valid(facts.own_acceptance):
        return "waiting", "already_accepted"
    if (
        not (facts.plan_approved and facts.approval_satisfied)
        or facts.execution_state == "awaiting_approval"
    ):
        return "waiting", "approval_pending"
    if facts.already_scheduled or facts.execution_state in {"running", "verifying"}:
        return "waiting", "dispatch_active"
    if facts.available_usd < facts.required_usd or any(
        getattr(facts.remaining_attempts, name) < getattr(facts.required_attempts, name)
        for name in AttemptQuota.model_fields
    ):
        return "blocked", "budget_exhausted"
    if facts.due is not None and (
        facts.due.actionable_at is None or facts.due.actionable_at > as_of
    ):
        return "waiting", "due_pending"
    if not all(acceptance_valid(row) for row in facts.dependencies):
        return "waiting", "dependency_unaccepted"
    if facts.verification is not None:
        return (
            ("eligible", "verification_result_available")
            if _verification_ready(facts.verification, facts.work)
            else ("waiting", "verification_unbound")
        )
    return "eligible", "ready"


def evaluate_graph(facts: tuple[EligibilityFacts, ...], as_of: datetime) -> tuple[Eligibility, ...]:
    if not 0 < len(facts) <= 100:
        raise ValueError("A management scan requires 1-100 exact work projections")
    nodes = {row.work.task_id: row for row in facts}
    if len(nodes) != len(facts) or len({(row.company_id, row.expected.plan) for row in facts}) != 1:
        raise ValueError("Management graph must have unique work in one company/plan")
    pending = {
        key: {row.work.task_id for row in value.dependencies} for key, value in nodes.items()
    }
    for key, value in nodes.items():
        if value.verification:
            pending[key].add(value.verification.intent.author_task_id)
    if any(not dependencies <= nodes.keys() for dependencies in pending.values()):
        raise ValueError("Management graph references absent work")
    for value in nodes.values():
        if any(
            row.work != nodes[row.work.task_id].current_work
            or row.work_snapshot_sha256
            != nodes[row.work.task_id].own_acceptance.work_snapshot_sha256
            or row.criterion_ids != nodes[row.work.task_id].own_acceptance.criterion_ids
            for row in value.dependencies
        ):
            raise ValueError("Management graph has inconsistent dependency binding")
        trigger = value.verification
        if trigger and (
            trigger.author != nodes[trigger.intent.author_task_id].current_work
            or trigger.author_work_sha256
            != nodes[trigger.intent.author_task_id].expected.work_snapshot_sha256
        ):
            raise ValueError("Management graph has inconsistent verification author binding")
    while pending:
        ready = {key for key, dependencies in pending.items() if not dependencies}
        if not ready:
            raise ValueError("Management dependencies and verification triggers form a cycle")
        pending = {
            key: dependencies - ready for key, dependencies in pending.items() if key not in ready
        }
    return tuple(evaluate_work(nodes[key], as_of) for key in sorted(nodes))
