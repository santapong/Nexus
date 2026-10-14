"""Read retained drill facts through exact native company scope; no operational writes or seeds."""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from pydantic import AwareDatetime, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.base import SHA256, ValueContract
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.harness.journal_models import CostHold


class RecoveryDrillEvidence(ValueContract):
    """Measured local data/replay facts do not assert storage independence or service recovery."""

    source_database: str
    target_database: str
    workflow_id: str
    metadata_sha256: SHA256
    captured_at: AwareDatetime
    completed_at: AwareDatetime
    snapshot_age_seconds: float = Field(ge=0)
    capture_seconds: float = Field(ge=0)
    data_restore_seconds: float = Field(ge=0)
    target_replay_seconds: float = Field(ge=0)
    source_unchanged: bool
    old_fence_denied: bool
    no_reissue: bool


@dataclass(frozen=True)
class RecoveryFacts:
    """Conservation fields describe actual stored rows before and after target replay."""

    database: str
    intent_fence: int
    intent_state: str
    receipt_json: str | None
    attempt_ids: tuple[UUID, ...]
    model_requests: int
    tool_attempts: int
    current_fence: int
    segment_id: UUID | None
    hold_usd: Decimal
    actual_usd: Decimal | None
    hold_state: str
    dispatch_json: str


async def recovery_facts(
    factory: async_sessionmaker[AsyncSession], company: UUID, task: UUID, action: UUID
) -> RecoveryFacts:
    """Restricted connection names its actual database and exact company/task/action records."""
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('nexus.company_id', :cid, true)"), {"cid": str(company)}
        )
        work = await session.get(ExecutionWork, (company, task))
        intent = await session.get(EffectIntent, (company, action))
        hold = await session.get(CostHold, action)
        dispatch = await session.get(SegmentDispatch, (company, action))
        attempts = tuple(
            (
                await session.scalars(
                    select(ExecutionAttempt.attempt_id)
                    .where(ExecutionAttempt.company_id == company, ExecutionAttempt.task_id == task)
                    .order_by(ExecutionAttempt.attempt_id)
                )
            ).all()
        )
        assert work is not None and intent is not None and hold is not None and dispatch is not None
        database = await session.scalar(text("SELECT current_database()"))
        assert isinstance(database, str)
        return RecoveryFacts(
            database,
            intent.intent_fence,
            intent.state,
            intent.receipt_json,
            attempts,
            work.model_requests_used,
            work.tool_attempts_used,
            work.fence,
            work.segment_id,
            hold.amount_usd,
            hold.actual_usd,
            hold.state,
            dispatch.binding_json,
        )


def assert_unknown_conserved(before: RecoveryFacts, after: RecoveryFacts) -> None:
    """A fresh fence may change; original intent, lifetime attempts and unknown money may not."""
    assert before.intent_fence == after.intent_fence
    assert before.attempt_ids == after.attempt_ids and len(after.attempt_ids) == 1
    assert before.model_requests == after.model_requests == 0
    assert before.tool_attempts == after.tool_attempts == 1
    assert before.segment_id == after.segment_id
    assert before.dispatch_json == after.dispatch_json
    assert before.hold_usd == after.hold_usd and after.hold_usd > 0
    assert before.actual_usd is after.actual_usd is None
    assert before.hold_state == after.hold_state == "unknown"
    assert before.intent_state == after.intent_state == "outcome_unknown"
    assert before.receipt_json is after.receipt_json is None
    assert after.current_fence > before.current_fence


def assert_no_issuance_phases(root: Path) -> None:
    """Unknown replay invokes no native publication, receipt or acceptance step."""
    path = root / "phases.jsonl"
    assert not path.exists() or path.read_text() == ""
