"""Nominated sample rows test binding only; no actual live process/cgroup qualification."""

from nexus.builder.contained_contracts import ParentObservation
from nexus.builder.contained_evidence_types import ExactContainer, ObservedSample, ProcessIdentity


# One >50-line fixture shows all roles, numeric observations and original binding in one value.
def sample_for(
    parent: ParentObservation,
    container: ExactContainer,
    start: int = 12_030_000,
    end: int = 12_040_000,
) -> ObservedSample:
    owned = parent.issued_identity
    assert owned is not None
    rows = []
    for pid, ticks, role, path, inode in (
        (
            owned.collector_pid,
            owned.collector_start_ticks,
            "descendant",
            owned.runtime_path,
            owned.runtime_inode,
        ),
        (
            owned.runtime_pid,
            owned.runtime_start_ticks,
            "runtime",
            owned.runtime_path,
            owned.runtime_inode,
        ),
        (102, 1020, "conmon", owned.runtime_path, owned.runtime_inode),
        (101, 1010, "payload", owned.scope_path + "/payload", 333),
    ):
        rows.append(
            ProcessIdentity.model_validate(
                {
                    "boot_id": owned.boot_id,
                    "pid": pid,
                    "start_ticks": ticks,
                    "role": role,
                    "cgroup_path": path,
                    "mount_id": owned.mount_id,
                    "cgroup_device": owned.mount_device,
                    "cgroup_inode": inode,
                }
            )
        )
    return ObservedSample(
        parent=parent,
        container=container,
        started_us=start,
        finished_us=end,
        deadline_end_us=13_000_000,
        processes=tuple(rows),
        status="observed_contained",
        diagnostics=(),
        subtree_count=3,
        tree_complete=True,
        memory_bytes=container.memory_bytes,
        cpu_quota_us=container.cpu_quota_us,
        cpu_period_us=container.cpu_period_us,
        pids=container.pids,
    )
