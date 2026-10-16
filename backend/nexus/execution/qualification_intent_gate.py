"""Mandatory original qualification composition at the native fresh-permit boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.core.llm.qualification_contracts import PROFILE, TOOL, WORKFLOW
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.runtime_contracts import AttemptKind, ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import JournalAction

if TYPE_CHECKING:
    from nexus.execution.effect_store import EffectStore

DENIED = "Fresh qualification intent requires its exact original native check"


def _markers(work: ExecutionWork, proposal: ActionProposal) -> tuple[str, str, str]:
    return work.workflow_name, work.model_profile, proposal.tool


def _reserved(markers: tuple[str, str, str]) -> bool:
    return any(
        actual == expected
        for actual, expected in zip(markers, (WORKFLOW, PROFILE, TOOL), strict=True)
    )


def _work_pin(work: ExecutionWork) -> tuple[object, ...]:
    return (
        work.company_id,
        work.task_id,
        work.trace_id,
        work.actor_id,
        work.workspace_id,
        work.run_id,
        work.workflow_name,
        work.workflow_version,
        work.model_profile,
        work.model_registry_version,
        work.registration_json,
        work.registration_hash,
        work.fence,
        work.worker_id,
        work.segment_id,
        work.lease_mode,
        work.lease_principal_id,
        *(
            getattr(work, f"{kind}_limit")
            for kind in ("model_requests", "tool_attempts", "rework_rounds", "plan_revisions")
        ),
    )


def _action_pin(action: JournalAction) -> tuple[object, ...]:
    return (
        action.id,
        action.company_id,
        action.task_id,
        action.trace_id,
        action.proposal_json,
        action.proposal_hash,
        action.approval_json,
        action.consumed_at,
    )


@dataclass(frozen=True, slots=True)
class QualificationIntentGate:
    """Derived from original native objects, never a serialized flag or call permission."""

    _factory: async_sessionmaker[AsyncSession]
    _effects: EffectStore
    _lease: ExecutionLease
    _identity: VerifiedIdentity
    _check: BeforeIntentCheck | None
    _kind: AttemptKind
    _markers: tuple[str, str, str]
    _work: tuple[object, ...]
    _action: tuple[object, ...]

    def require_current(
        self, work: ExecutionWork, action: JournalAction, check: BeforeIntentCheck | None
    ) -> None:
        """Retain original mode and full binding across awaited checks and final flush."""
        from nexus.harness.qualification_intent import QualificationIntentCheck

        try:
            proposal = ActionProposal.model_validate_json(action.proposal_json)
            current = _markers(work, proposal)
            if not _reserved(self._markers) and not _reserved(current):
                return
            if (
                self._markers != (WORKFLOW, PROFILE, TOOL)
                or current != self._markers
                or self._kind != "model_requests"
                or check is not self._check
                or type(check) is not QualificationIntentCheck
                or self._effects._factory is not self._factory
                or _work_pin(work) != self._work
                or _action_pin(action) != self._action
                or action.proposal_hash != action_hash(proposal)
            ):
                raise ExecutionDeniedError(DENIED)
            QualificationIntentCheck.require_gate_binding(
                check, self._factory, self._effects, self._lease, self._identity, proposal
            )
        except (ValueError, AttributeError, TypeError) as error:
            raise ExecutionDeniedError(DENIED) from error


def bind_qualification_intent_check(
    factory: async_sessionmaker[AsyncSession],
    effects: EffectStore,
    work: ExecutionWork,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action: JournalAction,
    kind: AttemptKind,
    before_intent: BeforeIntentCheck | None,
) -> QualificationIntentGate:
    """Capture before any await/mutation after known-issued replay has already returned."""
    try:
        proposal = ActionProposal.model_validate_json(action.proposal_json)
        gate = QualificationIntentGate(
            factory,
            effects,
            ExecutionLease.model_validate_json(lease.model_dump_json()),
            VerifiedIdentity.model_validate(identity.model_dump()),
            before_intent,
            kind,
            _markers(work, proposal),
            _work_pin(work),
            _action_pin(action),
        )
        gate.require_current(work, action, before_intent)
        return gate
    except (ValueError, AttributeError, TypeError) as error:
        raise ExecutionDeniedError(DENIED) from error
