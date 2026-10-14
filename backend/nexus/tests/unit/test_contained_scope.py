"""Pure scope descriptions never authorize an effect; every current fact is compared."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.builder.contained_contracts import (
    ContainedEvidenceIdentity,
    KernelScopeFacts,
    ObservationBounds,
    ScopeExpectation,
    SystemdScopeFacts,
)
from nexus.builder.contained_scope import validate_current_scope

BOOT = UUID("11111111-1111-4111-8111-111111111111")
INVOCATION = UUID("22222222-2222-4222-8222-222222222222")
UNIT = "nexus-test-1.scope"
GROUP = f"/user.slice/user-1000.slice/user@1000.service/app.slice/{UNIT}"


def expectation() -> ScopeExpectation:
    """Trusted-only synthetic fixture; no runner consumes it."""
    return ScopeExpectation(
        task_id=BOOT,
        trace_id=BOOT,
        company_id=BOOT,
        action_id=BOOT,
        run_id=BOOT,
        uid=1000,
        boot_id=BOOT,
        unit=UNIT,
        invocation_id=INVOCATION,
        launcher_nonce=BOOT,
        mount_id=32,
        mount_device=27,
        mount_inode=1,
        cgroup_path=GROUP,
        cgroup_inode=100,
        memory_bytes=4_294_967_296,
        cpu_quota_us=200_000,
        cpu_period_us=100_000,
        pids=256,
        runtime_us=1_200_000_000,
        stop_us=1_000_000,
        minimum_remaining_us=1_000_000,
    )


def unit_facts() -> SystemdScopeFacts:
    """Exact finite systemd properties for the synthetic scope."""
    return SystemdScopeFacts(
        unit=UNIT,
        load_state="loaded",
        active_state="active",
        invocation_id=INVOCATION,
        active_enter_us=10_000_000,
        cgroup_path=GROUP,
        runtime_us=1_200_000_000,
        randomized_extra_us=0,
        delegated=True,
        memory_bytes=4_294_967_296,
        cpu_per_second_us=2_000_000,
        cpu_period_us=100_000,
        pids=256,
        kill_mode="control-group",
        send_sigkill=True,
        stop_us=1_000_000,
    )


def kernel_facts() -> KernelScopeFacts:
    """Exact current kernel identity and hard limits for the synthetic scope."""
    return KernelScopeFacts(
        uid=1000,
        boot_id=BOOT,
        self_cgroup_path=GROUP,
        mount_id=32,
        mount_device=27,
        mount_inode=1,
        cgroup_path=GROUP,
        cgroup_inode=100,
        directory_uid=1000,
        delegation_marker=True,
        controllers=frozenset({"cpu", "memory", "pids"}),
        memory_bytes=4_294_967_296,
        cpu_quota_us=200_000,
        cpu_period_us=100_000,
        pids=256,
    )


def test_exact_current_scope_records_actual_remaining_without_permission() -> None:
    observed = validate_current_scope(
        expectation(), unit_facts(), kernel_facts(), 11_000_000, 12_000_000
    )
    assert observed.deadline_us == 1_210_000_000
    assert observed.remaining_us == 1_198_000_000
    assert observed.expectation == expectation()
    assert "permit" not in observed.model_dump()


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit", "nexus-other.scope"),
        ("load_state", "not-found"),
        ("active_state", "inactive"),
        ("invocation_id", BOOT),
        ("cgroup_path", GROUP + "-other"),
        ("delegated", False),
        ("randomized_extra_us", 1),
        ("runtime_us", 1),
        ("memory_bytes", 1),
        ("cpu_per_second_us", 1),
        ("cpu_period_us", 200_000),
        ("pids", 257),
        ("kill_mode", "process"),
        ("send_sigkill", False),
        ("stop_us", 2_000_000),
    ],
)
def test_changed_unit_identity_deadline_or_cap_denies(field: str, value: object) -> None:
    row = SystemdScopeFacts.model_validate(unit_facts().model_dump() | {field: value})
    with pytest.raises(ValueError):
        validate_current_scope(expectation(), row, kernel_facts(), 11_000_000, 12_000_000)


@pytest.mark.parametrize(
    "field,value",
    [
        ("uid", 1001),
        ("directory_uid", 0),
        ("boot_id", INVOCATION),
        ("mount_id", 33),
        ("mount_device", 28),
        ("mount_inode", 2),
        ("cgroup_inode", 101),
        ("cgroup_path", GROUP + "-other"),
        ("self_cgroup_path", GROUP + "/child"),
        ("delegation_marker", False),
        ("controllers", frozenset({"cpu", "memory"})),
        ("memory_bytes", 1),
        ("cpu_quota_us", 100_000),
        ("cpu_period_us", 50_000),
        ("pids", 255),
    ],
)
def test_changed_kernel_identity_or_exact_limits_denies(field: str, value: object) -> None:
    row = KernelScopeFacts.model_validate(kernel_facts().model_dump() | {field: value})
    with pytest.raises(ValueError):
        validate_current_scope(expectation(), unit_facts(), row, 11_000_000, 12_000_000)


@pytest.mark.parametrize(
    "start,end",
    [
        (9_000_000, 12_000_000),
        (12_000_000, 11_000_000),
        (11_000_000, 1_210_000_000),
        (11_000_000, 1_209_000_001),
    ],
)
def test_expired_insufficient_or_regressing_clock_denies(start: int, end: int) -> None:
    with pytest.raises(ValueError):
        validate_current_scope(expectation(), unit_facts(), kernel_facts(), start, end)


@pytest.mark.parametrize(
    "field,value",
    [
        ("uid", False),
        ("runtime_us", None),
        ("memory_bytes", float("inf")),
        ("unit", "--help"),
        ("cgroup_path", "/../foreign"),
        ("runtime_us", "1200000000"),
    ],
)
def test_expectation_does_not_coerce_unlimited_or_untrusted_values(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        ScopeExpectation.model_validate(expectation().model_dump() | {field: value})


def test_evidence_identity_uses_original_intent_fence_and_closed_bounds() -> None:
    identity = ContainedEvidenceIdentity(
        company_id=BOOT,
        action_id=BOOT,
        original_intent_fence=1,
        result_base_sha256="a" * 64,
        execution_method_sha256="b" * 64,
    )
    assert identity.model_dump()["original_intent_fence"] == 1
    with pytest.raises(ValidationError):
        ContainedEvidenceIdentity.model_validate(identity.model_dump() | {"current_lease_fence": 9})
    assert ObservationBounds().total_io_us == 3_000_000
    for changed in (
        {"total_io_us": 4_000_000},
        {"total_io_us": 3_000_000.0},
        {"kernel_bytes": None},
        {"process_count": False},
    ):
        with pytest.raises(ValidationError):
            ObservationBounds.model_validate(changed)
