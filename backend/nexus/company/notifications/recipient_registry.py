"""Actual private server recipient configuration; no API keys, implicit role grants or sends."""

import asyncio
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Protocol, Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.company.management.base import ValueContract
from nexus.company.notifications.contracts import OwnerRecipientPolicy


class RecipientConfigurationError(ValueError):
    """Constant safe missing/current-policy block; no path, address or source content."""


class RecipientRegistryFile(ValueContract):
    policies: tuple[OwnerRecipientPolicy, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def exact_owner_configuration(self) -> Self:
        keys = [(row.company_id, row.owner_id) for row in self.policies]
        ids = [(row.company_id, row.policy_id) for row in self.policies]
        if len(set(keys)) != len(keys) or len(set(ids)) != len(ids):
            raise ValueError("Recipient registration identity must be unique")
        return self


class RegisteredOwnerRecipients(Protocol):
    """Server composition dependency, never a caller-provided policy or approval flag."""

    async def current(
        self, company_id: UUID, actual_owner_id: UUID, now: datetime
    ) -> OwnerRecipientPolicy | None: ...

    def require_current(self, prepared: OwnerRecipientPolicy, now: datetime) -> None:
        """Final bounded server-configuration pin check; cannot grant company/source access."""
        ...


class FileOwnerRecipients:
    """Read explicit operator-selected local file only; no credentials/config are created."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute():
            raise RecipientConfigurationError("Owner recipient configuration is unavailable")
        self._path = path

    def _read(self) -> RecipientRegistryFile:
        try:
            descriptor = os.open(self._path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            try:
                info = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_mode & 0o077
                    or (info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_size > 65_536)
                ):
                    raise ValueError("Unsupported configuration file")
                raw = os.read(descriptor, 65_537)
            finally:
                os.close(descriptor)
            if len(raw) > 65_536:
                raise ValueError("Oversized configuration file")
            return RecipientRegistryFile.model_validate_json(raw)
        except (OSError, ValueError):
            raise RecipientConfigurationError(
                "Owner recipient configuration is unavailable"
            ) from None

    def _current(
        self, company_id: UUID, owner_id: UUID, now: datetime
    ) -> OwnerRecipientPolicy | None:
        if now.utcoffset() is None:
            raise RecipientConfigurationError("Owner recipient configuration is unavailable")
        return next(
            (
                row
                for row in self._read().policies
                if row.company_id == company_id
                and row.owner_id == owner_id
                and row.registered_at <= now < row.expires_at
            ),
            None,
        )

    async def current(
        self, company_id: UUID, actual_owner_id: UUID, now: datetime
    ) -> OwnerRecipientPolicy | None:
        try:
            async with asyncio.timeout(3):
                return await asyncio.to_thread(self._current, company_id, actual_owner_id, now)
        except TimeoutError:
            raise RecipientConfigurationError(
                "Owner recipient configuration is unavailable"
            ) from None

    def require_current(self, prepared: OwnerRecipientPolicy, now: datetime) -> None:
        if self._current(prepared.company_id, prepared.owner_id, now) != prepared:
            raise RecipientConfigurationError("Owner recipient configuration is unavailable")
