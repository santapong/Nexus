"""Persistent gate and actual SDK/HTTPMock: no real provider/network spend.

The shared fixture and complete negative matrix stay together for reviewable
transactional evidence, exceeding the ordinary file/function size guideline.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx2
import pytest
from pydantic import JsonValue, SecretStr, TypeAdapter
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import DirectoryMembership
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.core.llm.company_adapter_contracts import (
    CompanyModelRequest,
    ModelRequestCancelledError,
    ServerEndpoint,
    request_hash,
)
from nexus.core.llm.company_adapters import CompanyModelAdapters
from nexus.core.llm.company_pricing import CostQuote, quote_cost
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import CompanyControl, CostHold, DailyBudget, WorkBudget
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer
from nexus.harness.model_authorizer_contracts import (
    InputEstimate,
    ModelInputRecipe,
    model_action_parameters,
)
from nexus.harness.model_evidence import FileModelEvidenceStore
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TASK,
    TRACE,
    control,
    migrate,
)
from nexus.tests.integration.test_company_directory import (
    work as registered_work,
)
from nexus.tests.integration.test_company_registered_authorization import identity, prepare, scope
from nexus.tests.unit.test_company_provider_conformance import (
    KEY,
    EndpointResolver,
    catalog,
    request,
    response,
)


class FixtureEstimator:
    """Explicit synthetic estimator; this is not a production tokenizer/default."""

    def estimate(
        self, call: CompanyModelRequest, registry: ModelRegistry, recipe: ModelInputRecipe
    ) -> InputEstimate:
        return InputEstimate(
            request_hash=request_hash(call),
            registry_id=call.registry_id,
            registry_revision=registry.revision,
            recipe_id=recipe.recipe_id,
            recipe_revision=recipe.revision,
            input_text_tokens=len(call.input_text.encode()),
            system_text_tokens=len((call.system_text or "").encode()),
            tool_schema_tokens=sum(
                len(tool.model_dump_json(by_alias=True).encode()) for tool in call.tools
            ),
            output_schema_tokens=len(call.output_schema.document.encode())
            if call.output_schema
            else 0,
            sdk_overhead_tokens=256,
        )


def recipe() -> ModelInputRecipe:
    return ModelInputRecipe(
        recipe_id="fixture-full-request",
        revision="fixture-v1",
        profile="engineering",
        minimum_score=Decimal("0.80"),
        evaluation_suite_version="frozen-1",
        conformance_reference="fixture:estimator-not-live-conformance",
    )


@pytest.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    if not settings.company_test_database_url:
        pytest.skip("Explicit private model gate database is not configured")
    url = make_url(settings.company_test_database_url)
    assert (
        url.database == "nexus_company_test_model_gate"
        and settings.company_test_database_url != settings.database_url
    )
    engine = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    async with engine.begin() as connection:
        await connection.run_sync(migrate, "upgrade")
    try:
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await engine.dispose()


def current_registry(provider: str = "openai") -> ModelRegistry:
    source = catalog(provider)
    now = datetime.now(UTC)
    row = source.models[0]
    evaluation = row.evaluations[0].model_copy(
        update={"evaluated_at": now - timedelta(minutes=1), "expires_at": now + timedelta(hours=1)}
    )
    return source.model_copy(
        update={"models": (row.model_copy(update={"evaluations": (evaluation,)}),)}
    )


async def gate(
    factory: async_sessionmaker[AsyncSession],
    artifacts: Path,
    *,
    changes: dict[str, object] | None = None,
    profile: str = "engineering",
    registered_revision: str = "registry-1",
    amount: str = "0.02",
    registry: ModelRegistry | None = None,
    quote_at: datetime | None = None,
) -> tuple[PersistentModelCallAuthorizer, CompanyModelRequest, ModelRegistry, CostQuote]:
    journal, _ = await prepare(factory)
    call = request().model_copy(
        update={
            "task_id": TASK,
            "trace_id": TRACE,
            "actor_id": ACTOR,
            "action_id": UUID(int=500),
            "attempt_id": UUID(int=500),
        }
        | (changes or {})
    )
    registry = registry or current_registry()
    execution = ExecutionStore(factory)
    registration = ExecutionRegistration(
        work=WorkItem(
            company_id=COMPANY,
            task_id=TASK,
            trace_id=TRACE,
            goal_id=UUID(int=501),
            department="builder",
            title="model gate",
            acceptance=("fixture-result",),
            budget_usd=Decimal("1.00"),
        ),
        run_id=UUID(int=502),
        workflow_name="model-request-fixture",
        workflow_version="model-gate-v1",
        model_profile=profile,
        model_registry_version=registered_revision,
        quota=AttemptQuota(),
    )
    await execution.register(registration, scope(), identity())
    action = ActionProposal(
        company_id=COMPANY,
        task_id=TASK,
        trace_id=TRACE,
        actor_id=ACTOR,
        action_id=call.action_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource=f"model:{call.registry_id}",
        parameters=model_action_parameters(call, recipe()),
        policy_version="policy-1",
        price_version="prices-1",
        estimated_cost_usd=Decimal(amount),
    )
    await journal.submit(action, scope())
    now = datetime.now(UTC)
    record = await journal.get_action(scope(), action.action_id)
    await journal.approve_registered(
        scope(principal=OWNER),
        action.action_id,
        record.proposal_hash,
        now,
        identity=identity(OWNER),
    )
    await journal.authorize_registered(scope(), action.action_id, now, (), identity=identity())
    lease = await execution.claim(scope(), identity(), UUID(int=503), ttl_seconds=60)
    authority = PersistentModelCallAuthorizer(
        factory,
        lease,
        identity(),
        registry,
        resources=(),
        input_estimator=FixtureEstimator(),
        input_recipe=recipe(),
        allowed_classification="internal",
        evidence_store=FileModelEvidenceStore(artifacts),
    )
    return (
        authority,
        call,
        registry,
        quote_cost(registry.models[0].price, call.bounds, now=quote_at or now),
    )


async def test_claim_commits_exact_intent_before_one_actual_sdk_request(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    authority, call, registry, _ = await gate(factory, tmp_path)
    wires: list[httpx2.Request] = []

    def handle(wire: httpx2.Request) -> httpx2.Response:
        wires.append(wire)
        return httpx2.Response(200, json=response("openai"))

    endpoint = ServerEndpoint(
        endpoint_id="fixture-endpoint",
        provider="openai",
        api_family="openai_responses",
        base_url="https://offline.invalid/v1",
        api_key=SecretStr(KEY),
        transport=httpx2.MockTransport(handle),
        timeout_seconds=1,
    )
    result = await CompanyModelAdapters(
        registry, EndpointResolver(endpoint), authority
    ).request_once(call, now=datetime.now(UTC))
    assert result.status == "response" and len(wires) == 1
    recorded = await authority.record_result(call, result)
    assert (
        recorded.billing == "known"
        and recorded.actual_usd is not None
        and recorded.artifact is not None
    )
    evidence = await FileModelEvidenceStore(tmp_path).load(recorded.artifact)
    assert evidence.request_hash == request_hash(call) and evidence.action_hash
    assert evidence.price_version == call.price_version and evidence.result == result
    assert KEY not in Path(recorded.artifact.reference).read_text()
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        work = await session.get(ExecutionWork, (COMPANY, TASK))
        effect = await session.get(EffectIntent, (COMPANY, call.action_id))
        hold = await session.get(CostHold, call.action_id)
        assert work and work.model_requests_used == 1 and effect and effect.state == "succeeded"
        assert hold and hold.state == "reconciled" and hold.actual_usd == recorded.actual_usd


@pytest.mark.parametrize(
    "change",
    [
        {"company_id": UUID(int=999)},
        {"task_id": UUID(int=999)},
        {"trace_id": UUID(int=999)},
        {"actor_id": OWNER},
        {"request_id": UUID(int=999)},
        {"attempt_id": UUID(int=999)},
        {"registry_revision": "new-registry"},
        {"price_version": "new-prices"},
        {"input_text": "new text"},
        {"data_classification": "public"},
    ],
)
async def test_spliced_request_never_consumes_an_attempt_or_intent(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, change: dict[str, object]
) -> None:
    authority, call, _, quote = await gate(factory, tmp_path)
    with pytest.raises(ValueError):
        await authority.claim(call.model_copy(update=change), quote)
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.get(EffectIntent, (COMPANY, call.action_id)) is None
        work = await session.get(ExecutionWork, (COMPANY, TASK))
        hold = await session.get(CostHold, call.action_id)
        assert work is not None and hold is not None
        assert work.model_requests_used == 0
        assert hold.state == "held"


@pytest.mark.parametrize(
    "profile,revision", [("routine", "registry-1"), ("engineering", "other-catalog")]
)
async def test_current_execution_catalog_and_profile_cannot_be_overridden(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, profile: str, revision: str
) -> None:
    authority, call, _, quote = await gate(
        factory, tmp_path, profile=profile, registered_revision=revision
    )
    with pytest.raises(ValueError):
        await authority.claim(call, quote)


async def test_quote_and_input_understatement_are_denied(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    authority, call, _, quote = await gate(factory, tmp_path)
    with pytest.raises(ValueError):
        await authority.claim(call, quote.model_copy(update={"amount_usd": Decimal(0)}))
    low = call.model_copy(update={"bounds": call.bounds.model_copy(update={"input_tokens": 1})})
    with pytest.raises(ValueError):
        await authority.claim(low, quote)


@pytest.mark.parametrize("stale", ["health", "evaluation", "price"])
async def test_current_db_clock_rejects_expired_catalog_evidence(
    factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    stale: str,
) -> None:
    registry = current_registry()
    row = registry.models[0]
    expired = datetime.now(UTC) - timedelta(seconds=1)
    if stale == "health":
        row = row.model_copy(
            update={"health": row.health.model_copy(update={"expires_at": expired})}
        )
    elif stale == "evaluation":
        row = row.model_copy(
            update={"evaluations": (row.evaluations[0].model_copy(update={"expires_at": expired}),)}
        )
    else:
        assert row.price is not None
        row = row.model_copy(
            update={"price": row.price.model_copy(update={"valid_until": expired})}
        )
    # A quote made before evidence expiry is still no permission at current DB time.
    authority, call, _, _ = await gate(
        factory,
        tmp_path,
        registry=registry.model_copy(update={"models": (row,)}),
        quote_at=expired - timedelta(seconds=1),
    )
    quote = quote_cost(registry.models[0].price, call.bounds, now=datetime.now(UTC))
    with pytest.raises(ValueError, match="eligible"):
        await authority.claim(call, quote)


@pytest.mark.parametrize("revocation", ["actor", "owner", "paused"])
async def test_current_membership_and_pause_rechecked_after_approval(
    factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    revocation: str,
) -> None:
    authority, call, _, quote = await gate(factory, tmp_path)
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        if revocation == "paused":
            await session.execute(
                update(CompanyControl)
                .where(CompanyControl.company_id == COMPANY)
                .values(paused=True)
            )
        else:
            await session.execute(
                update(DirectoryMembership)
                .where(
                    DirectoryMembership.company_id == COMPANY,
                    DirectoryMembership.principal_id == (ACTOR if revocation == "actor" else OWNER),
                )
                .values(membership_active=False)
            )
    with pytest.raises(ValueError):
        await authority.claim(call, quote)


async def test_concurrent_claimants_have_one_permit_and_one_lifetime_attempt(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    authority, call, _, quote = await gate(factory, tmp_path)
    results = await asyncio.gather(
        authority.claim(call, quote), authority.claim(call, quote), return_exceptions=True
    )
    assert sum(isinstance(result, ValueError) for result in results) == 1
    with pytest.raises(ValueError):
        await authority.claim(call, quote)


def offline_adapter(
    authority: PersistentModelCallAuthorizer,
    registry: ModelRegistry,
    transport: httpx2.AsyncBaseTransport,
) -> CompanyModelAdapters:
    endpoint = ServerEndpoint(
        endpoint_id="fixture-endpoint",
        provider="openai",
        api_family="openai_responses",
        base_url="https://offline.invalid/v1",
        api_key=SecretStr(KEY),
        transport=transport,
        timeout_seconds=1,
    )
    return CompanyModelAdapters(registry, EndpointResolver(endpoint), authority)


async def test_concurrent_sdk_calls_issue_exactly_one_offline_wire_request(
    factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    authority, call, registry, _ = await gate(factory, tmp_path)
    count = 0

    def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        return httpx2.Response(200, json=response("openai"))

    adapter = offline_adapter(authority, registry, httpx2.MockTransport(handle))
    results = await asyncio.gather(
        *(adapter.request_once(call, now=datetime.now(UTC)) for _ in range(2))
    )
    assert sorted(row.status for row in results) == ["denied", "response"] and count == 1
    issued = next(row for row in results if row.status == "response")
    first = await authority.record_result(call, issued)
    assert await authority.record_result(call, issued) == first
    with pytest.raises(ValueError):
        await authority.record_result(call, next(row for row in results if row.status == "denied"))


async def test_independently_estimated_full_input_and_quote_must_fit_held_bound(
    factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    authority, call, _, quote = await gate(
        factory,
        tmp_path,
        changes={"bounds": request().bounds.model_copy(update={"input_tokens": 1})},
    )
    with pytest.raises(ValueError, match="input estimate"):
        await authority.claim(call, quote)


async def test_eligible_quote_must_fit_the_exact_action_hold(
    factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    authority, call, _, quote = await gate(factory, tmp_path, amount="0.000001")
    with pytest.raises(ValueError, match="eligible"):
        await authority.claim(call, quote)


@pytest.mark.parametrize("kind", ["work", "day"])
async def test_overbilling_blocks_previously_held_actions_at_current_caps(
    factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    kind: str,
) -> None:
    authority, call, _, quote = await gate(factory, tmp_path)
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        if kind == "work":
            await session.execute(
                update(WorkBudget)
                .where(WorkBudget.company_id == COMPANY)
                .values(spent_usd=Decimal("1.00"))
            )
        else:
            await session.execute(
                update(DailyBudget)
                .where(
                    DailyBudget.company_id == COMPANY,
                    DailyBudget.day == billing_day(datetime.now(UTC)),
                )
                .values(spent_usd=Decimal("5.00"))
            )
    with pytest.raises(ValueError, match="allowance"):
        await authority.claim(call, quote)


async def test_child_model_cannot_evade_an_overbilled_parent_own_slice(
    factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    _, root_call, registry, _ = await gate(factory, tmp_path)
    child = UUID(int=600)
    await PersistentCompanyDirectory(factory).register_work(
        registered_work(child, parent=TASK, amount="0.50"), control()
    )
    execution = ExecutionStore(factory)
    parent = await execution.get(scope(), identity())
    work = parent.registration.work.model_copy(
        update={"task_id": child, "budget_usd": Decimal("0.50")}
    )
    await execution.register(
        parent.registration.model_copy(
            update={
                "work": work,
                "run_id": UUID(int=601),
                "quota": AttemptQuota(
                    model_requests=1, tool_attempts=0, rework_rounds=0, plan_revisions=0
                ),
            }
        ),
        scope(task=child),
        identity(),
    )
    call = root_call.model_copy(
        update={"task_id": child, "action_id": UUID(int=602), "attempt_id": UUID(int=602)}
    )
    action = ActionProposal(
        company_id=COMPANY,
        task_id=child,
        trace_id=TRACE,
        actor_id=ACTOR,
        action_id=call.action_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource=f"model:{call.registry_id}",
        parameters=model_action_parameters(call, recipe()),
        policy_version="policy-1",
        price_version="prices-1",
        estimated_cost_usd=Decimal("0.02"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(action, scope(task=child))
    row = await journal.get_action(scope(task=child), action.action_id)
    now = datetime.now(UTC)
    await journal.approve_registered(
        scope(task=child, principal=OWNER),
        action.action_id,
        row.proposal_hash,
        now,
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        scope(task=child), action.action_id, now, (), identity=identity()
    )
    lease = await execution.claim(scope(task=child), identity(), UUID(int=603), ttl_seconds=60)
    authority = PersistentModelCallAuthorizer(
        factory,
        lease,
        identity(),
        registry,
        resources=(),
        input_estimator=FixtureEstimator(),
        input_recipe=recipe(),
        allowed_classification="internal",
        evidence_store=FileModelEvidenceStore(tmp_path),
    )
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        await session.execute(
            update(WorkBudget)
            .where(WorkBudget.company_id == COMPANY, WorkBudget.task_id == TASK)
            .values(spent_usd=Decimal("0.51"))
        )
    with pytest.raises(ValueError, match="ancestor allowance"):
        await authority.claim(call, quote_cost(registry.models[0].price, call.bounds, now=now))


@pytest.mark.parametrize("fault", ["timeout", "invalid-schema", "over-bound"])
async def test_failed_or_overbound_sdk_request_keeps_one_attempt_and_truthful_billing(
    factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    fault: str,
) -> None:
    authority, call, registry, _ = await gate(factory, tmp_path)
    body = TypeAdapter(dict[str, JsonValue]).validate_python(response("openai"))
    if fault == "invalid-schema":
        output = body["output"]
        assert isinstance(output, list)
        message = output[0]
        assert isinstance(message, dict)
        content = message["content"]
        assert isinstance(content, list)
        part = content[0]
        assert isinstance(part, dict)
        part["text"] = '{"result":12}'
    if fault == "over-bound":
        usage = body["usage"]
        assert isinstance(usage, dict)
        usage["input_tokens"] = 1_000_000
        usage["total_tokens"] = 1_000_020
    count = 0

    def handle(wire: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        if fault == "timeout":
            raise httpx2.ReadTimeout("offline timeout", request=wire)
        return httpx2.Response(200, json=body)

    adapter = offline_adapter(authority, registry, httpx2.MockTransport(handle))
    result = await adapter.request_once(call, now=datetime.now(UTC))
    recorded = await authority.record_result(call, result)
    assert result.status == "failed" and recorded.stop_required
    assert (
        await adapter.request_once(call, now=datetime.now(UTC))
    ).status == "denied" and count == 1
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        work = await session.get(ExecutionWork, (COMPANY, TASK))
        hold = await session.get(CostHold, call.action_id)
        assert work and work.model_requests_used == 1 and hold
        assert hold.state == ("unknown" if fault == "timeout" else "reconciled")
        assert work.state == ("outcome_unknown" if fault == "timeout" else "blocked")
        if fault == "over-bound":
            assert hold.actual_usd is not None and recorded.actual_usd is not None
            assert hold.actual_usd > Decimal("1.00") and hold.actual_usd == recorded.actual_usd


async def test_cancelled_sdk_request_retains_intent_attempt_and_unknown_hold(
    factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    authority, call, registry, _ = await gate(factory, tmp_path)
    entered = asyncio.Event()

    async def handle(_: httpx2.Request) -> httpx2.Response:
        entered.set()
        await asyncio.Event().wait()
        return httpx2.Response(200, json=response("openai"))

    adapter = offline_adapter(authority, registry, httpx2.MockTransport(handle))
    task = asyncio.create_task(adapter.request_once(call, now=datetime.now(UTC)))
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(ModelRequestCancelledError) as caught:
        await task
    recorded = await authority.record_result(call, caught.value.result)
    assert recorded.billing == "unknown" and recorded.stop_required
    with pytest.raises(ValueError):
        await authority.claim(
            call, quote_cost(registry.models[0].price, call.bounds, now=datetime.now(UTC))
        )


async def test_returned_result_is_saved_even_when_recording_actor_was_revoked(
    factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    authority, call, registry, _ = await gate(factory, tmp_path)
    adapter = offline_adapter(
        authority,
        registry,
        httpx2.MockTransport(lambda _: httpx2.Response(200, json=response("openai"))),
    )
    result = await adapter.request_once(call, now=datetime.now(UTC))
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        await session.execute(
            update(DirectoryMembership)
            .where(
                DirectoryMembership.company_id == COMPANY, DirectoryMembership.principal_id == ACTOR
            )
            .values(membership_active=False)
        )
    with pytest.raises(ValueError):
        await authority.record_result(call, result)
    saved = tmp_path / str(COMPANY) / str(call.action_id) / f"{call.request_id}.json"
    assert saved.exists() and '"status":"response"' in saved.read_text()
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        hold = await session.get(CostHold, call.action_id)
        effect = await session.get(EffectIntent, (COMPANY, call.action_id))
        assert hold and hold.state == "held" and hold.actual_usd is None
        assert effect and effect.receipt_json is None


async def test_missing_wire_usage_is_unknown_and_preserves_spend_hold(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    authority, call, registry, _ = await gate(factory, tmp_path)
    wire = response("openai")
    wire.pop("usage")
    endpoint = ServerEndpoint(
        endpoint_id="fixture-endpoint",
        provider="openai",
        api_family="openai_responses",
        base_url="https://offline.invalid/v1",
        api_key=SecretStr(KEY),
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=wire)),
        timeout_seconds=1,
    )
    result = await CompanyModelAdapters(
        registry, EndpointResolver(endpoint), authority
    ).request_once(call, now=datetime.now(UTC))
    assert result.billing == "unknown"
    recorded = await authority.record_result(call, result)
    assert recorded.billing == "unknown" and recorded.actual_usd is None and recorded.stop_required
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        hold = await session.get(CostHold, call.action_id)
        assert hold and hold.state == "unknown" and hold.amount_usd == Decimal("0.02")
