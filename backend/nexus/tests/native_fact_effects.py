"""Actual native issued fixture outcome; no output, acceptance, provider or OS process claim."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.tests.generated_artifact_fixture import ledger
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.native_profile_support import ProfileScenario


async def issued_fixture_action(
    factory: async_sessionmaker[AsyncSession],
    case: ProfileScenario,
) -> tuple[ActionProposal, ExecutionLease]:
    bound = case.payload.children[0].binding
    action = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        revision=1,
        tool="fake.internal.read.v1",
        tool_version="v1",
        resource="company.report",
        parameters={"operation": "fixture-read"},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.2"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(action, ledger(bound))
    await journal.approve_registered(
        ledger(bound).model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        ledger(bound), action.action_id, datetime.now(UTC), (), identity=identity(bound.actor_id)
    )
    lease = await case.native.execution.claim(
        ledger(bound), identity(bound.actor_id), uuid4(), ttl_seconds=60
    )
    await case.native.effects.begin(lease, identity(bound.actor_id), action.action_id)
    return action, lease


def fixture_receipt(action: ActionProposal, *, outcome: str = "failed") -> ActionReceipt:
    return ActionReceipt.model_validate(
        {
            "company_id": COMPANY,
            "receipt_id": uuid4(),
            "action_id": action.action_id,
            "task_id": action.task_id,
            "trace_id": action.trace_id,
            "proposal_hash": action_hash(action),
            "outcome": outcome,
            "recorded_at": datetime.now(UTC),
        }
    )
