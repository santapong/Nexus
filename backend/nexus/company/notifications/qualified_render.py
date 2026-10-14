"""Actual native deterministic owner drafts; no model, completion inference or transport."""

from datetime import datetime
from uuid import uuid5

from nexus.company.access import CompanyControlScope
from nexus.company.brain.native_fact_contracts import (
    BlockedState,
    CompanyCapState,
    DecisionState,
    DigestState,
    WorkCapState,
)
from nexus.company.management.base import require_company
from nexus.company.notifications.contracts import (
    NotificationDraft,
    NotificationPayload,
    NotificationPolicy,
    OwnerRecipientPolicy,
)
from nexus.company.notifications.native_facts import (
    NativeNotificationFact,
    NotificationUnavailableError,
    render_native_draft,
)
from nexus.company.notifications.policy import signal_admission, trigger_sha256
from nexus.company.notifications.qualified_facts import QualifiedNotificationFact


def render_qualified_draft(
    scope: CompanyControlScope,
    policy: NotificationPolicy,
    recipient: OwnerRecipientPolicy,
    fact: NativeNotificationFact,
    now: datetime,
) -> NotificationDraft:
    if not isinstance(fact, QualifiedNotificationFact):
        return render_native_draft(scope, policy, recipient, fact, now)
    require_company(scope.company_id, recipient, fact, fact.native_state)
    if signal_admission(policy, fact.signal).state != "eligible":
        raise NotificationUnavailableError("Native notification is not currently eligible")
    subject, details = _content(fact)
    source = fact.signal.source_event
    text = "\n".join(
        (
            subject,
            f"Native subject: {fact.signal.subject_id}",
            f"Source date ({source.precision}): {source.value or 'unknown'}",
            f"Observed: {now.isoformat()}",
            *details,
            "Open the authenticated company dashboard to inspect or decide.",
            "This message grants no approval, budget or execution authority.",
        )
    )
    payload = NotificationPayload(
        sender=recipient.sender, recipient=recipient.recipient, subject=subject, text=text
    )
    digest = fact.signal.digest
    trigger = trigger_sha256(fact.signal)
    return NotificationDraft(
        company_id=scope.company_id,
        draft_id=uuid5(scope.company_id, f"owner-notify:{trigger}"),
        trigger_sha256=trigger,
        signal=fact.signal,
        recipient_policy=recipient,
        policy_version=policy.version,
        template_version=policy.template_version,
        payload=payload,
        payload_sha256=payload.sha256,
        provenance=fact.provenance,
        operation_id=scope.operation_id,
        audit_trace_id=scope.trace_id,
        recorded_at=now,
        kind=digest.kind if digest else "routine",
        due_bucket=digest.due_bucket if digest else None,
        scheduled_for=digest.scheduled_for if digest else None,
    )


def _content(fact: QualifiedNotificationFact) -> tuple[str, tuple[str, ...]]:
    state = fact.native_state
    if isinstance(state, DecisionState):
        return "Owner decision required", (
            f"Task: {state.work.task_id}",
            f"Tool: {state.action.proposal.tool} {state.action.proposal.tool_version}",
            "Decision: not yet recorded",
        )
    if isinstance(state, BlockedState):
        cancellation = state.cancellation
        return "Work blocked", (
            f"State: {state.eligibility.state}",
            f"Reason: {state.eligibility.reason}",
            f"Permanent owner cancellation: {cancellation.cancellation.reason}"
            if cancellation
            else "No explicit owner cancellation",
        )
    if isinstance(state, (CompanyCapState, WorkCapState)):
        return "Allowance exhausted", (
            f"Cap USD: {state.cap_usd:.6f}",
            f"Held USD: {state.held_usd:.6f}",
            f"Spent USD: {state.spent_usd:.6f}",
            f"Billing: {'unknown' if state.billing_unknown else 'known'}",
            f"Delegated USD: {state.delegated_usd:.6f}"
            if isinstance(state, WorkCapState)
            else f"Bangkok budget day: {state.budget_day}",
        )
    if isinstance(state, DigestState):
        report = state.saved
        projection = report.projection
        actual = (
            "unknown"
            if projection.actual_total_usd is None
            else f"{projection.actual_total_usd:.6f}"
        )
        return f"{state.registration.kind.title()} operating digest", (
            f"Report: {report.report_id}",
            f"Bucket: {state.due_bucket}",
            f"Original observed: {report.observed_at.isoformat()}",
            f"Independently accepted tasks: {len(projection.accepted_task_ids)}",
            f"Receipt tasks: {len(projection.receipt_task_ids)}",
            f"Held USD: {projection.snapshot.ledger.held_usd:.6f}",
            f"Spent USD: {projection.snapshot.ledger.spent_usd:.6f}",
            f"Actual total USD: {actual}",
            f"Unknown charges: {len(projection.unknown_charge_ids)}",
            "Receipts, independent acceptance, billing and goal outcome remain separate.",
        )
    raise NotificationUnavailableError("Native notification state is unsupported")
