"""Real sidecar I/O closes mocked native publication windows; no PG permission/commit proof."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder import artifact_publisher as module
from nexus.builder.contained_contracts import ContainedEvidenceIdentity
from nexus.builder.contained_evidence_types import ContainedObservation, ContainmentRef
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.tests.builder_support import described_binding
from nexus.tests.contained_sidecar_fixture import contained_result, publisher


@pytest.mark.parametrize("fault", [None, "expired", "bytes"])
async def test_actual_sidecar_read_precedes_append_and_final_publication_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    # One nominated transaction boundary keeps original/current windows and the
    # actual sidecar read together; mocks do not establish native PG authority.
    value, store = await contained_result(tmp_path)
    configured = publisher(
        containment_store=store, execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256
    )
    _, lease, _ = described_binding(value.spec.job)
    identity = VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id)
    guard = MagicMock(spec=BuilderSourceGuard)
    now = [datetime.now(UTC)]
    expiry = now[0] + timedelta(seconds=1)
    events: list[str] = []
    session = MagicMock(spec=AsyncSession)

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, object, None]]:
        yield session, object(), None
        events.append("commit")

    real = store.load_exact

    async def observed(
        reference: ContainmentRef, expected: ContainedEvidenceIdentity
    ) -> ContainedObservation:
        assert events == ["intent", "sources", "derivation"]
        events.append("sidecar")
        result = await real(reference, expected)
        if fault == "expired":
            now[0] = expiry
        return result

    monkeypatch.setattr(store, "load_exact", observed)
    monkeypatch.setattr(module, "runtime_transaction", transaction)
    monkeypatch.setattr(module, "execution_row", AsyncMock(return_value=object()))
    monkeypatch.setattr(module, "db_now", AsyncMock(side_effect=lambda _: now[0]))
    monkeypatch.setattr(module, "require_lease", MagicMock())
    monkeypatch.setattr(
        module,
        "require_publication_intent",
        AsyncMock(side_effect=lambda *a: events.append("intent")),
    )

    async def disclosure(*args: object) -> tuple[datetime, ...]:
        events.append("sources")
        return (expiry,)

    guard.disclosure_windows = AsyncMock(side_effect=disclosure)
    monkeypatch.setattr(module, "publication_inputs", AsyncMock(return_value=((), (), ())))
    monkeypatch.setattr(module, "recipient_windows", AsyncMock(return_value=()))
    monkeypatch.setattr(
        module, "require_resources", AsyncMock(return_value=(SimpleNamespace(expires_at=expiry),))
    )
    monkeypatch.setattr(configured, "derivation", MagicMock(return_value=object()))
    monkeypatch.setattr(
        module, "validate_derivation", AsyncMock(side_effect=lambda *a: events.append("derivation"))
    )
    append = AsyncMock(side_effect=lambda *a: events.append("append"))
    monkeypatch.setattr(configured, "append", append)
    if fault == "bytes":
        assert value.containment is not None
        (store.root / store.filename(value.containment.identity)).write_bytes(b"{}")
    if fault is not None:
        with pytest.raises(ValueError):
            await configured.publish(value, lease, identity, guard)
        assert "commit" not in events
        if fault == "bytes":
            append.assert_not_awaited()
    else:
        await configured.publish(value, lease, identity, guard)
        assert events == ["intent", "sources", "derivation", "sidecar", "append", "commit"]
