"""Native notification keys preserve exact event sequence and M1 intent identity."""

from sqlalchemy import UniqueConstraint

from nexus.company.brain.models import BrainBase
from nexus.execution.runtime_models import ExecutionBase


def test_event_sequence_link_has_exact_native_unique_target() -> None:
    table = BrainBase.metadata.tables["company_brain_events"]
    keys = {
        tuple(item.columns.keys())
        for item in table.constraints
        if isinstance(item, UniqueConstraint)
    }
    assert ("company_id", "event_id", "sequence") in keys


def test_notification_intent_link_has_complete_native_unique_target() -> None:
    table = ExecutionBase.metadata.tables["company_effect_intents"]
    keys = {
        tuple(item.columns.keys())
        for item in table.constraints
        if isinstance(item, UniqueConstraint)
    }
    assert (
        "company_id",
        "action_id",
        "task_id",
        "trace_id",
        "run_id",
        "intent_fence",
        "attempt_kind",
        "proposal_hash",
    ) in keys
