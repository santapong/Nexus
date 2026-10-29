"""An issued mock request with missing usage retains its hold and cannot replay."""

import hashlib
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from uuid import uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.execution.effect_store import EffectStore
from nexus.execution.qualification_service import QualificationPreparationService
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal import CompanyJournal
from nexus.harness.qualification_client import QualificationClient
from nexus.harness.qualification_evidence import FileQualificationEvidenceStore
from nexus.tests.integration import test_company_model_qualification as existing
from nexus.tests.integration.n5_qualification_fixture import (
    CountedResolver,
    Namespace,
    approve_and_authorize,
    disposable_factory,
    make_goal,
    snapshot,
)
from nexus.tests.unit.test_company_provider_conformance import KEY


@pytest.fixture
async def isolated_factory() -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], Namespace]]:
    async with disposable_factory("nexus_company_test_model_unknown") as value:
        yield value


async def test_issued_unknown_preserves_hold_and_replay_never_posts(
    isolated_factory: tuple[async_sessionmaker[AsyncSession], Namespace], tmp_path: Path
) -> None:
    factory, ns = isolated_factory
    reference = await make_goal(factory, ns, tmp_path)
    recipes = await existing.recipes(reference)
    recipe = recipes[2]
    assert recipe.target.provider == "google" and recipe.case_id == "missing-usage"
    prepared = await QualificationPreparationService(factory, recipes).prepare_qualification(
        ns.control("prepare"), ns.identity(), recipe.recipe_id
    )
    scope = await approve_and_authorize(CompanyJournal(factory), ns, prepared)
    execution, effects = ExecutionStore(factory), EffectStore(factory)
    lease = await execution.claim(
        scope, ns.identity(), uuid5(prepared.request.action_id, "worker"), ttl_seconds=60
    )
    evidence_root = tmp_path / "unknown-evidence"
    evidence_root.mkdir(mode=0o700)
    store = FileQualificationEvidenceStore(evidence_root)
    resolver = CountedResolver(recipe, unknown=True)
    before = await snapshot(factory, ns)
    assert len(before.days) == 1 and before.days[0][1:] == (Decimal("0.478413"), Decimal("0"))
    assert before.day == before.days[0][0] and before.cap == Decimal("5")
    end = clock_us() + 45_000_000
    client = QualificationClient(
        factory,
        effects,
        lease,
        ns.identity(),
        recipe,
        prepared.request,
        resolver,
        store,
        end_us=end,
    )
    result = await client.request_once()
    assert resolver.posts == 1 and not client.pending_owners()
    assert result.provider_result.status == "failed" and result.provider_result.billing == "unknown"
    assert result.provider_result.usage is None and result.provider_result.text is None
    assert result.provider_result.structured_json is None and not result.provider_result.tool_calls
    assert result.record is not None and result.record.state == "outcome_unknown"
    assert (
        result.actual_usd is None and result.recording_error is None and result.evidence is not None
    )
    assert result.stop_required and not result.profile_quality_evaluated
    saved = await store.load(result.evidence, end_us=end)
    assert saved.recipe == recipe and saved.request == prepared.request
    assert saved.provider_result == result.provider_result
    evidence_file = Path(result.evidence.reference)
    assert hashlib.sha256(evidence_file.read_bytes()).hexdigest() == result.evidence.sha256
    assert KEY not in evidence_file.read_text()
    assert evidence_file.stat().st_mode & 0o777 == 0o400
    assert await effects.get(lease, ns.identity(), prepared.request.action_id) == result.record
    after = await snapshot(factory, ns)
    day, cap, days, works, holds, intents, attempts, counters = after
    assert day == before.day and cap == Decimal("5")
    assert len(days) == 1 and days[0] == (day, Decimal("0.478413"), Decimal("0"))
    assert len(works) == 1 and works[0] == (scope.task_id, Decimal("0.478413"), Decimal("0"))
    assert len(holds) == 1
    assert holds[0] == (prepared.request.action_id, day, "unknown", Decimal("0.478413"), None)
    assert intents == ((prepared.request.action_id, "outcome_unknown"),)
    assert attempts == ((scope.task_id, prepared.request.action_id, "model_requests"),)
    assert counters == ((scope.task_id, 1, 12),)
    replay = QualificationClient(
        factory,
        effects,
        lease,
        ns.identity(),
        recipe,
        prepared.request,
        resolver,
        store,
        end_us=end,
    )
    denied = await replay.request_once()
    assert (
        denied.provider_result.status == "denied" and denied.provider_result.billing == "not_issued"
    )
    assert denied.provider_result.error_code == "qualification_unissued" and resolver.posts == 1
    assert not replay.pending_owners() and await snapshot(factory, ns) == after
    released = await execution.release(lease, ns.identity())
    assert released.worker_id is None and released.expires_at is None
    confirmed = await execution.get(scope, ns.identity())
    assert confirmed.worker_id is None and confirmed.expires_at is None
