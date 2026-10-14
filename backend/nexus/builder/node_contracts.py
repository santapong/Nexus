"""Typed public Node/tool/cache pins contain no portable paths or authority claims."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from nexus.builder.contracts import BuilderValue, Digest, Symbol
from nexus.builder.csv_report_contracts import CsvRegressionPins


class NodeRuntimeInputs(BuilderValue):
    recipe: Literal[
        "nexus.builder.node.v1",
        "nexus.builder.node.v2",
        "nexus.builder.node.v3",
        "nexus.builder.node.v4",
    ] = "nexus.builder.node.v3"
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
    csv_regression: CsvRegressionPins | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def exact_csv_recipe(self) -> Self:
        if (self.recipe == "nexus.builder.node.v4") != (self.csv_regression is not None):
            raise ValueError("Only Node v4 requires its exact reviewed CSV regression pins")
        return self


def absent(value: object) -> bool:
    return value is None
