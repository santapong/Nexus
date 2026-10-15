"""End-to-end pure process/provider/raw/sidecar composition; no engine, scope or DB."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

import nexus.builder.contained_process as module
from nexus.builder.contained_contracts import (
    ContainedEvidenceIdentity,
    KernelScopeFacts,
    ParentObservation,
)
from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.contained_evidence_types import (
    ExactContainer,
    ObservationDeadline,
    ObservedSample,
    ProcessIdentity,
    parent_identity,
)
from nexus.builder.contained_observer import ContainmentObserver
from nexus.builder.contained_observer_io import OwnedObservationIO
from nexus.builder.contained_process import ContainedProcess
from nexus.builder.contained_process_contracts import ContainedRunCapture
from nexus.builder.systemd_scope_provider import SystemdScopeProvider
from nexus.tests.contained_process_fixture import Process, binding, launch
from nexus.tests.issued_membership_fixture import prepared
from nexus.tests.issued_sample_fixture import sample_for
from nexus.tests.unit.test_contained_discovery import body
from nexus.tests.unit.test_contained_discovery_transport import pipe
from nexus.tests.unit.test_contained_process import Watch
from nexus.tests.unit.test_systemd_scope_provider import FakeReader, reports


# A cohesive >50-line fake lifecycle proves actual owned-start/seal paths and full raw/sidecar
# binding together. The transport/proc/kernel inventories are nominated, never live evidence.
@pytest.mark.parametrize("parent_bad", [False, True])
async def test_driver_preserves_preissue_anchor_postseal_identity_and_final_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    parent_bad: bool,
) -> None:
    import nexus.builder.contained_discovery as discovery_module

    item = await prepared(monkeypatch, tmp_path, bind=False)

    async def opened(*args: object, **kwargs: object) -> object:
        return item.owner

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        if args[3] == "run":
            return item.process
        probe = Process()
        probe.pid = 888
        probe.stdout = pipe(body())
        return cast(asyncio.subprocess.Process, probe)

    async def kernel() -> KernelScopeFacts:
        path = item.proc[item.owner.collector_pid][1]
        if parent_bad and path.endswith("/runtime"):
            path = "/foreign"
        return item.parent.kernel.model_copy(update={"self_cgroup_path": path})

    class MigratingWatch(Watch):
        async def check(self) -> None:
            item.migrate()

    class IO:
        async def observe(
            self,
            current: ParentObservation,
            container: ExactContainer,
            deadline: ObservationDeadline,
            previous: tuple[ProcessIdentity, ...],
        ) -> ObservedSample:
            row = sample_for(current, container)
            item.transport.code = 0
            item.transport.done.set()
            return row

    real = ContainmentObserver

    def observer(io: OwnedObservationIO) -> ContainmentObserver:
        return real(IO(), clock_us=lambda: 12_050_000)

    monkeypatch.setattr(module, "open_owned_start", opened)
    monkeypatch.setattr(module, "_proc", lambda pid: item.proc[pid])
    monkeypatch.setattr(module, "ContainmentObserver", observer)
    monkeypatch.setattr(discovery_module, "clock_us", lambda: 12_020_000)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    provider = SystemdScopeProvider(
        reader=FakeReader(reports() * 2), kernel_reader=kernel, clock_us=lambda: 12_020_000
    )
    process = ContainedProcess(
        provider,
        clock_us=lambda: 12_020_000,
        utc_now=lambda: datetime(2026, 10, 15, tzinfo=UTC) + timedelta(milliseconds=20),
    )
    deadline = ObservationDeadline(end_us=13_000_000)
    try:
        raw = await process.run(
            launch(),
            binding(),
            item.parent.expectation,
            MigratingWatch([]),
            deadline,
            stdout_limit=1024,
            stderr_limit=1024,
        )
        if parent_bad:
            assert raw.infrastructure == "unresolved" and raw.capture.interruption == "ValueError"
            assert raw.samples == () and raw.sealed_container is not None
            assert (
                raw.parent_attempt is not None and raw.parent_attempt.stage == "issued_membership"
            )
            assert raw.parent_attempt.kernel is not None
            assert raw.parent_attempt.kernel.self_cgroup_path == "/foreign"
            assert (
                raw.diagnostic is not None and raw.diagnostic.parent_attempt == raw.parent_attempt
            )
            return
        assert raw.infrastructure == "known" and raw.issued_cleanup == "closed"
        assert raw.parent.schema_version == "nexus.builder.parent-observation.v2"
        assert raw.samples[0].parent.schema_version == "nexus.builder.parent-observation.v3"
        assert raw.issued_identity == raw.samples[0].parent.issued_identity
        assert raw.parent.kernel.self_cgroup_path == item.parent.expectation.cgroup_path
        assert raw.samples[0].parent.kernel.self_cgroup_path.endswith("/runtime")
        ContainedRunCapture.model_validate(raw.model_dump() | {"capture": raw.capture})
        assert raw.diagnostic is not None and raw.diagnostic.issued_identity == raw.issued_identity
        identity = ContainedEvidenceIdentity(
            company_id=binding().company_id,
            action_id=binding().action_id,
            original_intent_fence=1,
            result_base_sha256="a" * 64,
            execution_method_sha256="d" * 64,
        )
        final = await real(IO(), clock_us=lambda: 12_060_000).finish(
            raw.samples,
            identity,
            spec_sha256="b" * 64,
            proposal_sha256="c" * 64,
            selector_sha256="e" * 64,
            deadline=deadline,
        )
        store = ContainmentEvidenceStore(tmp_path / "sidecars")
        reference = await store.save_once(final)
        assert (await store.load_exact(reference, identity)) == final
        assert final.status == "observed_contained"
        _splices(raw)
    finally:
        item.owner.close()


def _splices(raw: ContainedRunCapture) -> None:
    assert raw.issued_identity is not None
    for copied in (
        raw.model_copy(update={"issued_identity": None}),
        raw.model_copy(update={"issued_cleanup": "deferred"}),
        raw.model_copy(
            update={
                "issued_identity": raw.issued_identity.model_copy(
                    update={"original_intent_fence": 2}
                )
            }
        ),
        raw.model_copy(
            update={
                "parent": raw.parent.model_copy(
                    update={"unit": raw.parent.unit.model_copy(update={"pids": 255})}
                )
            }
        ),
    ):
        with pytest.raises(ValueError):
            ContainedRunCapture.model_validate(copied.model_dump() | {"capture": copied.capture})
    post = raw.samples[0].parent
    later = post.model_copy(
        update={
            "observed_start_us": 12_025_000,
            "observed_end_us": 12_026_000,
            "remaining_us": post.deadline_us - 12_026_000,
        }
    )
    assert parent_identity(later) == parent_identity(post)
    changed = post.model_copy(update={"kernel": post.kernel.model_copy(update={"pids": 255})})
    assert parent_identity(changed) != parent_identity(post)
