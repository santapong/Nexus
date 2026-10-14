"""Operator-configured task-local credentials; no default account or application authority."""

from __future__ import annotations

import json
import os
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
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Private task credentials are unavailable")
    if path.stat().st_mode & 0o077 or path.parent.stat().st_mode & 0o077:
        raise ValueError("Task credential files require private permissions")
    if path.stat().st_size > 16384:
        raise ValueError("Task credential file exceeds its bound")
    return PilotCredentialFile.model_validate_json(path.read_bytes())


def save_credentials(path: Path, value: PilotCredentialFile) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.parent.stat().st_mode & 0o077 or path.is_symlink():
        raise ValueError("Task credential directory must be private")
    temporary = path.with_suffix(".pending")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value.model_dump(mode="json"), stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
