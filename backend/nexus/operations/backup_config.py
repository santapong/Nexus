"""Explicit disabled local operator configuration; no URL, password or caller selector."""

import re
from pathlib import Path
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from nexus.company.management.base import ValueContract

PG_BIN = Path("/usr/lib/postgresql/17/bin")
MAX_BYTES = 268_435_456


class LocalPostgresBackupConfig(ValueContract):
    enabled: bool = False
    company_id: UUID
    socket: Path
    port: int = Field(ge=1, le=65535)
    admin_user: str
    source_database: str
    target_database: str
    restore_root: Path
    company_revision: str = "company_015"
    max_bytes: int = Field(default=MAX_BYTES, ge=1, le=MAX_BYTES)
    timeout_seconds: int = Field(default=60, ge=1, le=180)

    @field_validator("admin_user", "source_database", "target_database")
    @classmethod
    def exact_local_name(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
            raise ValueError("Local backup identity is unavailable")
        return value

    @model_validator(mode="after")
    def distinct_local_scope(self) -> "LocalPostgresBackupConfig":
        if (
            self.source_database == self.target_database
            or not self.socket.is_absolute()
            or not self.restore_root.is_absolute()
            or not re.fullmatch(r"company_[0-9]{3}", self.company_revision)
        ):
            raise ValueError("Local backup scope is unavailable")
        return self

    def require_enabled(self) -> None:
        if not self.enabled:
            raise ValueError("Local backup operator is disabled")
