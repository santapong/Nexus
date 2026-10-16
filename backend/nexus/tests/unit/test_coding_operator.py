"""Unavailable actor is a closed denial, never a token, owner substitute or boot gate."""

import argparse
import asyncio
import hashlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest
from dbos import DBOS
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.company.notifications.worker_identity import WorkerIdentityDeniedError
from nexus.execution.coding_application import CodingApplication
from nexus.execution.coding_operator import UnavailableCredential, validate_coding_arguments
from nexus.tests.unit.coding_application_fixture import configuration
from nexus.tests.unit.test_planning_application import application_settings


def arguments(mode: str, path: Path, digest: str) -> argparse.Namespace:
    return argparse.Namespace(
        mode=mode,
        coding_config=path,
        coding_config_sha=digest,
        planning_credential_fd=None,
        coding_credential_fd=None,
        admin_database_fd=None,
        host="127.0.0.1",
        port=5189,
    )


def config_file(root: Path) -> tuple[Path, str]:
    parent = root / "operator"
    parent.mkdir(mode=0o700)
    path = parent / "coding.json"
    raw = configuration(root / "data").model_dump_json(by_alias=True).encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    return path, hashlib.sha256(raw).hexdigest()


async def test_missing_role_credential_returns_no_token_or_witness() -> None:
    with pytest.raises(WorkerIdentityDeniedError):
        await UnavailableCredential().credential()


@pytest.mark.parametrize("mode", ["coding-api", "coding-worker"])
def test_owner_history_boot_without_actor_fd_never_migrates_or_reads_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from nexus.execution import coding_operator as module

    path, digest = config_file(tmp_path)
    calls = []
    monkeypatch.setattr(module, "settings", application_settings())
    monkeypatch.setattr(DBOS, "migrate", lambda *a, **k: pytest.fail("Implicit migration"))

    def composed(actual: CodingApplication) -> None:
        actual.require_composition()
        assert type(actual.services.identities._credentials) is UnavailableCredential
        assert type(actual.planning.runtime.identities._credentials) is UnavailableCredential
        assert not actual.services._operations and not actual.lifecycle.pending_owners()
        calls.append(mode)

    def serve(
        actual: CodingApplication, engine: AsyncEngine, args: argparse.Namespace, end: int
    ) -> None:
        composed(actual)
        asyncio.run(engine.dispose())

    async def worker(
        actual: CodingApplication, engine: AsyncEngine, system_url: str, end: int
    ) -> None:
        composed(actual)
        await engine.dispose()

    monkeypatch.setattr(module, "_serve", serve)
    monkeypatch.setattr(module, "_run_worker", worker)
    module.coding_mode(arguments(mode, path, digest))
    assert calls == [mode]


@pytest.mark.parametrize("mode", ["coding-api", "coding-worker", "coding-migrate"])
def test_actor_and_admin_descriptor_modes_are_closed(mode: str) -> None:
    args = arguments(mode, Path("/unused/private.json"), "a" * 64)
    if mode == "coding-migrate":
        with pytest.raises(ValueError):
            validate_coding_arguments(args)
        args.admin_database_fd = 9
        validate_coding_arguments(args)
        args.coding_credential_fd = 8
    else:
        validate_coding_arguments(args)
        args.admin_database_fd = 9
    with pytest.raises(ValueError):
        validate_coding_arguments(args)
    args = arguments(mode, Path("/unused/private.json"), "a" * 64)
    args.planning_credential_fd = args.coding_credential_fd = 8
    with pytest.raises(ValueError):
        validate_coding_arguments(args)


def test_only_same_target_explicit_admin_fd_enters_public_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.execution import coding_operator as module

    path, digest = config_file(tmp_path)
    admin = "postgresql+psycopg://unit_operator@/unit_only"
    secret = tmp_path / "admin-fd"
    secret.write_text(admin)
    secret.chmod(0o600)
    fd = os.open(secret, os.O_RDONLY)
    args = arguments("coding-migrate", path, digest)
    args.admin_database_fd = fd
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(module, "settings", application_settings())
    monkeypatch.setattr(
        module, "create_async_engine", lambda *a, **k: pytest.fail("Migration made app engine")
    )
    monkeypatch.setattr(
        DBOS, "migrate", lambda url, *, application_role: calls.append((url, application_role))
    )
    module.coding_mode(args)
    assert calls == [(admin, "nexus_company_app")]
    with pytest.raises(OSError):
        os.fstat(fd)


@pytest.mark.parametrize("mode", ["coding-api", "coding-worker", "coding-migrate"])
def test_dedicated_cli_has_no_disposable_account_or_cross_profile_input(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    script = Path(__file__).resolve().parents[3] / "scripts/company_coding.py"
    spec = importlib.util.spec_from_file_location("nexus_coding_cli_unit", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module, "coding_mode", lambda args: calls.append(args))
    args = [
        str(script),
        "--mode",
        mode,
        "--coding-config",
        "/unused/private.json",
        "--coding-config-sha",
        "a" * 64,
    ]
    monkeypatch.setattr(sys, "argv", args)
    module.main()
    assert len(calls) == 1 and calls[0].host == "127.0.0.1"
    assert calls[0].planning_credential_fd is calls[0].coding_credential_fd is None
    for foreign in ("--root", "--planning-config", "--qualification-config", "--actor-id"):
        monkeypatch.setattr(sys, "argv", [*args, foreign, "/not-allowed"])
        with pytest.raises(SystemExit):
            module.main()
    assert len(calls) == 1
