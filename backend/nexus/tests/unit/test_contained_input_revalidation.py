"""Cached engineering metadata never caches the private sidecar or final freshness clock."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from nexus.builder import engineering_inputs as module
from nexus.builder.contained_contracts import ContainedEvidenceIdentity
from nexus.builder.contained_evidence_types import ContainedObservation, ContainmentRef
from nexus.builder.engineering_inputs import PreparedEngineeringInput
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.tests.contained_sidecar_fixture import contained_result, publisher
from nexus.tests.unit.test_contained_protected_loading import inputs


@pytest.mark.parametrize("fault", [None, "bytes", "expired"])
async def test_each_revalidation_rereads_both_results_before_final_freshness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    # This keeps both cached result positions and the final nominated clock in
    # one unit scenario. Native identity/READ is mocked, actual sidecar bytes are not.
    value, store = await contained_result(tmp_path)
    loader = inputs(value, store)
    reference = publisher(
        containment_store=store, execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256
    ).reference(value)
    metadata = SimpleNamespace(
        author_registration=SimpleNamespace(work=SimpleNamespace(goal_id=UUID(int=1))),
        author_output=reference,
        verifier_output=reference,
    )
    command = SimpleNamespace(
        declaration=loader.declarations[UUID(int=1)],
        target=object(),
        author=value,
        verifier=value,
    )
    prepared = cast(
        PreparedEngineeringInput,
        SimpleNamespace(
            command=command,
            metadata=metadata,
            artifacts=(),
            freshness=(),
        ),
    )
    events: list[str] = []
    now = [datetime.now(UTC)]
    expiry = now[0] + timedelta(seconds=1)
    real = store.load_exact

    async def read(
        reference: ContainmentRef, expected: ContainedEvidenceIdentity
    ) -> ContainedObservation:
        events.append("sidecar")
        actual = await real(reference, expected)
        if fault == "expired":
            now[0] = expiry
        return actual

    async def freshness(*args: object) -> None:
        events.append("freshness")
        if now[0] >= expiry:
            raise ValueError("Actual final freshness boundary expired")

    def clock(*args: object) -> datetime:
        events.append("clock")
        return now[0]

    monkeypatch.setattr(store, "load_exact", read)
    monkeypatch.setattr(module, "engineering_scope", MagicMock())
    monkeypatch.setattr(module, "actual_engineering_metadata", AsyncMock(return_value=metadata))
    monkeypatch.setattr(module, "actual_result_reference", AsyncMock(return_value=reference))
    monkeypatch.setattr(module, "db_now", AsyncMock(side_effect=clock))
    monkeypatch.setattr(loader.freshness, "revalidate", AsyncMock(side_effect=freshness))
    if fault == "bytes":
        assert value.containment is not None
        (store.root / store.filename(value.containment.identity)).write_bytes(b"{}")
    if fault is not None:
        with pytest.raises(ValueError):
            await loader.revalidate(
                MagicMock(), MagicMock(), MagicMock(), MagicMock(), prepared, now[0]
            )
        if fault == "bytes":
            assert events == ["sidecar"]
    else:
        await loader.revalidate(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), prepared, now[0]
        )
        assert events == ["sidecar", "sidecar", "clock", "freshness"]
