"""Post-seal descriptions are tested independently from live opaque ownership authority."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nexus.builder.contained_contracts import HostPlacementIdentity, ParentObservation
from nexus.builder.contained_discovery import decode_discovery
from nexus.builder.contained_parent_diagnostics import ParentAttempt
from nexus.builder.contained_process_contracts import require_spawn_ready
from nexus.builder.contained_scope import validate_current_scope, validate_issued_scope
from nexus.builder.issued_parent_identity import CURRENT_ISSUED_PARENT_METHOD_SHA256
from nexus.builder.user_parent_identity import CURRENT_USER_PARENT_METHOD_SHA256
from nexus.tests.contained_process_fixture import binding, launch, parent, window
from nexus.tests.unit.test_contained_discovery import body


def placement() -> HostPlacementIdentity:
    current, original = parent(), binding()
    return HostPlacementIdentity(
        company_id=original.company_id,
        action_id=original.action_id,
        task_id=original.task_id,
        trace_id=original.trace_id,
        run_id=original.run_id,
        original_intent_fence=original.original_intent_fence,
        spec_sha256=original.spec_sha256,
        proposal_sha256=original.proposal_sha256,
        execution_method_sha256=original.execution_method_sha256,
        container_id="e" * 64,
        container_name=original.container_name,
        image_id=original.image_id,
        boot_id=current.kernel.boot_id,
        uid=1000,
        collector_pid=700,
        collector_start_ticks=7000,
        runtime_pid=777,
        runtime_start_ticks=7770,
        mount_id=current.kernel.mount_id,
        mount_device=current.kernel.mount_device,
        mount_inode=current.kernel.mount_inode,
        scope_path=current.kernel.cgroup_path,
        scope_inode=current.kernel.cgroup_inode,
        scope_uid=1000,
        runtime_path=current.kernel.cgroup_path + "/runtime",
        runtime_mount_id=current.kernel.mount_id,
        runtime_device=current.kernel.mount_device,
        runtime_inode=222,
        runtime_uid=1000,
    )


def test_preissue_default_identity_and_wire_remain_strict_root() -> None:
    current = parent()
    assert current.provider_method_sha256 == CURRENT_USER_PARENT_METHOD_SHA256
    assert "issued_identity" not in current.model_dump()
    changed = current.kernel.model_copy(update={"self_cgroup_path": placement().runtime_path})
    with pytest.raises(ValueError, match="kernel scope"):
        validate_current_scope(current.expectation, current.unit, changed, 11_000_000, 12_000_000)


def test_issued_description_preserves_actual_path_and_distinct_provider_identity() -> None:
    current, owned = parent(), placement()
    kernel = current.kernel.model_copy(update={"self_cgroup_path": owned.runtime_path})
    value = validate_issued_scope(
        current.expectation,
        current.unit,
        kernel,
        owned,
        decode_discovery(body(), launch(), runtime_pid=777),
        11_000_000,
        12_000_000,
    )
    assert value.schema_version == "nexus.builder.parent-observation.v3"
    assert (
        value.provider_method_sha256
        == CURRENT_ISSUED_PARENT_METHOD_SHA256
        != CURRENT_USER_PARENT_METHOD_SHA256
    )
    assert value.kernel.self_cgroup_path == owned.runtime_path
    assert value.kernel.cgroup_path == current.kernel.cgroup_path
    assert value.issued_identity == owned
    assert ParentObservation.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("runtime_path", "/foreign/runtime"),
        ("runtime_path", "/runtime/x"),
        ("runtime_uid", 2),
        ("runtime_device", 9),
        ("runtime_mount_id", 9),
        ("collector_pid", 777),
        ("runtime_inode", True),
    ],
)
def test_runtime_leaf_description_rejects_alias_identity_or_coercion(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        HostPlacementIdentity.model_validate(placement().model_dump() | {field: value})


def test_exact_retained_fourth_case_still_denies_default_without_live_context() -> None:
    path = Path(__file__).parents[1] / "fixtures/issued-parent-v1/fourth-case-parent-failure.json"
    raw = path.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "181822f2c637fa5df507ed0db44f4bc4029ffd8938bfe94e0250cc59c28de080"
    )
    receipt = json.loads(raw)
    original = ParentObservation.model_validate_json(json.dumps(receipt["bootstrap"]))
    failed = ParentAttempt.model_validate_json(json.dumps(receipt["attempt"]))
    assert failed.unit is not None and failed.kernel is not None
    with pytest.raises(ValueError, match="kernel scope"):
        validate_current_scope(
            original.expectation, failed.unit, failed.kernel, failed.started_us, failed.finished_us
        )


def test_postseal_description_cannot_replace_strict_prespawn_parent() -> None:
    current, owned = parent(), placement()
    post = validate_issued_scope(
        current.expectation,
        current.unit,
        current.kernel.model_copy(update={"self_cgroup_path": owned.runtime_path}),
        owned,
        decode_discovery(body(), launch(), runtime_pid=777),
        11_000_000,
        12_000_000,
    )
    with pytest.raises(ValueError, match="strict original root"):
        require_spawn_ready(
            launch(),
            binding(),
            post,
            window(),
            monotonic_now_us=12_020_000,
            utc_now=datetime(2026, 10, 15, tzinfo=UTC),
        )
