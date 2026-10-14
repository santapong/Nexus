"""Trusted worker startup cannot reuse an unrelated singleton or elevated system engine."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from dbos import _dbos
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from nexus.execution import notification_worker as module
from nexus.tests.notification_durable_unit_fixture import recovery_inputs


def witness() -> module.NotificationDatabaseWitness:
    return module.NotificationDatabaseWitness(
        database="fixture",
        username="app",
        port=55438,
        server_address=None,
        backend_pid=412,
        backend_start=datetime.now(UTC),
        client_address=None,
        elevated=False,
    )


async def test_failed_sdk_constructor_disposes_owned_engine_without_poisoning_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    engine = MagicMock()
    monkeypatch.setattr(module, "_services", None)
    monkeypatch.setattr(module, "_system_engine", None)
    monkeypatch.setattr(_dbos, "_dbos_global_instance", None)
    create = MagicMock(return_value=engine)
    monkeypatch.setattr(module, "create_engine", create)
    monkeypatch.setattr(module, "require_database_endpoint", MagicMock())
    monkeypatch.setattr(module, "DBOS", MagicMock(side_effect=RuntimeError("constructor")))
    with pytest.raises(RuntimeError, match="constructor"):
        module.configure_notification_worker(value.services, "postgresql+asyncpg:///fixture")
    assert module._services is None and module._system_engine is None
    assert create.call_args.kwargs == {"pool_size": 4, "max_overflow": 0, "pool_timeout": 30}
    assert create.call_args.args[0].drivername == "postgresql+psycopg"
    engine.dispose.assert_called_once()


async def test_preexisting_sdk_singleton_cannot_silently_select_foreign_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "_services", None)
    monkeypatch.setattr(module, "_system_engine", None)
    monkeypatch.setattr(_dbos, "_dbos_global_instance", MagicMock())
    constructor = MagicMock()
    monkeypatch.setattr(module, "DBOS", constructor)
    with pytest.raises(ValueError, match="already configured"):
        module.configure_notification_worker(value.services, "postgresql:///fixture")
    constructor.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("database", "foreign"),
        ("username", "foreign"),
        ("port", 5432),
        ("server_address", "127.0.0.2"),
        ("elevated", True),
        ("elevated", None),
    ],
)
def test_actual_system_engine_role_server_and_database_must_all_match(
    field: str, value: object
) -> None:
    business = witness()
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.one.return_value = (
        business.model_dump() | {field: value}
    )
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = (
        business.model_dump(include={"database", "username", "backend_start", "client_address"})
    )
    with pytest.raises(ValueError):
        module.require_system_role(engine, business)


@pytest.mark.parametrize("change", ["none", "missing", "start", "client", "database"])
def test_exact_live_business_backend_witness_is_required_before_system_launch(change: str) -> None:
    business = witness()
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.one.return_value = business.model_dump()
    peer = business.model_dump(include={"database", "username", "backend_start", "client_address"})
    if change == "start":
        peer["backend_start"] = business.backend_start + timedelta(seconds=1)
    elif change == "client":
        peer["client_address"] = "127.0.0.2"
    elif change == "database":
        peer["database"] = "foreign"
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = (
        None if change == "missing" else peer
    )
    if change == "none":
        module.require_system_role(engine, business)
        assert connection.execute.call_args.args[1] == {"pid": business.backend_pid}
    else:
        with pytest.raises(ValueError, match="system role or database"):
            module.require_system_role(engine, business)


@pytest.mark.parametrize(
    "system,allowed",
    [
        ("postgresql+psycopg://app@/fixture?host=/tmp/nexus-unit&port=55438", True),
        ("postgresql+psycopg://app@/fixture?host=/tmp/foreign&port=55438", False),
        ("postgresql+psycopg://app@/fixture?host=/tmp/nexus-unit&port=5432", False),
        ("postgresql+psycopg://other@/fixture?host=/tmp/nexus-unit&port=55438", False),
        ("postgresql+psycopg://app@/other?host=/tmp/nexus-unit&port=55438", False),
        ("postgresql+psycopg://app@/fixture?host=/tmp/nexus-unit,/tmp/other&port=55438", False),
        ("postgresql+psycopg://app@/fixture?service=foreign", False),
        ("postgresql+psycopg://app@/fixture", False),
    ],
)
async def test_configured_real_business_engine_requires_exact_explicit_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, system: str, allowed: bool
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    engine = create_async_engine(
        "postgresql+asyncpg://app@/fixture?host=/tmp/nexus-unit&port=55438"
    )
    cast(MagicMock, value.services.reads.factory).kw = {"bind": engine}
    try:
        if allowed:
            module.require_database_endpoint(value.services, make_url(system))
        else:
            with pytest.raises(ValueError, match="database endpoint"):
                module.require_database_endpoint(value.services, make_url(system))
    finally:
        await engine.dispose()


@pytest.mark.parametrize("deny", [False, True])
async def test_system_qualification_of_exact_engine_precedes_any_sdk_launch_or_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, deny: bool
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    engine = MagicMock()
    monkeypatch.setattr(module, "_services", value.services)
    monkeypatch.setattr(module, "_system_engine", engine)
    monkeypatch.setattr(module, "require_database_endpoint", MagicMock())
    session = cast(MagicMock, value.services.reads.factory).return_value.__aenter__.return_value
    business = witness()
    result = MagicMock()
    result.mappings.return_value.one.return_value = business.model_dump()
    session.execute = AsyncMock(return_value=result)
    order: list[str] = []

    def qualified(actual: object, observed: module.NotificationDatabaseWitness) -> None:
        assert actual is engine and observed == business
        cast(MagicMock, value.services.reads.factory).return_value.__aexit__.assert_not_awaited()
        order.append("system")
        if deny:
            raise ValueError("system denied")

    monkeypatch.setattr(module, "require_system_role", qualified)
    sdk = MagicMock()
    sdk.launch.side_effect = lambda: order.append("launch")
    sdk.register_queue_async = AsyncMock(side_effect=lambda *args, **kwargs: order.append("queue"))
    monkeypatch.setattr(module, "DBOS", sdk)
    if deny:
        with pytest.raises(ValueError, match="system denied"):
            await module.launch_notification_worker()
        assert order == ["system"]
        sdk.launch.assert_not_called()
        sdk.register_queue_async.assert_not_awaited()
    else:
        await module.launch_notification_worker()
        assert order == ["system", "launch", "queue"]
