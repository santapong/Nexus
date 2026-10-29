"""Explicit same-owner preview onboarding; never reset an initialized account.

Live use requires every running signup writer to have the shared final-commit
guard. A fresh CLI cannot make an older process's unguarded writer safe.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from nexus.company.pilot_config import PREVIEW_PROFILE, PilotConfig
from nexus.company.pilot_session_store import (
    PilotCredential,
    PilotCredentialFile,
    credential_writer,
    load_credentials,
    private_record,
    record_signature,
    save_credentials,
)


class OwnerInvitationState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: Literal["initialized", "expired_unused", "unexpired_unused"]
    has_password: bool
    expires_at: AwareDatetime | None


class OwnerInvitationRenewal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: Literal["renewed"] = "renewed"
    expires_at: AwareDatetime
    output_path: Path


def _config(root: Path) -> tuple[PilotConfig, bytes]:
    if not root.is_absolute() or root.resolve(strict=True) != root:
        raise ValueError("Preview root must be an exact private directory")
    raw = private_record(root / "config.json")
    config = PilotConfig.model_validate_json(raw)
    if config.profile != PREVIEW_PROFILE or config.account_file != root / "accounts.json":
        raise ValueError("Only the configured local owner preview may be renewed")
    return config, raw


def _owner(config: PilotConfig, stored: PilotCredentialFile) -> PilotCredential:
    owner = next((row for row in stored.accounts if row.principal_id == config.owner_id), None)
    if owner is None or (
        owner.email != "owner-uat@example.invalid"
        or owner.company_id != config.company_id
        or owner.workspace_id != config.workspace_id
    ):
        raise ValueError("Configured preview owner is unavailable")
    return owner


def _state(owner: PilotCredential) -> OwnerInvitationState:
    if owner.password_hash is not None:
        return OwnerInvitationState(
            state="initialized", has_password=True, expires_at=owner.signup_expires_at
        )
    if owner.signup_sha256 is None or owner.signup_expires_at is None:
        raise ValueError("Configured preview invitation is unavailable")
    return OwnerInvitationState(
        state="expired_unused"
        if owner.signup_expires_at <= datetime.now(UTC)
        else "unexpired_unused",
        has_password=False,
        expires_at=owner.signup_expires_at,
    )


def inspect_owner_invitation(root: Path) -> OwnerInvitationState:
    """Return metadata only; never return private values or create a writer lock."""
    config, raw = _config(root)
    result = _state(_owner(config, load_credentials(config.account_file)))
    if private_record(root / "config.json") != raw:
        raise ValueError("Preview configuration changed")
    return result


def _write_invitation(output: Path, secret: str) -> None:
    """Create a fresh private user file before adopting its invitation digest."""
    if not output.is_absolute() or output.parent.resolve(strict=True) != output.parent:
        raise ValueError("Invitation output requires an exact private directory")
    parent = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        before = os.fstat(parent)
        if (
            not stat.S_ISDIR(before.st_mode)
            or before.st_mode & 0o077
            or before.st_uid != os.geteuid()
        ):
            raise ValueError("Invitation output requires private permissions")
        descriptor = os.open(
            output.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write((secret + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
            saved = os.fstat(stream.fileno())
        named = os.stat(output.name, dir_fd=parent, follow_symlinks=False)
        current_parent = output.parent.lstat()
        if (
            saved.st_nlink != 1
            or saved.st_mode & 0o777 != 0o600
            or record_signature(saved) != record_signature(named)
            or private_record(output) != (secret + "\n").encode()
            or (before.st_dev, before.st_ino) != (current_parent.st_dev, current_parent.st_ino)
        ):
            raise ValueError("Invitation output changed")
        os.fsync(parent)
    finally:
        os.close(parent)


def renew_expired_owner_invitation(root: Path, output: Path) -> OwnerInvitationRenewal:
    """Renew only an expired unused invitation for the original configured owner.

    If publication of the new private user file precedes a later commit failure,
    that file remains an unadopted artifact. No success or automatic retry is emitted.
    Signup still rechecks current company access; renewal grants no membership.
    """
    config, raw = _config(root)
    with credential_writer(config.account_file):
        stored = load_credentials(config.account_file)
        owner = _owner(config, stored)
        if _state(owner).state != "expired_unused":
            raise ValueError("Owner invitation is not expired and unused")
        secret = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(hours=8)
        _write_invitation(output, secret)
        if (
            private_record(root / "config.json") != raw
            or load_credentials(config.account_file) != stored
            or owner.password_hash is not None
            or owner.signup_expires_at is None
            or owner.signup_expires_at > datetime.now(UTC)
        ):
            raise ValueError("Preview owner invitation changed")
        renewed = owner.model_copy(
            update={
                "signup_sha256": hashlib.sha256(secret.encode()).hexdigest(),
                "signup_expires_at": expires,
            }
        )
        save_credentials(
            config.account_file,
            stored.model_copy(
                update={
                    "accounts": tuple(
                        renewed if row.principal_id == owner.principal_id else row
                        for row in stored.accounts
                    )
                }
            ),
        )
        return OwnerInvitationRenewal(expires_at=expires, output_path=output)
