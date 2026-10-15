"""Mocked native proof orchestration; no claim of SQL rollback or current S/SV authority."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.management.acceptance_models import (
    ManagementAcceptanceProof,
    ManagementWorkAcceptance,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.strategy import acceptance_store as module
from nexus.company.strategy.acceptance import build_strategy_acceptance
from nexus.company.strategy.acceptance_store import StrategyAcceptanceStore
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.tests.unit.strategy_brief_fixture import strategy_case
from nexus.tests.unit.strategy_verifier_receipt_fixture import receipt_case
from nexus.tests.unit.test_strategy_acceptance_description import _actual_description
from nexus.tests.unit.test_strategy_check_output import inputs


@pytest.mark.parametrize(
    "failure", [None, "pair_after_write", "initial", "result1", "current", "result2"]
)
async def test_acceptance_rechecks_current_target_and_all_captured_windows_after_write(
    monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    # Keep this >50-line mock flow's original/current protected windows and failure order together.
    case = receipt_case(monkeypatch)
    facts, raw = _actual_description(case)
    command, manifest = strategy_case().command, inputs()
    record = build_strategy_acceptance(command, manifest, facts, raw, case.clock["now"])
    events: list[str] = []

    class Protection:
        def __init__(self, name: str) -> None:
            self.name = name

        def require_time(self, _: object) -> None:
            events.append(self.name)
            if failure == self.name:
                raise AcceptanceDeniedError("nominated late expiry")

    count = {"load": 0, "result": 0}

    async def load(*_: object, **__: object) -> object:
        count["load"] += 1
        if count["load"] == 2 and failure == "pair_after_write":
            raise AcceptanceDeniedError("nominated changed current pair")
        return SimpleNamespace(
            command=command,
            inputs=manifest,
            classification="internal",
            protection=Protection("initial" if count["load"] == 1 else "current"),
        )

    async def protected(*_: object, **__: object) -> object:
        count["result"] += 1
        return Protection(f"result{count['result']}")

    factory = cast(async_sessionmaker[AsyncSession], object())
    reader = MagicMock(spec=StrategyInputReader)
    reader.artifacts = SimpleNamespace(factory=factory)
    reader.rules = SimpleNamespace(check=case.rule)
    reader.load_check_locked = AsyncMock(side_effect=load)
    reader.protect_check_result_locked = AsyncMock(side_effect=protected)
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(
        return_value=SimpleNamespace(raw_text=raw.decode(), resource_id=case.artifact.resource_id)
    )
    session.scalar = AsyncMock(return_value=False)
    session.flush = AsyncMock()

    @asynccontextmanager
    async def transaction(
        *_: object, **__: object
    ) -> AsyncIterator[tuple[AsyncSession, object, object]]:
        yield cast(AsyncSession, session), case.control, case.clock["now"]

    async def persist(*_: object) -> object:
        events.append("persist")
        return record

    monkeypatch.setattr(module, "runtime_transaction", transaction)
    monkeypatch.setattr(module, "require_strategy_verifier_receipt", AsyncMock(return_value=facts))
    monkeypatch.setattr(module, "_persist_locked", persist)
    monkeypatch.setattr(module, "append_event", AsyncMock())
    monkeypatch.setattr(module, "db_now", AsyncMock(return_value=case.clock["now"]))
    monkeypatch.setattr(module, "execution_row", AsyncMock(return_value=case.work))
    store = StrategyAcceptanceStore(factory, reader)

    async def publish() -> object:
        return await store.publish_verified_result(
            case.lease,
            case.credential.identity,
            author_action_id=command.target.action_id,
            verifier_action_id=facts.action.action_id,
            protected_result=facts.protected_result,
            credential=case.credential,
        )

    if failure is not None:
        with pytest.raises(AcceptanceDeniedError):
            await publish()
        assert events[0] == "persist"
        return
    assert await publish() == record
    assert events == ["persist", "initial", "result1", "current", "result2"]
    assert (
        reader.load_check_locked.await_count == 2
        and reader.protect_check_result_locked.await_count == 2
    )


@pytest.mark.parametrize("change", [None, "missing", "extra", "hash", "foreign", "timestamp"])
async def test_actual_saved_acceptance_requires_complete_original_proof_rows(
    monkeypatch: pytest.MonkeyPatch, change: str | None
) -> None:
    # This >50-line native-row fixture keeps the saved target columns and proof bytes exact.
    case = receipt_case(monkeypatch)
    facts, raw = _actual_description(case)
    record = build_strategy_acceptance(
        strategy_case().command, inputs(), facts, raw, case.clock["now"]
    )
    target = record.target
    saved = ManagementWorkAcceptance(
        company_id=record.company_id,
        acceptance_id=record.acceptance_id,
        author_task_id=target.author.task_id,
        author_run_id=target.author.run_id,
        author_id=target.author.actor_id,
        verifier_task_id=target.verifier.task_id,
        verifier_run_id=target.verifier.run_id,
        verifier_id=target.verifier.actor_id,
        action_id=target.action_id,
        receipt_id=target.receipt_id,
        receipt_sha256=target.receipt_sha256,
        work_sha256=target.work_snapshot_sha256,
        target_sha256=canonical_sha256(target),
        verdict=record.verdict,
        target_json=target.model_dump_json(),
        result_json=record.model_dump_json(),
        recorded_at=record.recorded_at,
    )
    value = record.proofs[0]
    proof = ManagementAcceptanceProof(
        company_id=record.company_id,
        acceptance_id=record.acceptance_id,
        proof_id=value.proof_id,
        artifact_revision_id=value.result_artifact.artifact_revision_id,
        artifact_sha256=value.result_artifact.sha256,
        check_recipe=value.recipe,
        target_sha256=value.target_sha256,
        proof_json=value.model_dump_json(),
    )
    proofs = [proof]
    if change == "missing":
        proofs = []
    elif change == "extra":
        proofs = [proof, proof]
    elif change == "hash":
        proof.artifact_sha256 = "b" * 64
    elif change == "foreign":
        proof.company_id = UUID(int=999)
    elif change == "timestamp":
        saved.recorded_at += timedelta(seconds=1)
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=saved)
    result = MagicMock()
    result.all.return_value = proofs
    session.scalars = AsyncMock(return_value=result)
    if change is not None:
        with pytest.raises(AcceptanceDeniedError):
            await module._persist_locked(session, record)
    else:
        assert await module._persist_locked(session, record) == record
    session.add.assert_not_called()
