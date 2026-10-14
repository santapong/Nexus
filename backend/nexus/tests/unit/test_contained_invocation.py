"""Synthetic raw capture plus real sidecar storage; no native permit/process/DB is issued."""

import base64
import io
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

import nexus.builder.contained_invocation as module
from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.contained_evidence_types import ObservationDeadline, ObservedSample
from nexus.builder.contained_observer import ContainmentObserver
from nexus.builder.contained_process_contracts import ContainedRunCapture, RuntimeCapture
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.process import ProcessCapture
from nexus.builder.runner import NativeBuilderRunner
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.builder_support import described_binding, synthetic_capabilities
from nexus.tests.contained_observer_fixture import container, process
from nexus.tests.contained_process_fixture import binding, launch, parent
from nexus.tests.unit.test_contained_evidence_types import sample
from nexus.tests.unit.test_contained_runtime_identity import configured


@pytest.mark.parametrize("qualified,late", [(False, False), (True, False), (True, True)])
async def test_only_actual_complete_host_sample_can_attach_original_result_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qualified: bool,
    late: bool,
) -> None:
    # One composed fixture keeps decoded original command bytes, host observation
    # and actual immutable store identity together; no fake terminal receipt exists.
    spec, policy = configured()
    expected = parent().expectation
    job = spec.job.model_copy(
        update={
            "company_id": expected.company_id,
            "action_id": expected.action_id,
            "task_id": expected.task_id,
            "trace_id": expected.trace_id,
            "run_id": expected.run_id,
        }
    )
    policy = BuilderToolPolicy.model_validate(
        policy.model_dump()
        | {
            "company_id": expected.company_id,
            "full_execution_method_sha256": CONTAINED_EXECUTION_METHOD_SHA256,
        }
    )
    spec = spec.model_copy(update={"job": job, "policy_sha256": canonical_sha256(policy)})
    action, lease, _ = described_binding(job)
    identity = VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id)
    services = ContainmentServices(expected, ContainmentEvidenceStore(tmp_path / "sidecars"))
    services.deadline = ObservationDeadline(end_us=13_000_000)
    exact = container().model_copy(
        update={"container_name": binding().container_name, "runtime_pid": 777}
    )
    row = ObservedSample.model_validate(
        sample().model_dump()
        | {
            "container": exact.model_dump(),
            "processes": tuple(
                p.model_dump() for p in (*sample().processes, process(777, "runtime"))
            ),
        }
    )
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as exported:
        for phase in ["baseline", "post"]:
            entry = tarfile.TarInfo(phase + "/checks/result.txt")
            entry.size = 1
            exported.addfile(entry, io.BytesIO(b"x"))
    output = (
        "NEXUS-BUILDER/1\nQ 4294967296 200000 100000 256\n"
        "C 0 0 1\nO 0 \nE 0 \nC 1 0 1\nO 1 \nE 1 \nA "
        + base64.b64encode(archive.getvalue()).decode()
        + "\nEND\n"
    ).encode()
    raw = ContainedRunCapture(
        capture=ProcessCapture(output, b"", 0, 1, None),
        runtime=RuntimeCapture(
            pid=777,
            start_ticks=7770,
            cgroup_path=parent().kernel.cgroup_path,
            parent_membership="observed_path",
            reap="waited",
        ),
        parent=parent(),
        deadline=services.deadline,
        sealed_container=exact if qualified else None,
        samples=(row,) if qualified else (),
        infrastructure="known" if qualified else "unproven",
    )
    monkeypatch.setattr(services.process, "run", AsyncMock(return_value=raw))
    monkeypatch.setattr(module, "described_contained_argv", lambda *a, **k: launch().argv)
    clocks = iter((12_040_000, 12_040_000, 13_000_001))
    monkeypatch.setattr(module, "clock_us", clocks.__next__ if late else lambda: 12_040_000)
    real_observer = ContainmentObserver
    monkeypatch.setattr(
        module,
        "ContainmentObserver",
        lambda actual: real_observer(actual, clock_us=lambda: 12_040_000),
    )
    runner = cast(
        NativeBuilderRunner,
        SimpleNamespace(
            containment=services,
            policy=policy,
            image_id="a" * 64,
            capabilities=synthetic_capabilities(),
            factory=object(),
            execution=object(),
        ),
    )
    guard = cast(BuilderSourceGuard, SimpleNamespace(lease=lease))
    if late:
        with pytest.raises(ValueError, match="validation crossed"):
            await module.invoke_contained(runner, lease, identity, action, spec, guard, tmp_path)
        return
    result = await module.invoke_contained(runner, lease, identity, action, spec, guard, tmp_path)
    assert result.spec == spec and result.intent_fence == lease.fence
    assert result.contained_runtime == raw.runtime
    if qualified:
        assert result.outcome == "commands_succeeded" and result.containment is not None
        sidecar = await services.store.load_exact(result.containment, result.containment.identity)
        assert sidecar.identity.original_intent_fence == lease.fence
        assert sidecar.spec_sha256 == canonical_sha256(spec)
    else:
        assert result.outcome == "outcome_unknown" and result.containment is None
