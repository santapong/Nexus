"""Generated mechanical descriptors for pure observer/store tests; no actual job evidence."""

from nexus.builder.contained_contracts import ContainedEvidenceIdentity, ParentObservation
from nexus.builder.contained_evidence_types import ExactContainer, ProcessIdentity, ProcessRole
from nexus.builder.contained_scope import validate_current_scope
from nexus.tests.unit.test_contained_scope import (
    BOOT as BOOT,
)
from nexus.tests.unit.test_contained_scope import (
    GROUP as GROUP,
)
from nexus.tests.unit.test_contained_scope import (
    INVOCATION as INVOCATION,
)
from nexus.tests.unit.test_contained_scope import (
    expectation,
    kernel_facts,
    unit_facts,
)


def parent() -> ParentObservation:
    """Synthetic qualified parent, never an effect permit."""
    return validate_current_scope(
        expectation(), unit_facts(), kernel_facts(), 11_000_000, 12_000_000
    )


def container() -> ExactContainer:
    """Expected exact immutable object and independently selected action/image."""
    return ExactContainer(
        company_id=BOOT,
        action_id=BOOT,
        image_id="a" * 64,
        container_id="b" * 64,
        container_name="nexus-builder-" + "c" * 32,
        memory_bytes=4294967296,
        cpu_quota_us=200000,
        cpu_period_us=100000,
        pids=256,
    )


def process(
    pid: int = 101, role: ProcessRole = "payload", path: str = GROUP + "/payload"
) -> ProcessIdentity:
    """Observed generated process/start identity beneath the synthetic parent."""
    return ProcessIdentity(
        boot_id=BOOT,
        pid=pid,
        start_ticks=pid * 10,
        role=role,
        cgroup_path=path,
        mount_id=32,
        cgroup_device=27,
        cgroup_inode=200,
    )


def identity() -> ContainedEvidenceIdentity:
    """Original issuance fence stays independent of every later replay lease."""
    return ContainedEvidenceIdentity(
        company_id=BOOT,
        action_id=BOOT,
        original_intent_fence=1,
        result_base_sha256="d" * 64,
        execution_method_sha256="e" * 64,
    )
