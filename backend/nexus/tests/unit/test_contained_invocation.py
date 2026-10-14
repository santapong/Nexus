"""Synthetic raw capture plus real sidecar storage; no native permit/process/DB is issued."""

import asyncio
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
from nexus.builder.contained_observer_io import OwnedObservationIO
from nexus.builder.contained_process_contracts import (
    ContainedRunCapture,
    ProcessSampling,
    RuntimeCapture,
    process_diagnostic,
)
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.process import ProcessCapture
from nexus.builder.runner import NativeBuilderRunner
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.management.canonical import canonical_sha256
from nexus.harness.canonical import action_hash
from nexus.tests.builder_support import described_binding, synthetic_capabilities
from nexus.tests.contained_observer_fixture import container, process
from nexus.tests.contained_process_fixture import binding, launch, parent
from nexus.tests.unit.test_contained_evidence_types import sample
from nexus.tests.unit.test_contained_runtime_identity import configured


@pytest.mark.parametrize(
    "qualified,late,final_failure",
    [
        (False, False, None),
        (True, False, None),
        (True, True, None),
        (True, False, "unproven"),
        (True, False, "exception"),
    ],
)
async def test_only_actual_complete_host_sample_can_attach_original_result_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qualified: bool,
    late: bool,
    final_failure: str | None,
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

    async def empty() -> bytes:
        return b""

    async def stopped() -> int:
        return 0

    tasks = (
        asyncio.create_task(empty()),
        asyncio.create_task(empty()),
        asyncio.create_task(stopped()),
    )
    state = ProcessSampling(*tasks)
    bound = binding().model_copy(
        update={
            "company_id": job.company_id,
            "action_id": job.action_id,
            "task_id": job.task_id,
            "trace_id": job.trace_id,
            "run_id": job.run_id,
            "original_intent_fence": lease.fence,
            "spec_sha256": canonical_sha256(spec),
            "proposal_sha256": action_hash(action),
            "execution_method_sha256": services.method_sha256,
        }
    )
    raw = raw.model_copy(update={"diagnostic": process_diagnostic(bound, raw, state)})
    await asyncio.gather(*tasks)
    import nexus.builder.contained_diagnostic_wiring as diagnostic_module

    monkeypatch.setattr(diagnostic_module, "clock_us", lambda: 12_040_000)
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
    if final_failure is not None:
        from nexus.builder.contained_evidence_types import ContainedObservation

        async def finish(*args: object, **kwargs: object) -> ContainedObservation:
            if final_failure == "exception":
                raise OSError(5, "nominated actual observer failure")
            actual_observer = real_observer(OwnedObservationIO(), clock_us=lambda: 12_040_000)
            from nexus.builder.contained_results import result_evidence_identity
            from nexus.builder.runner_capture import capture_result
            from nexus.builder.runtime_identity import RUNTIME_V1

            decoded = capture_result(
                raw.capture,
                spec.model_copy(update={"runtime_recipe": RUNTIME_V1}),
                action,
                lease.fence,
                "a" * 64,
                binding().container_name,
            )
            restored = decoded.model_copy(update={"spec": spec, "contained_runtime": raw.runtime})
            assert services.deadline is not None
            value = await actual_observer.finish(
                raw.samples,
                result_evidence_identity(restored, services.method_sha256),
                spec_sha256=canonical_sha256(spec),
                proposal_sha256=action_hash(action),
                selector_sha256=policy.runtime_method_sha256 or "",
                deadline=services.deadline,
            )
            return value.model_copy(
                update={"status": "unproven", "diagnostics": ("tree_incomplete",)}
            )

        monkeypatch.setattr(
            module, "ContainmentObserver", lambda actual: SimpleNamespace(finish=finish)
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
    if final_failure == "exception":
        with pytest.raises(OSError, match="nominated actual observer"):
            await module.invoke_contained(runner, lease, identity, action, spec, guard, tmp_path)
        paths = list(services.diagnostics.root.glob("*final*"))
        assert len(paths) == 1 and b'"error_type":"OSError"' in paths[0].read_bytes()
        return
    result = await module.invoke_contained(runner, lease, identity, action, spec, guard, tmp_path)
    assert result.spec == spec and result.intent_fence == lease.fence
    assert result.contained_runtime == raw.runtime
    assert len(list(services.diagnostics.root.iterdir())) == 2
    if final_failure == "unproven":
        assert result.outcome == "outcome_unknown" and result.containment is None
        assert b'"tree_incomplete"' in next(services.diagnostics.root.glob("*final*")).read_bytes()
    elif qualified:
        assert result.outcome == "commands_succeeded" and result.containment is not None
        sidecar = await services.store.load_exact(result.containment, result.containment.identity)
        assert sidecar.identity.original_intent_fence == lease.fence
        assert sidecar.spec_sha256 == canonical_sha256(spec)
    else:
        assert result.outcome == "outcome_unknown" and result.containment is None
