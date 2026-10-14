"""Native author multiplicity is rejected before any source/hash candidate can be selected."""

from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.engineering_pair_selection import unique_author_action
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import JournalAction
from nexus.tests.engineering_check_support import check_input


class Rows:
    """Minimal SQL result adapter exposes actual ORM records for query-boundary negatives."""

    def __init__(self, rows: list[tuple[EffectIntent, JournalAction | None]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[EffectIntent, JournalAction | None]]:
        return self.rows


@pytest.mark.parametrize("kind", ["none", "multiple", "missing_journal", "foreign_tool"])
async def test_author_identity_not_filtered_to_passing_candidate(kind: str) -> None:
    value = check_input()
    job = value.author.spec.job
    work = ExecutionWork(company_id=job.company_id, task_id=job.task_id, run_id=job.run_id)
    effect = EffectIntent(action_id=job.action_id)
    action = JournalAction(
        company_id=job.company_id,
        proposal_json=ActionProposal(
            company_id=job.company_id,
            action_id=job.action_id,
            task_id=job.task_id,
            trace_id=job.trace_id,
            actor_id=job.actor_id,
            revision=1,
            tool="company.report.write.v1",
            tool_version="v1",
            resource=job.resource_symbol,
            parameters={},
            policy_version="fixture-policy",
            price_version="fixture-prices",
            estimated_cost_usd=Decimal("0.01"),
        ).model_dump_json(),
    )
    # Missing/multiple rows must fail before decoding any possibly malformed candidate.
    rows: list[tuple[EffectIntent, JournalAction | None]] = []
    if kind == "multiple":
        rows = [(effect, action), (EffectIntent(action_id=UUID(int=99)), action)]
    elif kind == "missing_journal":
        rows = [(effect, None)]
    elif kind == "foreign_tool":
        rows = [(effect, action)]
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = Rows(rows)
    with pytest.raises(ValueError):
        await unique_author_action(session, work)
