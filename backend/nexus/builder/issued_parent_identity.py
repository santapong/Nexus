"""Separate post-seal algorithm identity; default strict user-parent v2 stays unchanged."""

import hashlib
import json
from types import MappingProxyType
from typing import Final, Literal

from nexus.builder.user_parent_identity import (
    SUPPORTED_USER_SYSTEMD_262_VERSION,
    SUPPORTED_USER_SYSTEMD_VERSION,
    USER_PARENT_262_METHOD_SHA256,
    USER_PARENT_262_PROVIDER_VERSION,
)

ISSUED_PARENT_VERSION: Final = "nexus.builder.user-issued-parent-provider.v1"
_ISSUED_PARENT_V1_DESCRIPTOR = {
    "schema": ISSUED_PARENT_VERSION,
    "phase": "after_actual_owned_spawn_and_fixed_full_id_seal_only",
    "preissue": "unchanged_exact_root",
    "placement": "exact_original_scope_runtime_leaf",
    "ownership": (
        "opaque_owned_start_and_discovery_seal_current_distinct_collector_runtime_pid_start"
    ),
    "directory": "nofollow_held_root_runtime_mount_device_inode_uid_visible_recheck",
    "limits": "unchanged_actual_outer_root_and_original_deadline",
    "facts": "actual_self_path_never_rewritten_stable_issued_identity",
}
ISSUED_PARENT_METHOD_SHA256 = hashlib.sha256(
    json.dumps(
        _ISSUED_PARENT_V1_DESCRIPTOR,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()


IssuedParentProviderVersion = Literal[
    "nexus.builder.user-issued-parent-provider.v1", "nexus.builder.user-issued-parent-provider.v2"
]
ISSUED_PARENT_262_VERSION: Literal["nexus.builder.user-issued-parent-provider.v2"] = (
    "nexus.builder.user-issued-parent-provider.v2"
)
ISSUED_PARENT_262_METHOD_SHA256 = hashlib.sha256(
    json.dumps(
        {
            **_ISSUED_PARENT_V1_DESCRIPTOR,
            "schema": ISSUED_PARENT_262_VERSION,
            "manager_version": SUPPORTED_USER_SYSTEMD_262_VERSION,
            "root_provider": (USER_PARENT_262_PROVIDER_VERSION, USER_PARENT_262_METHOD_SHA256),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()
ISSUED_PARENT_PROFILES: MappingProxyType[str, tuple[IssuedParentProviderVersion, str]] = (
    MappingProxyType(
        {
            SUPPORTED_USER_SYSTEMD_VERSION: (ISSUED_PARENT_VERSION, ISSUED_PARENT_METHOD_SHA256),
            SUPPORTED_USER_SYSTEMD_262_VERSION: (
                ISSUED_PARENT_262_VERSION,
                ISSUED_PARENT_262_METHOD_SHA256,
            ),
        }
    )
)


def issued_parent_profile(version: str) -> tuple[IssuedParentProviderVersion, str]:
    """Post-seal profile selection preserves the exact manager and root-method binding."""
    if type(version) is not str or version not in ISSUED_PARENT_PROFILES:
        raise ValueError("User manager version has no closed issued profile")
    return ISSUED_PARENT_PROFILES[version]
