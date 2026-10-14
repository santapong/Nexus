"""Exact ID-only native wake pins and bounded deterministic state/bucket dedup recipe."""

from datetime import date, datetime
from typing import TypedDict
from uuid import UUID

from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.native_fact_contracts import (
    BlockedSelector,
    BlockedState,
    CapSelector,
    CompanyCapState,
    DecisionSelector,
    DecisionState,
    DigestSelector,
    DigestState,
    FailedReceiptSelector,
    NativeEventSelector,
    NativeFactProjection,
    WorkCapState,
)
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.management.canonical import canonical_sha256


class WakePins(TypedDict, total=False):
    action_id: UUID
    task_id: UUID
    report_id: UUID
    budget_day: date
    native_snapshot_sha256: str
    due_bucket: str
    scheduled_for: datetime
    notification_policy_sha256: str


def wake_pins(fact: NativeFactProjection) -> WakePins:
    selector, state = fact.selector, fact.state
    if isinstance(selector, FailedReceiptSelector):
        return {"action_id": selector.action_id}
    pins: WakePins = {"native_snapshot_sha256": fact.state_sha256}
    if isinstance(state, DigestState):
        pins["report_id"] = state.saved.report_id
        pins["due_bucket"] = state.due_bucket
        pins["scheduled_for"] = state.scheduled_for
        pins["notification_policy_sha256"] = canonical_sha256(state.registration.policy)
    elif isinstance(state, CompanyCapState):
        pins["budget_day"] = state.budget_day
    elif isinstance(state, (DecisionState, BlockedState, WorkCapState)):
        pins["task_id"] = state.work.task_id
        if isinstance(state, DecisionState):
            pins["action_id"] = state.action.proposal.action_id
    else:
        raise ValueError("Native wake state does not match its selector")
    return pins


def wake_key(fact: NativeFactProjection) -> str:
    if isinstance(fact.selector, FailedReceiptSelector):
        return f"native.receipt.failed.v1:{fact.selector.action_id}:{fact.state_sha256}"
    # Exact typed state includes company/subject and the digest's registered policy/bucket.
    return f"native.{fact.selector.kind}.v1:{fact.state_sha256}"


def matches_event(event: OutboxEvent, fact: NativeFactProjection) -> bool:
    return (
        event.kind == fact.selector.kind
        and event.resource == fact.resource
        and event.deduplication_key == wake_key(fact)
        and all(getattr(event, name) == value for name, value in wake_pins(fact).items())
    )


def event_selector(event: OutboxEvent, services: NativeFactServices) -> NativeEventSelector | None:
    company = event.company_id
    if event.kind == "decision_required" and event.action_id is not None:
        return DecisionSelector(company_id=company, action_id=event.action_id)
    if event.kind == "work_blocked" and event.task_id is not None:
        return BlockedSelector(company_id=company, task_id=event.task_id)
    if event.kind == "cap_exhausted":
        return CapSelector(company_id=company, task_id=event.task_id)
    if event.kind == "receipt_recorded" and event.action_id is not None:
        return FailedReceiptSelector(company_id=company, action_id=event.action_id)
    if event.kind == "digest_due":
        choices = tuple(
            row
            for row in services.digests
            if row.report_id == event.report_id
            and canonical_sha256(row.policy) == event.notification_policy_sha256
            and event.due_bucket is not None
            and event.due_bucket.startswith(f"{row.kind}:")
        )
        return (
            DigestSelector(company_id=company, schedule=choices[0].schedule)
            if len(choices) == 1
            else None
        )
    return None
