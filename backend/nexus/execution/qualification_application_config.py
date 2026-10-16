"""One immutable private operator configuration; it grants no model/owner authority."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nexus.builder.contained_query import clock_us
from nexus.company.management.goals import GoalRevisionRef
from nexus.core.llm.qualification_contracts import QualificationRecipe

MAX_CONFIG = 65_536
NO_PROVIDER_VERSIONS = frozenset({"nexus-preview-no-provider-v1", "uat-offline-v1"})


def current(end_us: int) -> None:
    if type(end_us) is not int or not 0 < clock_us() < end_us:
        raise TimeoutError("Qualification operator deadline expired")


class QualificationApplicationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)
    schema_version: Literal["nexus.qualification.application.v1"] = (
        "nexus.qualification.application.v1"
    )
    goal: GoalRevisionRef
    owner_id: UUID
    workspace_id: UUID
    worker_id: UUID
    evidence_root: Path
    recipes: tuple[QualificationRecipe, ...] = Field(min_length=1, max_length=32)
    allocation_usd: Decimal = Decimal("1.000000")

    @model_validator(mode="after")
    def exact_application(self) -> Self:
        if (
            self.allocation_usd != Decimal(1)
            or not self.evidence_root.is_absolute()
            or any(
                row.goal != self.goal
                or row.target.price is None
                or row.target.price.version in NO_PROVIDER_VERSIONS
                for row in self.recipes
            )
            or len({row.sdk_pins.model_dump_json() for row in self.recipes}) != 1
        ):
            raise ValueError(
                "Qualification requires one fixed goal/allowance and actual priced public recipes"
            )
        return self


def _signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _parent_signature(value: os.stat_result) -> tuple[int, ...]:
    # Private directory identity/mode stay fixed while legitimate data children appear.
    return value.st_dev, value.st_ino, value.st_uid, value.st_mode


def read_owned_fd(fd: int, limit: int, *, end_us: int) -> tuple[bytes, tuple[int, ...]]:
    """Consume/close the actual inherited ordinary descriptor; no path/secret reflection."""
    if type(fd) is not int or fd < 0 or limit not in {4096, 16384, MAX_CONFIG}:
        raise ValueError("Qualification owned descriptor is unavailable")
    first: BaseException | None = None
    before: os.stat_result | None = None
    result = b""
    try:
        current(end_us)
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or not 0 < before.st_size <= limit
            or os.lseek(fd, 0, os.SEEK_CUR) != 0
        ):
            raise ValueError("Qualification owned descriptor is unavailable")
        parts = []
        length = 0
        while True:
            current(end_us)
            raw = os.read(fd, min(4096, limit + 1 - length))
            if not raw:
                break
            parts.append(raw)
            length += len(raw)
            if length > limit:
                raise ValueError("Qualification owned descriptor exceeds its bound")
        if length != before.st_size or _signature(os.fstat(fd)) != _signature(before):
            raise ValueError("Qualification owned descriptor changed")
        result = b"".join(parts)
    except BaseException as error:
        first = error
    finally:
        try:
            os.close(fd)
        except BaseException as secondary:
            if first is None:
                first = secondary
            else:
                first.__dict__["_nexus_qualification_secondary"] = type(secondary).__name__
    if first is not None:
        raise first
    assert before is not None
    current(end_us)
    return result, _signature(before)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Qualification configuration contains duplicate fields")
        result[name] = value
    return result


def _nonfinite(_: str) -> None:
    raise ValueError("Qualification configuration contains a nonfinite value")


@dataclass(frozen=True)
class QualificationConfigSnapshot:
    value: QualificationApplicationConfig
    path: Path
    sha256: str
    signature: tuple[int, ...]
    parent_signature: tuple[int, ...]

    def require_current(self, *, end_us: int) -> None:
        if load_qualification_config(self.path, self.sha256, end_us=end_us) != self:
            raise ValueError("Qualification original configuration changed")


def load_qualification_config(
    path: Path, expected_sha256: str, *, end_us: int
) -> QualificationConfigSnapshot:
    current(end_us)
    if (
        type(expected_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or not path.is_absolute()
        or path.resolve() != path
    ):
        raise ValueError("Qualification exact configuration is unavailable")
    parent = path.parent.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_IMODE(parent.st_mode) != 0o700
        or parent.st_uid != os.geteuid()
    ):
        raise ValueError("Qualification configuration directory is unavailable")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    raw, signature = read_owned_fd(fd, MAX_CONFIG, end_us=end_us)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Qualification configuration hash differs")
    json.loads(
        raw,
        object_pairs_hook=_unique,
        parse_constant=_nonfinite,
    )
    value = QualificationApplicationConfig.model_validate_json(raw)
    if (
        _parent_signature(path.parent.stat(follow_symlinks=False)) != _parent_signature(parent)
        or _signature(path.stat(follow_symlinks=False)) != signature
    ):
        raise ValueError("Qualification configuration namespace changed")
    current(end_us)
    return QualificationConfigSnapshot(
        value, path, expected_sha256, signature, _parent_signature(parent)
    )
