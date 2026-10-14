"""Resolve only frozen public registry integrity entries and literal platform constraints."""

from __future__ import annotations

import hashlib

import yaml  # type: ignore[import-untyped]  # Existing safe YAML loader has no local stub package.
from pydantic import BaseModel, ConfigDict, Field

from nexus.builder.public_package_contracts import PublicPackage, PublicPackageManifest, package_url


class Resolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    integrity: str


class LockedPackage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    resolution: Resolution
    os: tuple[str, ...] = ()
    cpu: tuple[str, ...] = ()
    libc: tuple[str, ...] = ()


class Lock(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    lockfile_version: str = Field(alias="lockfileVersion")
    packages: dict[str, LockedPackage]


def public_manifest(raw: bytes, expected_sha256: str) -> PublicPackageManifest:
    if not 0 < len(raw) <= 2_097_152 or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Public cache lock bytes differ from the frozen nominated source")
    lock = Lock.model_validate(yaml.safe_load(raw))
    if lock.lockfile_version != "9.0" or len(lock.packages) > 1024:
        raise ValueError("Public cache lock version/package bound is unsupported")
    selected = []
    for key, value in lock.packages.items():
        if not platform_matches(value):
            continue
        name, separator, version = key.rpartition("@")
        if not separator:
            raise ValueError("Public cache package version is unresolved")
        selected.append(
            PublicPackage(
                name=name,
                version=version,
                integrity=value.resolution.integrity,
                url=package_url(name, version),
            )
        )
    return PublicPackageManifest(
        lock_sha256=expected_sha256,
        packages=tuple(sorted(selected, key=lambda row: (row.name, row.version))),
    )


def platform_matches(value: LockedPackage) -> bool:
    for allowed, current in ((value.os, "linux"), (value.cpu, "x64"), (value.libc, "glibc")):
        if any(item.startswith("!") for item in allowed):
            raise ValueError(
                "Negative platform constraints require a separately qualified resolver"
            )
        if allowed and current not in allowed:
            return False
    return True
