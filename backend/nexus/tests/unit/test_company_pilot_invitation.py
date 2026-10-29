"""Real private fixtures and process locks; never the owner's account or a database."""

# This one regression module exceeds400 lines to keep the complete private-file,
# real signup/crypto and process-lock cases within the approved five-file scope.

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from multiprocessing.connection import Connection
from pathlib import Path
from uuid import UUID

import pytest
from litestar.exceptions import NotAuthorizedException

from nexus.api.auth import hash_password
from nexus.company.access import PrincipalAccess, VerifiedIdentity, WorkAccess
from nexus.company.pilot_config import PilotConfig
from nexus.company.pilot_invitation import (
    inspect_owner_invitation,
    renew_expired_owner_invitation,
)
from nexus.company.pilot_session import PilotLogin, PilotSessionService, PilotSignup
from nexus.company.pilot_session_store import (
    PilotCredential,
    PilotCredentialFile,
    commit_signup,
    load_credentials,
    save_credentials,
)
from nexus.company.pilot_setup import new_config
from nexus.settings import settings

INVITATION = "synthetic-old-invitation-" + "x" * 40
PASSWORD = "synthetic-private-passphrase"


def case(tmp_path: Path, *, expired: bool = True) -> tuple[Path, PilotConfig]:
    root = tmp_path / "preview"
    root.mkdir(mode=0o700)
    config = new_config(
        root,
        None,
        profile="local-nexus-owner-preview-v1",
        database_name="nexus_company_test_owner_preview_invitation",
        docs_manifest=tmp_path / "documents.json",
        docs_manifest_sha256="a" * 64,
    )
    (root / "config.json").write_text(config.model_dump_json())
    (root / "config.json").chmod(0o600)
    owner = PilotCredential(
        principal_id=config.owner_id,
        company_id=config.company_id,
        workspace_id=config.workspace_id,
        email="owner-uat@example.invalid",
        display_name="Synthetic owner",
        signup_sha256=hashlib.sha256(INVITATION.encode()).hexdigest(),
        signup_expires_at=datetime.now(UTC) + timedelta(hours=-1 if expired else 1),
    )
    member = owner.model_copy(
        update={
            "principal_id": config.member_id,
            "email": "member-uat@example.invalid",
            "password_hash": "synthetic-already-initialized-member",
            "signup_sha256": None,
            "signup_expires_at": None,
        }
    )
    save_credentials(config.account_file, PilotCredentialFile(accounts=(owner, member)))
    (root / "browser-credentials.json").write_bytes(b"synthetic-do-not-open-or-change")
    return root, config


def owner_change(config: PilotConfig, **values: object) -> None:
    stored = load_credentials(config.account_file)
    owner, member = stored.accounts
    save_credentials(
        config.account_file,
        stored.model_copy(update={"accounts": (owner.model_copy(update=values), member)}),
    )


class Directory:
    """Supplied current directory delivery; password verification and JWT issuance are real."""

    def __init__(self, config: PilotConfig) -> None:
        self.config = config

    async def lookup_principal(
        self, identity: VerifiedIdentity, *, task_id: UUID, trace_id: UUID
    ) -> PrincipalAccess:
        return PrincipalAccess(
            company_id=self.config.company_id,
            workspace_id=identity.workspace_id,
            principal_id=identity.principal_id,
            owner_id=self.config.owner_id,
            membership_role="owner",
            company_active=True,
            workspace_active=True,
            principal_active=True,
            membership_active=True,
        )

    async def lookup_work(
        self, company_id: UUID, task_id: UUID, *, trace_id: UUID
    ) -> WorkAccess | None:
        return None


def session(config: PilotConfig, monkeypatch: pytest.MonkeyPatch) -> PilotSessionService:
    monkeypatch.setattr(settings, "jwt_secret_key", "unit-only-signing-key-" + "s" * 48)
    return PilotSessionService(Directory(config), config.account_file)


def test_expired_owner_renewal_changes_only_invitation_and_preserves_private_inputs(
    tmp_path: Path,
) -> None:
    root, config = case(tmp_path)
    before = load_credentials(config.account_file)
    browser = (root / "browser-credentials.json").read_bytes()
    configuration = (root / "config.json").read_bytes()
    state = inspect_owner_invitation(root)
    assert state.state == "expired_unused" and not state.has_password
    output = root / "new-invitation.txt"
    start = datetime.now(UTC)
    result = renew_expired_owner_invitation(root, output)
    secret = output.read_text().strip()
    after = load_credentials(config.account_file)
    assert result.state == "renewed" and result.output_path == output
    assert start + timedelta(hours=8) <= result.expires_at <= datetime.now(UTC) + timedelta(hours=8)
    assert secret != INVITATION and len(secret) >= 32
    assert after.accounts[0].signup_sha256 == hashlib.sha256(secret.encode()).hexdigest()
    assert after.accounts[0].model_dump(exclude={"signup_sha256", "signup_expires_at"}) == (
        before.accounts[0].model_dump(exclude={"signup_sha256", "signup_expires_at"})
    )
    assert after.accounts[1:] == before.accounts[1:]
    assert (root / "browser-credentials.json").read_bytes() == browser
    assert (root / "config.json").read_bytes() == configuration
    assert output.stat().st_mode & 0o777 == 0o600 and output.stat().st_nlink == 1
    assert inspect_owner_invitation(root).state == "unexpired_unused"
    with pytest.raises(ValueError):
        renew_expired_owner_invitation(root, root / "second.txt")
    assert not (root / "second.txt").exists()


