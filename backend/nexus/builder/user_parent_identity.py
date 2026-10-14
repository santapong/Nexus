"""Provider-only v2 identity; selector/full execution authority remains separate and disabled."""

import hashlib
import json
from typing import Literal

USER_PARENT_PROVIDER_VERSION: Literal["nexus.builder.user-parent-provider.v2"] = (
    "nexus.builder.user-parent-provider.v2"
)
SUPPORTED_USER_SYSTEMD_VERSION: Literal["261.2-1"] = "261.2-1"
USER_PARENT_METHOD_SHA256 = hashlib.sha256(
    json.dumps(
        {
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
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()
