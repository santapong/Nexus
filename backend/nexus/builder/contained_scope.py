"""Pure comparison of current independently observed unit and kernel scope facts."""

from __future__ import annotations

from nexus.builder.contained_contracts import (
    KernelScopeFacts,
    ParentObservation,
    ScopeExpectation,
    SystemdScopeFacts,
    cgroup_components,
    require_user_manager,
)


def validate_current_scope(
    expected: ScopeExpectation,
    unit: SystemdScopeFacts,
    kernel: KernelScopeFacts,
    start_us: int,
    end_us: int,
) -> ParentObservation:
    """A finite actual monotonic deadline and every exact identity/limit must agree."""
    _require_unit(expected, unit)
    _require_kernel(expected, kernel)
    if unit.user_manager != kernel.user_manager:
        raise ValueError("Unit and kernel user manager observations differ")
    deadline = unit.active_enter_us + unit.runtime_us
    remaining = deadline - end_us
    if not unit.active_enter_us <= start_us <= end_us or remaining < expected.minimum_remaining_us:
        raise ValueError("Scope deadline is expired, insufficient or clock order differs")
    return ParentObservation(
        expectation=expected,
        unit=unit,
        kernel=kernel,
        observed_start_us=start_us,
        observed_end_us=end_us,
        deadline_us=deadline,
        remaining_us=remaining,
    )


def _require_unit(expected: ScopeExpectation, unit: SystemdScopeFacts) -> None:
    require_user_manager(unit.user_manager, expected.uid)
    wanted = (
        expected.unit,
        "loaded",
        "active",
        expected.invocation_id,
        expected.cgroup_path,
        expected.runtime_us,
        0,
        True,
        expected.memory_bytes,
        expected.cpu_quota_us * 1_000_000,
        expected.cpu_period_us,
        expected.pids,
        "control-group",
        True,
        expected.stop_us,
    )
    actual = (
        unit.unit,
        unit.load_state,
        unit.active_state,
        unit.invocation_id,
        unit.cgroup_path,
        unit.runtime_us,
        unit.randomized_extra_us,
        unit.delegated,
        unit.memory_bytes,
        unit.cpu_per_second_us * unit.cpu_period_us,
        unit.cpu_period_us,
        unit.pids,
        unit.kill_mode,
        unit.send_sigkill,
        unit.stop_us,
    )
    if actual != wanted:
        raise ValueError("Current systemd scope identity, duration or exact caps differ")


def _require_kernel(expected: ScopeExpectation, kernel: KernelScopeFacts) -> None:
    require_user_manager(kernel.user_manager, expected.uid)
    prefix = ("user.slice", f"user-{expected.uid}.slice", f"user@{expected.uid}.service")
    if cgroup_components(kernel.cgroup_path)[:3] != prefix or kernel.delegation_marker not in {
        "present_1",
        "absent_user_manager",
    }:
        raise ValueError("Kernel user hierarchy or marker description differs")
    wanted = (
        expected.uid,
        expected.uid,
        expected.boot_id,
        expected.mount_id,
        expected.mount_device,
        expected.mount_inode,
        expected.cgroup_path,
        expected.cgroup_path,
        expected.cgroup_inode,
        expected.memory_bytes,
        expected.cpu_quota_us,
        expected.cpu_period_us,
        expected.pids,
    )
    actual = (
        kernel.uid,
        kernel.directory_uid,
        kernel.boot_id,
        kernel.mount_id,
        kernel.mount_device,
        kernel.mount_inode,
        kernel.cgroup_path,
        kernel.self_cgroup_path,
        kernel.cgroup_inode,
        kernel.memory_bytes,
        kernel.cpu_quota_us,
        kernel.cpu_period_us,
        kernel.pids,
    )
    if actual != wanted or not {"cpu", "memory", "pids"}.issubset(kernel.controllers):
        raise ValueError("Current owned kernel scope identity, controllers or exact caps differ")
