"""Closed exact user-manager profiles; full execution authority remains separate and disabled."""

import hashlib
import json
from types import MappingProxyType
from typing import Literal

USER_PARENT_PROVIDER_VERSION: Literal["nexus.builder.user-parent-provider.v2"] = (
    "nexus.builder.user-parent-provider.v2"
)
SUPPORTED_USER_SYSTEMD_VERSION: Literal["261.2-1"] = "261.2-1"
_USER_PARENT_V2_DESCRIPTOR = {
    "schema": USER_PARENT_PROVIDER_VERSION,
    "manager": "fixed_local_user_bus",
    "version": SUPPORTED_USER_SYSTEMD_VERSION,
    "queries": (
        "manager_service_unix_uid",
        "manager_version",
        "exact_get_unit",
        "unit_five",
        "scope_eleven",
    ),
    "marker": ("present_1", "ENODATA_only_absent_user_manager"),
    "required": (
        "current_owned_uid",
        "delegate_true",
        "exact_user_hierarchy",
        "boot_invocation_mount_inode",
        "actual_controllers_exact_limits",
    ),
    "deadline": "active_enter_monotonic_plus_runtime_random_extra_zero",
    "total_io_us": 3_000_000,
    "query_reap_reserve_us": 100_000,
    "stdout_stderr_kernel_caps": (16_384, 4_096, 4_096),
}
USER_PARENT_METHOD_SHA256 = hashlib.sha256(
    json.dumps(
        _USER_PARENT_V2_DESCRIPTOR,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()


UserSystemdVersion = Literal["261.2-1", "262-1"]
UserParentProviderVersion = Literal[
    "nexus.builder.user-parent-provider.v2", "nexus.builder.user-parent-provider.v3"
]
SUPPORTED_USER_SYSTEMD_262_VERSION: Literal["262-1"] = "262-1"
USER_PARENT_262_PROVIDER_VERSION: Literal["nexus.builder.user-parent-provider.v3"] = (
    "nexus.builder.user-parent-provider.v3"
)
USER_PARENT_262_METHOD_SHA256 = hashlib.sha256(
    json.dumps(
        {
            **_USER_PARENT_V2_DESCRIPTOR,
            "schema": USER_PARENT_262_PROVIDER_VERSION,
            "version": SUPPORTED_USER_SYSTEMD_262_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()
USER_PARENT_PROFILES: MappingProxyType[str, tuple[UserParentProviderVersion, str]] = (
    MappingProxyType(
        {
            SUPPORTED_USER_SYSTEMD_VERSION: (
                USER_PARENT_PROVIDER_VERSION,
                USER_PARENT_METHOD_SHA256,
            ),
            SUPPORTED_USER_SYSTEMD_262_VERSION: (
                USER_PARENT_262_PROVIDER_VERSION,
                USER_PARENT_262_METHOD_SHA256,
            ),
        }
    )
)


def root_parent_profile(version: str) -> tuple[UserParentProviderVersion, str]:
    """Exact daemon versions select one descriptive profile, never an activation grant."""
    if type(version) is not str or version not in USER_PARENT_PROFILES:
        raise ValueError("User manager version has no closed root profile")
    return USER_PARENT_PROFILES[version]
