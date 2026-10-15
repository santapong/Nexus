"""Separate post-seal algorithm identity; default strict user-parent v2 stays unchanged."""

import hashlib
import json
from typing import Final

ISSUED_PARENT_VERSION: Final = "nexus.builder.user-issued-parent-provider.v1"
ISSUED_PARENT_METHOD_SHA256 = hashlib.sha256(
    json.dumps(
        {
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
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()
