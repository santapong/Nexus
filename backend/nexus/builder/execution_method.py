"""Unactivated method candidate; shared gate/spawn/result/cleanup algorithms remain unqualified."""

import hashlib
import json
from typing import Literal

from nexus.builder.contained_contracts import ContainedValue, ObservationBounds
from nexus.builder.runtime_identity import RUNTIME_V2_METHOD_SHA256
from nexus.builder.user_parent_identity import USER_PARENT_METHOD_SHA256

# Complete implementation identity is separate from actual qualification receipts.
# A digest never activates a process or grants native action authority.
CONTAINED_EXECUTION_METHOD_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "schema": "nexus.builder.contained-execution-method.v1",
            "selector": RUNTIME_V2_METHOD_SHA256,
            "parent": USER_PARENT_METHOD_SHA256,
            "observer": "nexus.builder.contained-observation.v1",
            "store": "nexus.builder.containment-ref.v1",
            "source_clock": "db_query_start_monotonic_original_deadlines_utc_continuity_1s",
            "intent": "source_then_current_parent_same_native_tx_final_clock",
            "spawn": "watch_parent_descriptor_final_clock_task_local_final_clock_native_issue",
            "ownership": "strong_pending_spawn_original_runtime_pid_start_path_wait_unknown",
            "sampling": {
                "interval_us": 100000,
                "samples": 12001,
                "processes": 256,
                "subtrees": 512,
                "sidecar_bytes": 65536,
            },
            "result": "original_fence_base_excludes_ref_full_includes_ref_actual_sidecar_reread",
            "cleanup": {
                "version": "nexus.builder.contained-cleanup.v1",
                "total_us": 5000000,
                "rows": 512,
                "bytes": 65536,
                "force": False,
            },
            "default": "unconfigured",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()


class ExecutionMethodCandidate(ContainedValue):
    """A candidate description cannot provide the later full activation pin."""

    schema_version: Literal["nexus.builder.execution-method-candidate.v1"] = (
        "nexus.builder.execution-method-candidate.v1"
    )
    selector_sha256: str = RUNTIME_V2_METHOD_SHA256
    provider_sha256: str = USER_PARENT_METHOD_SHA256
    observer_version: Literal["nexus.builder.contained-observation.v1"] = (
        "nexus.builder.contained-observation.v1"
    )
    store_version: Literal["nexus.builder.containment-ref.v1"] = "nexus.builder.containment-ref.v1"
    bounds: ObservationBounds = ObservationBounds()
    execution_ready: Literal[False] = False


def execution_method_candidate() -> ExecutionMethodCandidate:
    """A candidate never configures execution or replaces actual qualification receipts."""
    return ExecutionMethodCandidate()
