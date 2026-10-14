"""A disabled tick is a constant no-read path and metadata cannot carry effect authority."""

from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from nexus.company.notifications.worker_contracts import WorkerTickResult
from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.tests.unit.test_company_notification_worker_services import services


async def test_disabled_tick_performs_no_file_credential_or_database_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = services(tmp_path)
    reader = MagicMock(side_effect=AssertionError("disabled file read"))
    credential = AsyncMock(side_effect=AssertionError("disabled credential read"))
    monkeypatch.setattr(value.registrations, "snapshot", reader)
    monkeypatch.setattr(type(value.identities), "current", credential)
    result = await NotificationReadPreparationWorker(value).tick()
    assert result == WorkerTickResult(disposition="disabled")
    reader.assert_not_called()
    credential.assert_not_called()
    cast(MagicMock, value.factory).assert_not_called()


@pytest.mark.parametrize("bad", [1, "true", None])
def test_worker_enablement_requires_literal_server_boolean(tmp_path: Path, bad: object) -> None:
    with pytest.raises(ValueError):
        NotificationReadPreparationWorker(services(tmp_path), enabled=cast(bool, bad))


@pytest.mark.parametrize(
    "data",
    [
        {"new_wakes": True},
        {"new_wakes": 33},
        {"events_acknowledged": 33},
        {"approval": True},
        {"call_permit": True},
        {"token": "synthetic-unused"},
    ],
)
def test_tick_metadata_rejects_coerced_unbounded_or_authority_fields(
    data: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        WorkerTickResult.model_validate({"disposition": "quiet"} | data)
