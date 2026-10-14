"""Exact public dependency cache descriptions grant no package-manager networking."""

from __future__ import annotations

import hashlib
from typing import Literal, Self
from urllib.parse import quote

from pydantic import Field, model_validator

from nexus.builder.contracts import BuilderValue, Digest


class PublicPackage(BuilderValue):
    name: str = Field(pattern=r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$", max_length=160)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$", max_length=100)
    integrity: str = Field(pattern=r"^sha512-[A-Za-z0-9+/]{86}==$", max_length=100)
    url: str

    @property
    def filename(self) -> str:
        return hashlib.sha256(f"{self.name}@{self.version}".encode()).hexdigest() + ".tgz"

    @model_validator(mode="after")
    def exact_public_url(self) -> Self:
        if self.url != package_url(self.name, self.version):
            raise ValueError("Public package URL differs from its exact registry/name/version")
        return self


def package_url(name: str, version: str) -> str:
    leaf = name.rsplit("/", 1)[-1]
    path = quote(name, safe="@/")
    archive = quote(leaf, safe="") + "-" + quote(version, safe="") + ".tgz"
    return f"https://registry.npmjs.org/{path}/-/{archive}"


class PublicPackageManifest(BuilderValue):
    recipe: Literal["nexus.builder.public-cache.v1"] = "nexus.builder.public-cache.v1"
    lock_sha256: Digest
    platform: Literal["linux/amd64"] = "linux/amd64"
    cpu: Literal["x64"] = "x64"
    libc: Literal["glibc"] = "glibc"
    packages: tuple[PublicPackage, ...] = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def ordered_unique(self) -> Self:
        keys = tuple((row.name, row.version) for row in self.packages)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("Public cache package set must be stable, ordered and unique")
        return self
