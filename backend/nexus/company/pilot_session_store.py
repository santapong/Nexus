"""Operator-configured task-local credentials; no default account or application authority."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class PilotCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    principal_id: UUID
    company_id: UUID
    workspace_id: UUID
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=100)
    password_hash: str | None = None
    signup_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    signup_expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def credential_state(self) -> Self:
        if self.password_hash is None and (
            self.signup_sha256 is None or self.signup_expires_at is None
        ):
            raise ValueError("An unregistered task account requires an explicit invitation")
        return self


class PilotCredentialFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: str = "disposable-supervised-owner-uat-v1"
    accounts: tuple[PilotCredential, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def exact_accounts(self) -> Self:
        if len({row.email.casefold() for row in self.accounts}) != len(self.accounts):
            raise ValueError("Task account emails must be unique")
        if len({row.principal_id for row in self.accounts}) != len(self.accounts):
            raise ValueError("Task account principals must be unique")
        return self


def load_credentials(path: Path) -> PilotCredentialFile:
    return PilotCredentialFile.model_validate_json(private_record(path))


def record_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _private(value: os.stat_result, *, directory: bool = False) -> None:
    kind = stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode)
    if not kind or value.st_uid != os.geteuid() or (not directory and value.st_nlink != 1):
        raise ValueError("Private task record is unavailable")
    if value.st_mode & 0o077:
        raise ValueError("Task credential files require private permissions")


@contextmanager
def _parent(path: Path) -> Iterator[int]:
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        first = os.fstat(descriptor)
        _private(first, directory=True)
        named = path.parent.lstat()
        if (first.st_dev, first.st_ino) != (named.st_dev, named.st_ino):
            raise ValueError("Private task directory changed")
        yield descriptor
        named = path.parent.lstat()
        if (first.st_dev, first.st_ino) != (named.st_dev, named.st_ino):
            raise ValueError("Private task directory changed")
    finally:
        os.close(descriptor)


def _read(parent: int, name: str) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        first = os.fstat(descriptor)
        _private(first)
        if first.st_size <= 0 or first.st_size > 16384:
            raise ValueError("Task credential file exceeds its bound")
        raw = bytearray()
        while len(raw) <= 16384:
            part = os.read(descriptor, 16385 - len(raw))
            if not part:
                break
            raw.extend(part)
        if (
            len(raw) != first.st_size
            or record_signature(os.fstat(descriptor)) != record_signature(first)
            or record_signature(os.stat(name, dir_fd=parent, follow_symlinks=False))
            != record_signature(first)
        ):
            raise ValueError("Private task record changed")
        return bytes(raw)
    finally:
        os.close(descriptor)


def private_record(path: Path) -> bytes:
    """Read a bounded private config/account record without following replacement links."""
    try:
        with _parent(path) as parent:
            return _read(parent, path.name)
    except OSError as exc:
        raise ValueError("Private task record is unavailable") from exc


@contextmanager
def credential_writer(path: Path) -> Iterator[None]:
    """One nonblocking cross-process final writer; never hold this across password hashing.

    Every live signup/renewal writer must use this same retained lock inode. Bootstrap
    save_credentials is intentionally separate and does not initialize/reset a live account.
    """
    started = time.monotonic()
    try:
        with _parent(path) as parent:
            descriptor = os.open(
                ".accounts.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=parent,
            )
            try:
                first = os.fstat(descriptor)
                _private(first)
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if time.monotonic() - started >= 5 or record_signature(
                    os.stat(".accounts.lock", dir_fd=parent, follow_symlinks=False)
                ) != record_signature(first):
                    raise ValueError("Task credential writer changed or expired")
                yield
            finally:
                os.close(descriptor)
    except OSError as exc:
        raise ValueError("Task credential writer is unavailable") from exc


def save_credentials(path: Path, value: PilotCredentialFile) -> None:
    """Bootstrap writer; live changes require credential_writer and a final state check."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = json.dumps(value.model_dump(mode="json"), sort_keys=True).encode()
    if len(raw) > 16384:
        raise ValueError("Task credential file exceeds its bound")
    with _parent(path) as parent:
        if path.exists() or path.is_symlink():
            _read(parent, path.name)
        temporary = path.name + ".pending"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=parent)


def commit_signup(
    path: Path, expected: PilotCredentialFile, account: PilotCredential, password_hash: str
) -> PilotCredential:
    """Compare and commit after actual password hashing/current-access validation."""
    with credential_writer(path):
        if (
            load_credentials(path) != expected
            or account not in expected.accounts
            or account.password_hash is not None
            or account.signup_sha256 is None
            or account.signup_expires_at is None
            or account.signup_expires_at <= datetime.now(UTC)
            or not password_hash
        ):
            raise ValueError("Task session invitation changed or expired")
        current = account.model_copy(
            update={
                "password_hash": password_hash,
                "signup_sha256": None,
                "signup_expires_at": None,
            }
        )
        save_credentials(
            path,
            expected.model_copy(
                update={
                    "accounts": tuple(
                        current if row.principal_id == account.principal_id else row
                        for row in expected.accounts
                    )
                }
            ),
        )
        return current
