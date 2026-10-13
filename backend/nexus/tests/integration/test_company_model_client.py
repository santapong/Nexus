"""One actual offline SDK request, durable billing and capacity release in private PG."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.directory_models import DirectoryMembership
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.model_evidence import ModelEvidence
from nexus.tests.integration.company_model_client_fixture import client, rows
from nexus.tests.integration.company_model_client_fixture import client_factory as client_factory
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, TASK
from nexus.tests.unit.test_company_provider_conformance import KEY, response


@pytest.mark.parametrize("provider", ["openai", "google"])
@pytest.mark.parametrize("kind", ["known", "invalid", "missing", "timeout"])
async def test_issued_response_records_truthful_cost_and_releases_capacity(
    client_factory: async_sessionmaker[AsyncSession], tmp_path: Path, provider: str, kind: str
) -> None:
    count = 0

    def handle(wire: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        if kind == "timeout":
            raise httpx2.ReadTimeout("fixture timeout", request=wire)
        body = response(provider)
        if kind == "missing":
            body.pop("usage" if provider == "openai" else "usageMetadata")
        if kind == "invalid":
            body["output"] = [] if provider == "openai" else body.get("output", [])
            if provider == "google":
                body["candidates"] = []
        return httpx2.Response(200, json=body)

    governed, call, _ = await client(
        client_factory, tmp_path, httpx2.MockTransport(handle), provider=provider
    )
    result = await governed.request_once(call, now=datetime.now(UTC))
    assert count == 1 and result.recording_status == "recorded"
    assert result.recorded and result.release_status == "released"
    assert result.company_completed is False
    work, effect, hold, budget = await rows(client_factory, call)
    assert work.worker_id is None and work.model_requests_used == 1 and effect
    if kind in {"known", "invalid"}:
        assert result.ledger_billing == "known" and hold.state == "reconciled"
        assert result.recorded.actual_usd == hold.actual_usd == budget.spent_usd
        assert budget.held_usd == Decimal(0)
        assert work.state == ("verifying" if kind == "known" else "blocked")
    else:
        assert result.ledger_billing == "unknown" and hold.state == "unknown"
        assert hold.actual_usd is None and budget.held_usd == hold.amount_usd
        assert work.state == "outcome_unknown"
    assert result.stop_required == (kind != "known")
    assert KEY not in Path(result.recorded.artifact.reference).read_text()


async def test_duplicate_wrapper_invocations_do_not_reissue_record_or_release(
    client_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    count = 0

    async def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        await asyncio.sleep(0)
        return httpx2.Response(200, json=response("openai"))

    governed, call, _ = await client(client_factory, tmp_path, httpx2.MockTransport(handle))
    results = await asyncio.gather(
        *(governed.request_once(call, now=datetime.now(UTC)) for _ in range(2))
    )
    issued = next(r for r in results if r.provider_result.status == "response")
    denied = next(r for r in results if r.provider_result.status == "denied")
    assert count == 1 and issued.release_status == "released"
    assert denied.recorded is None and denied.recording_status == "not_issued"
    assert denied.release_status == "not_attempted" and denied.ledger_billing == "not_issued"
    assert (await rows(client_factory, call))[0].state == "verifying"


async def test_distinct_concurrent_loser_cannot_release_the_actual_issuer_lease(
    client_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    entered, deliver = asyncio.Event(), asyncio.Event()
    count = 0

    async def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        entered.set()
        await deliver.wait()
        return httpx2.Response(200, json=response("openai"))

    governed, call, composition = await client(
        client_factory, tmp_path, httpx2.MockTransport(handle)
    )
    issuer = asyncio.create_task(governed.request_once(call, now=datetime.now(UTC)))
    await entered.wait()
    denied = await composition.build().request_once(call, now=datetime.now(UTC))
    assert denied.provider_result.status == "denied" and denied.recorded is None
    assert denied.release_status == "not_attempted"
    work, effect, hold, _ = await rows(client_factory, call)
    assert work.worker_id and effect and effect.state == "intent" and hold.state == "held"
    deliver.set()
    issued = await issuer
    assert issued.ledger_billing == "known" and issued.release_status == "released" and count == 1


@pytest.mark.parametrize("revocation", ["fence", "member"])
async def test_already_issued_envelope_survives_denied_recording_and_stale_release(
    client_factory: async_sessionmaker[AsyncSession], tmp_path: Path, revocation: str
) -> None:
    count = 0

    async def handle(_: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        async with client_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            if revocation == "fence":
                await session.execute(
                    update(ExecutionWork)
                    .where(ExecutionWork.company_id == COMPANY, ExecutionWork.task_id == TASK)
                    .values(fence=ExecutionWork.fence + 1)
                )
            else:
                await session.execute(
                    update(DirectoryMembership)
                    .where(
                        DirectoryMembership.company_id == COMPANY,
                        DirectoryMembership.principal_id == ACTOR,
                    )
                    .values(membership_active=False)
                )
        return httpx2.Response(200, json=response("openai"))

    governed, call, _ = await client(client_factory, tmp_path, httpx2.MockTransport(handle))
    result = await governed.request_once(call, now=datetime.now(UTC))
    assert count == 1 and result.provider_result.billing == "known"
    assert result.recorded is None and result.recording_status == "failed"
    assert result.recording_error == "recording_denied" and result.ledger_billing == "unconfirmed"
    assert result.release_status == "failed" and result.release_error == "release_denied"
    assert result.stop_required and not result.company_completed
    evidence = ModelEvidence.model_validate_json(
        (tmp_path / str(COMPANY) / str(call.action_id) / f"{call.request_id}.json").read_text()
    )
    evidence.require_binding()
    assert evidence.result == result.provider_result
    work, effect, hold, budget = await rows(client_factory, call)
    assert work.worker_id and effect and effect.state == "intent"
    assert hold.state == "held" and hold.actual_usd is None
    assert budget.spent_usd == 0 and budget.held_usd == hold.amount_usd
