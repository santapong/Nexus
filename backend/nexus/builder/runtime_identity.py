"""Closed runtime versions and PhaseA selector identity; no live containment authority."""

import hashlib
import json
from typing import Literal

RuntimeRecipe = Literal["nexus.builder.runtime.v1", "nexus.builder.runtime.v2"]
RUNTIME_V1: Literal["nexus.builder.runtime.v1"] = "nexus.builder.runtime.v1"
RUNTIME_V2: Literal["nexus.builder.runtime.v2"] = "nexus.builder.runtime.v2"
V2_GLOBAL_ARGUMENTS: tuple[Literal["--cgroup-manager=cgroupfs"], ...] = (
    "--cgroup-manager=cgroupfs",
)
V2_RUN_ARGUMENTS: tuple[Literal["--cgroups=split"], ...] = ("--cgroups=split",)
RUNTIME_V2_METHOD_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "schema": "nexus.builder.runtime-selector.v2",
            "engine": "/usr/bin/podman",
            "global_arguments": V2_GLOBAL_ARGUMENTS,
            "run_arguments": V2_RUN_ARGUMENTS,
            "parent_source": "trusted_current_delegated_scope_only",
            "description_node_recipes": ("none", "nexus.builder.node.v4"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()


def is_legacy_runtime(value: object) -> bool:
    """Excluded default preserves exact old policy wire bytes and canonical hashes."""
    return value == RUNTIME_V1


def require_runtime_method(recipe: object, method_sha256: object) -> None:
    """Reject copied/unknown version and method values without normalizing them."""
    if not (
        (recipe == RUNTIME_V1 and method_sha256 is None)
        or (recipe == RUNTIME_V2 and method_sha256 == RUNTIME_V2_METHOD_SHA256)
    ):
        raise ValueError("Builder runtime version/method differs from the closed selector")
