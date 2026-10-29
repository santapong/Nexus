"""Two mocked providers cannot issue an already held request over the company cap."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.company.contracts.results import ActionReceipt
from nexus.execution.effect_store import EffectStore
from nexus.execution.qualification_service import QualificationPreparationService
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.qualification_client import QualificationClient
from nexus.harness.qualification_evidence import FileQualificationEvidenceStore
from nexus.tests.integration import test_company_model_qualification as existing
from nexus.tests.integration.n5_qualification_fixture import (
    CountedResolver,
    Namespace,
    approve_and_authorize,
    disposable_factory,
    known_call,
    make_goal,
    prepare_overbill,
    snapshot,
)


@pytest.fixture
async def isolated_factory() -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], Namespace]]:
    async with disposable_factory("nexus_company_test_model_cap") as value:
        yield value


async def test_two_provider_cap_denies_previously_held_request(
    isolated_factory: tuple[async_sessionmaker[AsyncSession], Namespace], tmp_path: Path
) -> None:
    factory, ns = isolated_factory
    reference = await make_goal(factory, ns, tmp_path)
    started_day = (await snapshot(factory, ns)).day
    recipes = await existing.recipes(reference)
    service = QualificationPreparationService(factory, recipes)
    prepared = tuple(
        [
            await service.prepare_qualification(ns.control("prepare"), ns.identity(), r.recipe_id)
            for r in recipes
        ]
    )
    assert len({p.request.task_id for p in prepared}) == 1
    root = tmp_path / "evidence"
    root.mkdir(mode=0o700)
    first = await known_call(factory, ns, prepared[0], recipes[0], root)
    second = await known_call(factory, ns, prepared[1], recipes[1], root)
    assert (recipes[0].target.provider, recipes[1].target.provider) == ("openai", "google")
    target_scope = await approve_and_authorize(CompanyJournal(factory), ns, prepared[2])
    tool_scope, proposal = await prepare_overbill(factory, ns)
    assert tool_scope.task_id != target_scope.task_id
    execution, effects = ExecutionStore(factory), EffectStore(factory)
    tool_lease = await execution.claim(
        tool_scope, ns.identity(), uuid5(proposal.action_id, "worker"), ttl_seconds=60
    )
    assert (await effects.begin(tool_lease, ns.identity(), proposal.action_id)).permit_external_call
    receipt = ActionReceipt(
        company_id=ns.company,
        receipt_id=uuid5(proposal.action_id, "receipt"),
        action_id=proposal.action_id,
        task_id=proposal.task_id,
        trace_id=proposal.trace_id,
        proposal_hash=action_hash(proposal),
        outcome="succeeded",
        recorded_at=datetime.now(UTC),
        external_id="synthetic-overbill",
    )
    await effects.record_receipt(tool_lease, ns.identity(), receipt, actual_usd=Decimal("4.95"))
    released = await execution.release(tool_lease, ns.identity())
    assert released.worker_id is None and released.expires_at is None
    assert (await execution.get(tool_scope, ns.identity())).worker_id is None
    lease = await execution.claim(
        target_scope, ns.identity(), uuid5(prepared[2].request.action_id, "worker"), ttl_seconds=60
    )
    resolver = CountedResolver(recipes[2], unknown=True)
    client = QualificationClient(
        factory,
        effects,
        lease,
        ns.identity(),
        recipes[2],
        prepared[2].request,
        resolver,
        FileQualificationEvidenceStore(root),
        end_us=clock_us() + 45_000_000,
    )
    before = await snapshot(factory, ns)
    day, cap, days, _works, holds, intents, attempts, counters = before
    assert day == started_day and cap == Decimal("5.00") and len(days) == 1 and days[0][0] == day
    assert days[0][1] + days[0][2] > cap
    assert first.actual_usd is not None and second.actual_usd is not None
    assert days[0][2] == Decimal("4.95") + first.actual_usd + second.actual_usd
    for result in (first, second):
        usage = result.provider_result.usage
        assert usage is not None and usage.input_tokens == 100 and usage.output_tokens == 20
        assert usage.cached_input_tokens == 0 and usage.reasoning_tokens == 5
    assert first.actual_usd == Decimal("0.000165")
    assert second.actual_usd == Decimal("0.000080")
    assert days[0][2] == Decimal("4.950245")
    for action, amount in (
        (prepared[0].request.action_id, Decimal("0.000165")),
        (prepared[1].request.action_id, Decimal("0.000080")),
        (proposal.action_id, Decimal("4.95")),
    ):
        assert any(h[0] == action and h[2] == "reconciled" and h[4] == amount for h in holds)
    assert any(row[0] == target_scope.task_id and row[1:] == (2, 12) for row in counters)
    assert any(
        h[0] == prepared[2].request.action_id and h[2] == "held" and h[4] is None for h in holds
    )
    assert all(h[0] != prepared[2].request.action_id for h in intents)
    assert all(a[1] != prepared[2].request.action_id for a in attempts)
    with pytest.raises(ValueError, match="Qualification actual day allowance is unavailable"):
        await client.request_once()
    assert resolver.posts == 0 and not client.pending_owners()
    assert await snapshot(factory, ns) == before
    released = await execution.release(lease, ns.identity())
    assert released.worker_id is None and released.expires_at is None
    confirmed = await execution.get(target_scope, ns.identity())
    assert confirmed.worker_id is None and confirmed.expires_at is None
