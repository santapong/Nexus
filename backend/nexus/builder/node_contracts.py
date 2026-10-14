"""Typed public Node/tool/cache pins contain no portable paths or authority claims."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from nexus.builder.contracts import BuilderValue, Digest, Symbol


class NodeRuntimeInputs(BuilderValue):
    recipe: Literal["nexus.builder.node.v1", "nexus.builder.node.v2"] = "nexus.builder.node.v2"
    architecture: Literal["amd64"] = "amd64"
    tool_symbol: Symbol
    cache_symbol: Symbol
    image_id: Digest
    node_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    pnpm_version: Literal["9.12.0"]
    pnpm_archive_sha256: Digest
    pnpm_integrity: str = Field(pattern=r"^sha512-[A-Za-z0-9+/]{86}==$", max_length=100)
    cache_archive_sha256: Digest
    cache_manifest_sha256: Digest
    lock_sha256: Digest
    command_recipe_sha256: Digest


def absent(value: object) -> bool:
    return value is None