@pytest.mark.asyncio
async def test_renewed_invitation_signup_once_then_real_password_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = case(tmp_path)
    output = root / "new.txt"
    renew_expired_owner_invitation(root, output)
    service = session(config, monkeypatch)
    data = PilotSignup(
        email="owner-uat@example.invalid", password=PASSWORD, invitation=output.read_text().strip()
    )
    token = await service.signup(data)
    assert token.user.user_id == config.owner_id and token.access_token
    assert inspect_owner_invitation(root).state == "initialized"
    before = config.account_file.read_bytes()
    with pytest.raises(NotAuthorizedException):
        await service.signup(data)
    with pytest.raises(ValueError):
        renew_expired_owner_invitation(root, root / "forbidden.txt")
    assert config.account_file.read_bytes() == before
    assert not (root / "forbidden.txt").exists()
    assert (await service.login(PilotLogin(email=data.email, password=PASSWORD))).user == token.user


@pytest.mark.parametrize(
    "change", ["password", "unexpired", "principal", "company", "workspace", "email"]
)
def test_renewal_refuses_completed_unexpired_or_foreign_owner(tmp_path: Path, change: str) -> None:
    root, config = case(tmp_path)
    changes: dict[str, dict[str, object]] = {
        "password": {"password_hash": "existing-password-must-survive"},
        "unexpired": {"signup_expires_at": datetime.now(UTC) + timedelta(hours=1)},
        "principal": {"principal_id": config.author_id},
        "company": {"company_id": config.goal_id},
        "workspace": {"workspace_id": config.goal_id},
        "email": {"email": "foreign@example.invalid"},
    }
    owner_change(config, **changes[change])
    before = config.account_file.read_bytes()
    with pytest.raises(ValueError):
        renew_expired_owner_invitation(root, root / "denied.txt")
    assert config.account_file.read_bytes() == before and not (root / "denied.txt").exists()


@pytest.mark.parametrize(
    "fault", ["output_exists", "output_parent", "account_mode", "hardlink", "symlink"]
)
def test_private_path_failure_preserves_account(tmp_path: Path, fault: str) -> None:
    root, config = case(tmp_path)
    output = root / "new.txt"
    if fault == "output_exists":
        output.write_text("preserve-existing-output")
    elif fault == "output_parent":
        output = tmp_path / "public" / "new.txt"
        output.parent.mkdir(mode=0o755)
        output.parent.chmod(0o755)  # The runner's077 umask must not hide this negative.
    elif fault == "account_mode":
        config.account_file.chmod(0o644)
    elif fault == "hardlink":
        os.link(config.account_file, root / "alias")
    else:
        target = root / "original.json"
        config.account_file.rename(target)
        config.account_file.symlink_to(target)
    before = config.account_file.read_bytes()
    with pytest.raises((ValueError, OSError)):
        renew_expired_owner_invitation(root, output)
    assert config.account_file.read_bytes() == before
    if fault == "output_exists":
        assert output.read_text() == "preserve-existing-output"
    else:
        assert not output.exists()


