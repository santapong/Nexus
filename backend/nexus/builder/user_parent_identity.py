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
    "nexus.builder.user-parent-provider.v2",
    "nexus.builder.user-parent-provider.v3",
    "nexus.builder.user-parent-provider.v4",
    "nexus.builder.user-parent-provider.v5",
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
    """Retained exact profiles identify historical reads, never a fresh issue allowance."""
    if type(version) is not str or version not in USER_PARENT_PROFILES:
        raise ValueError("User manager version has no closed root profile")
    return USER_PARENT_PROFILES[version]


_MOUNTINFO64_DESCRIPTOR = {
    "schema": "nexus.builder.mountinfo-reader.v2",
    "mountinfo_bytes": 65_536,
    "other_kernel_file_bytes": 4_096,
    "overflow": "at_most_65537_actual_bytes_never_an_invented_total",
    "read": "fixed_numeric_self_proc_fd_nofollow_nonblock_cloexec_finally_close",
    "parser": "ascii_single_cgroup2_root_slash_target_sys_fs_cgroup_rw_canonical_id",
    "namespace": "held_fixed_proc_mnt_namespace_device_inode_visible_before_after",
    "collection": "repeat_uid_boot_self_path_held_visible_mount_group_fd_mount_id",
    "metadata": "same_call_immutable_length_sha_status_original_exception_no_raw_body",
    "deadline": "unchanged_original_io_and_job_end_no_hard_thread_cancellation_claim",
}
MOUNTINFO64_METHOD_SHA256 = hashlib.sha256(
    json.dumps(_MOUNTINFO64_DESCRIPTOR, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
CURRENT_USER_PARENT_PROVIDER_VERSION: Literal["nexus.builder.user-parent-provider.v4"] = (
    "nexus.builder.user-parent-provider.v4"
)
CURRENT_USER_PARENT_262_PROVIDER_VERSION: Literal["nexus.builder.user-parent-provider.v5"] = (
    "nexus.builder.user-parent-provider.v5"
)


def _current_method(version: str, schema: UserParentProviderVersion) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                **_USER_PARENT_V2_DESCRIPTOR,
                "schema": schema,
                "version": version,
                "previous_profile": USER_PARENT_PROFILES[version],
                "kernel_reader": MOUNTINFO64_METHOD_SHA256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


CURRENT_USER_PARENT_METHOD_SHA256 = _current_method(
    SUPPORTED_USER_SYSTEMD_VERSION, CURRENT_USER_PARENT_PROVIDER_VERSION
)
CURRENT_USER_PARENT_262_METHOD_SHA256 = _current_method(
    SUPPORTED_USER_SYSTEMD_262_VERSION, CURRENT_USER_PARENT_262_PROVIDER_VERSION
)
CURRENT_USER_PARENT_PROFILES: MappingProxyType[str, tuple[UserParentProviderVersion, str]] = (
    MappingProxyType(
        {
            SUPPORTED_USER_SYSTEMD_VERSION: (
                CURRENT_USER_PARENT_PROVIDER_VERSION,
                CURRENT_USER_PARENT_METHOD_SHA256,
            ),
            SUPPORTED_USER_SYSTEMD_262_VERSION: (
                CURRENT_USER_PARENT_262_PROVIDER_VERSION,
                CURRENT_USER_PARENT_262_METHOD_SHA256,
            ),
        }
    )
)


def current_root_parent_profile(version: str) -> tuple[UserParentProviderVersion, str]:
    """Select the exact current method; version prefixes and historical tuples never qualify."""
    if type(version) is not str or version not in CURRENT_USER_PARENT_PROFILES:
        raise ValueError("User manager version has no closed current root profile")
    return CURRENT_USER_PARENT_PROFILES[version]
