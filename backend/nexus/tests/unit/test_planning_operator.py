"""Explicit planning CLI modes cannot enter the disposable account or configuration path."""

import argparse
import importlib.util
import os
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "mode,extra",
    [
        ("planning-api", ["--worker-credential-fd", "8"]),
        ("planning-worker", ["--worker-credential-fd", "8"]),
        ("planning-migrate", ["--admin-database-fd", "9"]),
    ],
)
def test_planning_cli_dispatch_is_explicit_before_any_disposable_reads(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    extra: list[str],
) -> None:
    script = Path(__file__).resolve().parents[3] / "scripts/company_pilot.py"
    spec = importlib.util.spec_from_file_location("nexus_planning_cli_unit", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls: list[str] = []
    monkeypatch.setattr(module, "planning_mode", lambda args: calls.append(args.mode))
    monkeypatch.setattr(module, "config_at", lambda root: pytest.fail("Disposable account read"))
    args = [
        str(script),
        mode,
        "--planning-config",
        "/unused/planning.json",
        "--planning-config-sha",
        "a" * 64,
        *extra,
    ]
    monkeypatch.setattr(sys, "argv", args)
    module.main()
    assert calls == [mode]
    for invalid in (
        ["--root", "/unused/pilot"],
        ["--qualification-config", "/unused/qualification.json"],
        ["--qualification-config-sha", "b" * 64],
    ):
        monkeypatch.setattr(sys, "argv", [*args, *invalid])
        with pytest.raises(SystemExit):
            module.main()
    assert calls == [mode]


@pytest.mark.parametrize("mode", ["planning-api", "planning-worker", "planning-migrate"])
def test_planning_cli_requires_its_exact_inherited_descriptor(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    script = Path(__file__).resolve().parents[3] / "scripts/company_pilot.py"
    spec = importlib.util.spec_from_file_location("nexus_planning_cli_missing_unit", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "planning_mode", lambda args: pytest.fail("Missing descriptor"))
    args = [
        str(script),
        mode,
        "--planning-config",
        "/unused/planning.json",
        "--planning-config-sha",
        "a" * 64,
    ]
    for extra in (
        [],
        ["--admin-database-fd" if mode != "planning-migrate" else "--worker-credential-fd", "9"],
    ):
        monkeypatch.setattr(sys, "argv", [*args, *extra])
        with pytest.raises(SystemExit):
            module.main()


def operator_arguments(mode: str, config: Path, digest: str, fd: int) -> argparse.Namespace:
    return argparse.Namespace(
        mode=mode,
        root=None,
        qualification_config=None,
        qualification_config_sha=None,
        planning_config=config,
        planning_config_sha=digest,
        port=9188,
        host="127.0.0.1",
        sdk_receipt=None,
        prompt_password=False,
        database_name=None,
        docs_manifest=None,
        docs_manifest_sha=None,
        worker_credential_fd=fd if mode != "planning-migrate" else None,
        admin_database_fd=fd if mode == "planning-migrate" else None,
    )


def private_descriptor(path: Path, value: str) -> int:
    path.write_text(value)
    path.chmod(0o600)
    return os.open(path, os.O_RDONLY)


@pytest.mark.parametrize("mode", ["planning-api", "planning-worker"])
def test_actual_operator_builds_shared_graph_without_migrate_or_fresh_identity_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    import asyncio

    from dbos import DBOS
    from sqlalchemy.ext.asyncio import AsyncEngine

    from nexus.execution import planning_operator as module
    from nexus.execution.planning_application import PlanningApplication
    from nexus.tests.unit.test_planning_application import application_settings
    from nexus.tests.unit.test_planning_application_files import config_file

    path, digest = config_file(tmp_path)
    fd = private_descriptor(tmp_path / "opaque-actor-unit", "synthetic-expired-original-only")
    calls: list[str] = []
    monkeypatch.setattr(module, "settings", application_settings())
    monkeypatch.setattr(DBOS, "migrate", lambda *args, **kwargs: pytest.fail("Implicit migration"))

    def composed(actual: PlanningApplication) -> None:
        actual.require_composition()
        assert actual.planning.lifecycle is actual.management.planning_lifecycle
        assert not actual.runtime._operations
        assert not actual.lifecycle.pending_owners()
        calls.append(mode)

    def serve(
        actual: PlanningApplication,
        engine: AsyncEngine,
        args: argparse.Namespace,
        end_us: int,
    ) -> None:
        composed(actual)
        asyncio.run(engine.dispose())

    async def worker(
        actual: PlanningApplication,
        engine: AsyncEngine,
        system_url: str,
        end_us: int,
    ) -> None:
        composed(actual)
        await engine.dispose()

    monkeypatch.setattr(module, "_serve", serve)
    monkeypatch.setattr(module, "_run_worker", worker)
    module.planning_mode(operator_arguments(mode, path, digest, fd))
    assert calls == [mode]
    with pytest.raises(OSError):
        os.fstat(fd)


def test_migration_uses_only_same_target_explicit_admin_and_public_migrate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dbos import DBOS

    from nexus.execution import planning_operator as module
    from nexus.tests.unit.test_planning_application import application_settings
    from nexus.tests.unit.test_planning_application_files import config_file

    path, digest = config_file(tmp_path)
    injected = application_settings()
    admin = "postgresql+psycopg://unit_operator@/unit_only"
    fd = private_descriptor(tmp_path / "admin-unit", admin)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(module, "settings", injected)
    monkeypatch.setattr(
        module, "compose_planning_application", lambda *args: pytest.fail("Actor graph")
    )
    monkeypatch.setattr(
        module, "create_async_engine", lambda *args, **kwargs: pytest.fail("App engine")
    )
    monkeypatch.setattr(
        DBOS, "migrate", lambda url, *, application_role: calls.append((url, application_role))
    )
    module.planning_mode(operator_arguments("planning-migrate", path, digest, fd))
    assert calls == [(admin, "nexus_company_app")]
    with pytest.raises(OSError):
        os.fstat(fd)


def test_api_startup_retirement_failure_cannot_overwrite_original_preflight_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from collections.abc import Callable, Coroutine
    from typing import cast
    from unittest.mock import AsyncMock

    import uvicorn
    from litestar import Litestar
    from sqlalchemy.ext.asyncio import create_async_engine

    from nexus.execution import planning_operator as module
    from nexus.settings import settings
    from nexus.tests.unit.test_planning_application import TEST_SIGNER
    from nexus.tests.unit.test_planning_application_runtime import application

    app = application(tmp_path)
    engine = create_async_engine("postgresql+asyncpg://nexus_company_app@/unused_unit")
    original = ValueError("supplied native preflight denial")
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_SIGNER)
    monkeypatch.setattr(module, "preflight_planning_database", AsyncMock(side_effect=original))
    monkeypatch.setattr(
        module, "retire_planning_application", AsyncMock(side_effect=OSError("close"))
    )

    def run(api: Litestar, **kwargs: object) -> None:
        startup = cast(Callable[[], Coroutine[object, object, None]], api.on_startup[-1])
        asyncio.run(startup())

    monkeypatch.setattr(uvicorn, "run", run)
    with pytest.raises(ValueError) as caught:
        module._serve(app, engine, argparse.Namespace(host="127.0.0.1", port=9188), 1)
    assert caught.value is original
    assert vars(original)["_nexus_planning_secondary"] == "OSError"
    asyncio.run(engine.dispose())
