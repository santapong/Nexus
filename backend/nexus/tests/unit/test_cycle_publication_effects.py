"""Known replay bypasses every preparation/publisher path; metadata delivery is mocked."""

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.execution.effect_support import effect_record
from nexus.tests.unit.cycle_prerequisite_fixture import signed_identity
from nexus.tests.unit.test_cycle_publication_intent import cycle_boundary

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("phase", ["author", "check"])
@pytest.mark.parametrize("state", ["intent", "outcome_unknown", "failed", "succeeded"])
async def test_known_issued_metadata_never_calls_a_publisher_or_requires_material(
    phase: str, state: str
) -> None:
    from nexus.company.cycle_artifacts.effect_adapter import CycleArtifactEffects

    case = cycle_boundary(4 if phase == "author" else 5)
    row = case.known()
    row.state = state
    record = effect_record(row)
    adapter = SimpleNamespace(
        known=AsyncMock(return_value=record),
        _run=AsyncMock(side_effect=AssertionError("known replay reached publication")),
    )
    call = CycleArtifactEffects.run_author if phase == "author" else CycleArtifactEffects.run_check
    # Explicitly isolate the actual early-return method; no native credential/DB authority claim.
    returned = await call(
        cast(CycleArtifactEffects, adapter),
        case.lease,
        case.identity,
        case.proposal.action_id,
        None,
        credential=await signed_identity(case.identity),
    )
    assert returned == record
    adapter._run.assert_not_awaited()


@pytest.mark.parametrize("damage", [None, "fence", "foreign_run", "expired_credential"])
async def test_actual_known_metadata_checks_own_fence_and_signed_credential_without_body_reads(
    monkeypatch: pytest.MonkeyPatch,
    damage: str | None,
) -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from datetime import timedelta
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.company.cycle_artifacts import effect_adapter as module
    from nexus.company.cycle_artifacts.input_reader import CycleInputReader
    from nexus.execution.runtime_models import EffectIntent

    case = cycle_boundary()
    row = case.known()
    case.control.paused = True
    credential = await signed_identity(case.identity)
    if damage == "fence":
        case.work.fence += 1
    elif damage == "foreign_run":
        row.run_id = UUID(int=999)
    elif damage == "expired_credential":
        case.now = credential.expires_at
        case.work.lease_until = case.now + timedelta(seconds=5)
    session = MagicMock(spec=AsyncSession)

    async def scalar(statement: object) -> object:
        text = str(statement)
        return False if "pg_roles" in text else case.now if "clock_timestamp" in text else case.work

    session.scalar = AsyncMock(side_effect=scalar)

    async def get(model: type[object], key: object) -> object:
        assert model is EffectIntent
        return row

    session.get = AsyncMock(side_effect=get)

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[object, object, object]]:
        assert kwargs == {"allow_paused": True, "allow_inactive": True}
        yield session, case.control, object()

    # Prior configured composition and current directory/transaction delivery are mocked;
    # actual known(), native lease/snapshot and genuine credential checks execute unchanged.
    inputs = SimpleNamespace(
        scope=CycleInputReader.scope, rules=SimpleNamespace(bind=lambda work: object())
    )
    body = AsyncMock(side_effect=AssertionError("known metadata reached protected body"))
    inputs.prepare_author = body
    adapter = SimpleNamespace(
        factory=object(),
        publisher=SimpleNamespace(inputs=inputs),
        composition=lambda: ("supplied prior configuration",),
        require_composition=lambda original: None,
    )
    monkeypatch.setattr(module, "runtime_transaction", transaction)
    call = module.CycleArtifactEffects.known
    if damage is None:
        result = await call(
            cast(module.CycleArtifactEffects, adapter),
            case.lease,
            case.identity,
            case.proposal.action_id,
            credential=credential,
        )
        assert result is not None and result.intent_fence == 1 and result.state == "outcome_unknown"
    else:
        with pytest.raises(ValueError):
            await call(
                cast(module.CycleArtifactEffects, adapter),
                case.lease,
                case.identity,
                case.proposal.action_id,
                credential=credential,
            )
    body.assert_not_awaited()
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.parametrize("change", ["catalog", "factory", "publisher"])
async def test_concrete_adapter_keeps_original_configuration_after_await(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: "Path",
    change: str,
) -> None:
    import asyncio

    from nexus.company.cycle_artifacts.deliverable_store import CycleDeliverableStore
    from nexus.company.cycle_artifacts.effect_adapter import CycleArtifactEffects
    from nexus.company.cycle_artifacts.original_reader import CycleOriginalReader
    from nexus.execution.effect_store import EffectStore
    from nexus.tests.unit.cycle_publication_fixture import input_reader

    reader = input_reader(monkeypatch, tmp_path)
    publisher = CycleDeliverableStore(
        reader.factory, reader.blobs, reader, CycleOriginalReader(reader)
    )
    effects = EffectStore(
        reader.factory,
        management_catalog=reader.catalog,
        management_artifacts=reader.artifacts,
        management_freshness=reader.freshness,
    )
    adapter = CycleArtifactEffects(effects, publisher)
    original = adapter.composition()
    await asyncio.sleep(0)
    if change == "catalog":
        effects._management_catalog = reader.catalog.model_copy(update={"cycle_admission": None})
    elif change == "factory":
        effects._factory = MagicMock()
    else:
        publisher.inputs = input_reader(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        adapter.require_composition(original)


@pytest.mark.parametrize("phase", ["author", "check"])
async def test_lost_unissued_preparation_never_recompiles_or_issues_an_attempt(phase: str) -> None:
    from nexus.company.cycle_artifacts.effect_adapter import CycleArtifactEffects

    case = cycle_boundary()
    adapter = SimpleNamespace(
        known=AsyncMock(return_value=None),
        _run=AsyncMock(side_effect=AssertionError("missing original preparation reached begin")),
    )
    call = CycleArtifactEffects.run_author if phase == "author" else CycleArtifactEffects.run_check
    with pytest.raises(ValueError, match="retained"):
        await call(
            cast(CycleArtifactEffects, adapter),
            case.lease,
            case.identity,
            case.proposal.action_id,
            None,
            credential=await signed_identity(case.identity),
        )
    adapter._run.assert_not_awaited()
