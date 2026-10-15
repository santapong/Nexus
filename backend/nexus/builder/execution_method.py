"""Unactivated method candidate; shared gate/spawn/result/cleanup algorithms remain unqualified."""

import hashlib
import json
from typing import Literal

from nexus.builder.contained_contracts import ContainedValue, ObservationBounds
from nexus.builder.issued_parent_identity import ISSUED_PARENT_METHOD_SHA256, ISSUED_PARENT_PROFILES
from nexus.builder.runtime_identity import RUNTIME_V2_METHOD_SHA256
from nexus.builder.user_parent_identity import (
    USER_PARENT_262_METHOD_SHA256,
    USER_PARENT_METHOD_SHA256,
    USER_PARENT_PROFILES,
)

# Complete implementation identity is separate from actual qualification receipts.
# A digest never activates a process or grants native action authority.
CONTAINED_EXECUTION_METHOD_V6_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "schema": "nexus.builder.contained-execution-method.v6",
            "fixed_inspect_template": "podman_go_field_ID_not_json_tag_Id",
            "diagnostics": {
                "raw": "original_identity_complete_capture_metadata_before_decode",
                "final": "observer_status_before_any_unknown_or_terminal_result",
                "store": "nexus.builder.diagnostic-ref.v1",
                "bytes": 65536,
                "deadline": "same_original_job_end_no_authority",
                "parent_failure": {
                    "binding": "same_exception_original_scope_current_attempt_only",
                    "queries": 5,
                    "query_prefix_bytes": 512,
                    "parsed_facts": "canonical-parsed-parent-facts.v1",
                    "unit_bytes": 16384,
                    "kernel_bytes": 8192,
                    "overflow": "explicit_digest_truncation_never_authority",
                    "clock": "after_metadata_original_io_and_parent_end",
                    "issued_failure": {
                        "schema": "nexus.builder.issued-failure.v1",
                        "binding": "same_exception_call_token_scope_and_original_job_only",
                        "observations": "existing_read_operands_once_original_shortcircuit_order",
                        "bytes": 4096,
                        "timeout": "frozen_snapshot_no_late_worker_backfill",
                        "authority": "none_preserve_exception_predicate_and_original_end",
                    },
                },
            },
            "selector": RUNTIME_V2_METHOD_SHA256,
            "parent": USER_PARENT_METHOD_SHA256,
            "issued_parent": {
                "method": ISSUED_PARENT_METHOD_SHA256,
                "phase": "opaque_actual_owned_start_fixed_full_id_postseal_only",
                "placement": "exact_runtime_leaf_actual_facts_original_root_caps",
                "series": "stable_issued_identity_all_immutable_parent_facts",
                "binding": "original_preissue_parent_to_issued_job_fence_full_id_samples_sidecar",
                "ownership": "strong_pending_fd_io_and_child_no_hard_thread_cancellation_claim",
            },
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


# V6 remains byte-identifiable history. V7 binds the unchanged algorithms to both exact profiles.
CONTAINED_EXECUTION_METHOD_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "schema": "nexus.builder.contained-execution-method.v7",
            "legacy_algorithm_sha256": CONTAINED_EXECUTION_METHOD_V6_SHA256,
            "root_profiles": dict(USER_PARENT_PROFILES),
            "issued_profiles": dict(ISSUED_PARENT_PROFILES),
            "manager_binding": (
                "same_actual_closed_manager_unit_and_kernel_phase_exact_provider_hash"
            ),
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
    provider_sha256: str = USER_PARENT_262_METHOD_SHA256
    observer_version: Literal["nexus.builder.contained-observation.v1"] = (
        "nexus.builder.contained-observation.v1"
    )
    store_version: Literal["nexus.builder.containment-ref.v1"] = "nexus.builder.containment-ref.v1"
    bounds: ObservationBounds = ObservationBounds()
    execution_ready: Literal[False] = False


def execution_method_candidate() -> ExecutionMethodCandidate:
    """Candidate identity cannot replace configured execution or actual qualification receipts."""
    return ExecutionMethodCandidate()