def hold_writer(path: Path, ready: Connection, release: Connection) -> None:
    descriptor = os.open(path.parent / ".accounts.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ready.send(True)
        if not release.poll(5):
            raise RuntimeError("Test parent did not release its own child")
        release.recv()
    finally:
        os.close(descriptor)
        ready.close()
        release.close()


def test_actual_other_process_writer_lock_denies_then_releases(tmp_path: Path) -> None:
    root, config = case(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    release_receive, release_send = ctx.Pipe(duplex=False)
    child = ctx.Process(target=hold_writer, args=(config.account_file, send, release_receive))
    child.start()
    try:
        assert receive.poll(5) and receive.recv() is True
        before = config.account_file.read_bytes()
        with pytest.raises(ValueError):
            renew_expired_owner_invitation(root, root / "locked.txt")
        assert config.account_file.read_bytes() == before and not (root / "locked.txt").exists()
    finally:
        release_send.send(True)
        child.join(5)
        if child.is_alive():
            child.terminate()
            child.join(5)
        receive.close()
        send.close()
        release_receive.close()
        release_send.close()
    assert child.exitcode == 0
    renew_expired_owner_invitation(root, root / "released.txt")


def test_stale_signup_snapshot_cannot_replace_renewed_invitation(tmp_path: Path) -> None:
    root, config = case(tmp_path)
    snapshot = load_credentials(config.account_file)
    renew_expired_owner_invitation(root, root / "new.txt")
    before = config.account_file.read_bytes()
    with pytest.raises(ValueError):
        commit_signup(config.account_file, snapshot, snapshot.accounts[0], "new-password-hash")
    assert config.account_file.read_bytes() == before


@pytest.mark.asyncio
async def test_signup_hash_and_real_expiry_allow_renewal_without_password_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nexus.company.pilot_session as implementation

    root, config = case(tmp_path, expired=False)
    service = session(config, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original = hash_password

    def blocked(password: str) -> str:
        entered.set()
        assert release.wait(8)
        return original(password)

    monkeypatch.setattr(implementation, "hash_password", blocked)
    expiry = datetime.now(UTC) + timedelta(seconds=2)
    owner_change(config, signup_expires_at=expiry)
    operation = asyncio.create_task(
        service.signup(
            PilotSignup(email="owner-uat@example.invalid", password=PASSWORD, invitation=INVITATION)
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        while datetime.now(UTC) <= expiry:
            await asyncio.sleep(0.02)
        # The real hash is still owned, but no writer lock is held across it.
        output = root / "concurrent-new.txt"
        await asyncio.to_thread(renew_expired_owner_invitation, root, output)
        after = config.account_file.read_bytes()
    finally:
        release.set()
    with pytest.raises(NotAuthorizedException):
        await operation
    assert config.account_file.read_bytes() == after
    assert not load_credentials(config.account_file).accounts[0].password_hash


def test_failed_account_publication_retains_old_credentials_and_unadopted_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nexus.company.pilot_invitation as implementation

    root, config = case(tmp_path)
    before = config.account_file.read_bytes()

    def failed(path: Path, value: PilotCredentialFile) -> None:
        raise OSError("synthetic account replacement failure")

    monkeypatch.setattr(implementation, "save_credentials", failed)
    output = root / "unadopted.txt"
    with pytest.raises(ValueError, match="writer is unavailable"):
        renew_expired_owner_invitation(root, output)
    assert config.account_file.read_bytes() == before
    assert output.exists() and output.stat().st_mode & 0o777 == 0o600


def test_truncated_new_private_output_is_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = case(tmp_path)
    before = config.account_file.read_bytes()
    original = os.fsync

    def truncate_output(descriptor: int) -> None:
        if os.fstat(descriptor).st_size == 44:
            os.ftruncate(descriptor, 1)
        original(descriptor)

    monkeypatch.setattr(os, "fsync", truncate_output)
    with pytest.raises(ValueError):
        renew_expired_owner_invitation(root, root / "truncated.txt")
    assert config.account_file.read_bytes() == before


@pytest.mark.asyncio
async def test_cancelled_signup_retains_actual_commit_until_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nexus.company.pilot_session as implementation

    root, config = case(tmp_path, expired=False)
    service = session(config, monkeypatch)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = commit_signup

    def blocked(*args: object, **kwargs: object) -> PilotCredential:
        entered.set()
        assert release.wait(5)
        try:
            return original(
                config.account_file,
                load_credentials(config.account_file),
                load_credentials(config.account_file).accounts[0],
                "already-hashed-test-password",
            )
        finally:
            finished.set()

    monkeypatch.setattr(implementation, "commit_signup", blocked)
    operation = asyncio.create_task(
        service.signup(
            PilotSignup(email="owner-uat@example.invalid", password=PASSWORD, invitation=INVITATION)
        )
    )
    assert await asyncio.to_thread(entered.wait, 5)
    operation.cancel()
    await asyncio.sleep(0)
    operation.cancel()
    assert not operation.done() and not finished.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert finished.is_set() and inspect_owner_invitation(root).has_password


def test_cli_metadata_only_and_generic_denials(tmp_path: Path) -> None:
    root, config = case(tmp_path)
    command = [sys.executable, "-m", "scripts.company_pilot_invitation"]
    backend = Path(__file__).resolve().parents[3]
    inspected = subprocess.run(
        [*command, "inspect-owner", "--root", str(root)],
        cwd=backend,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert inspected.returncode == 0 and json.loads(inspected.stdout)["state"] == "expired_unused"
    output = root / "cli-new.txt"
    renewed = subprocess.run(
        [*command, "renew-expired-owner", "--root", str(root), "--output", str(output)],
        cwd=backend,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert renewed.returncode == 0 and json.loads(renewed.stdout)["state"] == "renewed"
    secret = output.read_text().strip()
    forbidden = subprocess.run(
        [*command, "renew-expired-owner", "--root", str(root), "--output", str(root / "again.txt")],
        cwd=backend,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert forbidden.returncode != 0 and "Traceback" not in forbidden.stderr
    streams = (
        inspected.stdout
        + inspected.stderr
        + renewed.stdout
        + renewed.stderr
        + forbidden.stdout
        + forbidden.stderr
    )
    assert secret not in streams and INVITATION not in streams
    digest = load_credentials(config.account_file).accounts[0].signup_sha256
    assert digest is not None and digest not in streams
