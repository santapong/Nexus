"""Owned stopped container removal uses immutable ID and preserves error/unknown distinctions."""

from unittest.mock import AsyncMock

import pytest

from nexus.builder.engineering_cleanup import inspect_owned_stopped, remove_captured

ID = "a" * 64
IMAGE = "b" * 64
ACTION = "00000000-0000-0000-0000-000000000007"
COMPANY = "00000000-0000-0000-0000-000000000001"
NAME = "nexus-builder-" + "c" * 32


async def test_exact_stopped_capture_is_removed_by_full_id(monkeypatch: pytest.MonkeyPatch) -> None:
    import nexus.builder.engineering_cleanup as module

    calls: list[tuple[str, ...]] = []

    async def owned(argv: tuple[str, ...], limit: int = 16384) -> bytes:
        calls.append(argv)
        return (
            f"{ID} {NAME}".encode()
            if argv[0] == "ps"
            else f"{ID} {ACTION} {COMPANY} false {IMAGE}".encode()
        )

    monkeypatch.setattr(module, "owned_engine", owned)
    captured = await inspect_owned_stopped(NAME, ACTION, COMPANY, IMAGE)
    assert captured is not None and captured.container_id == ID
    await remove_captured(captured)
    assert calls[-1] == ("rm", ID)


@pytest.mark.parametrize("case", ["live", "action", "company", "image", "id"])
async def test_bad_owned_capture_never_removed(monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    import nexus.builder.engineering_cleanup as module

    fields = [ID, ACTION, COMPANY, "false", IMAGE]
    fields[{"id": 0, "action": 1, "company": 2, "live": 3, "image": 4}[case]] = (
        "true" if case == "live" else "wrong"
    )
    monkeypatch.setattr(
        module,
        "owned_engine",
        AsyncMock(side_effect=[f"{ID} {NAME}".encode(), " ".join(fields).encode()]),
    )
    with pytest.raises(ValueError):
        await inspect_owned_stopped(NAME, ACTION, COMPANY, IMAGE)


async def test_inspect_error_is_not_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import nexus.builder.engineering_cleanup as module

    monkeypatch.setattr(
        module, "owned_engine", AsyncMock(side_effect=ValueError("Synthetic engine unavailable"))
    )
    with pytest.raises(ValueError):
        await inspect_owned_stopped(NAME, ACTION, COMPANY, IMAGE)


async def test_successful_empty_inventory_is_idempotent_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.builder.engineering_cleanup as module

    engine = AsyncMock(return_value=b"")
    monkeypatch.setattr(module, "owned_engine", engine)
    assert await inspect_owned_stopped(NAME, ACTION, COMPANY, IMAGE) is None
    assert engine.await_count == 1


async def test_wrong_actual_protected_result_digest_cannot_authorize_cleanup() -> None:
    import hashlib
    import json
    from uuid import uuid4

    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.builder.engineering_cleanup import require_stored_result_summary
    from nexus.company.brain.source_models import BrainArtifactRevision
    from nexus.tests.engineering_check_support import check_input

    result = check_input().verifier
    raw = json.dumps(
        {
            "result_sha256": "f" * 64,
            "spec": result.spec.model_dump(mode="json"),
            "proposal_sha256": result.proposal_sha256,
            "intent_fence": result.intent_fence,
        }
    )
    row = BrainArtifactRevision(
        raw_text=raw, byte_length=len(raw.encode()), sha256=hashlib.sha256(raw.encode()).hexdigest()
    )
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = row
    with pytest.raises(ValueError, match="binding differs"):
        await require_stored_result_summary(session, result, uuid4())


async def test_unknown_result_cannot_enter_native_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    from typing import cast

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import nexus.builder.engineering_cleanup as module
    from nexus.builder.engineering_cleanup import cleanup_known_engineering_container
    from nexus.company.access import VerifiedIdentity
    from nexus.company.contracts.actions import ActionProposal
    from nexus.execution.runtime_contracts import ExecutionLease
    from nexus.tests.engineering_check_support import check_input

    value = check_input()
    result = value.verifier.model_copy(
        update={"outcome": "outcome_unknown", "commands": (), "artifacts": ()}
    )
    actual = AsyncMock()
    monkeypatch.setattr(module, "actual_action", actual)
    # Unknown result must deny before any current-store/engine side effect.
    with pytest.raises(ValueError, match="known reconciliation"):
        await cleanup_known_engineering_container(
            cast(async_sessionmaker[AsyncSession], object()),
            cast(ExecutionLease, type("Lease", (), {"mode": "reconcile"})()),
            cast(VerifiedIdentity, object()),
            cast(ActionProposal, object()),
            result.spec,
            result,
            value.verifier_receipt,
        )
    assert actual.await_count == 0
