"""Opaque stop authority and exact immutable replies over finite supplied IO, no engine."""

import asyncio
import json
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from nexus.builder.contained_evidence_types import ExactContainer, ObservationDeadline
from nexus.builder.contained_issued_context import OwnedIssuedContext
from nexus.builder.contained_owned_stop import ContainedOwnedStop, decode_inspection
from nexus.builder.contained_owned_stop_io import OwnedStopIO, StopCapture, StopKind, stop_argv
from nexus.builder.contained_process_contracts import ProcessRunBinding, StartedContainedProcess
from nexus.tests.contained_process_fixture import binding, window
from nexus.tests.issued_membership_fixture import MechanicalOwner, fixed_seal, prepared


async def owned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[MechanicalOwner, OwnedIssuedContext, StartedContainedProcess]:
    item = await prepared(monkeypatch, tmp_path)
    context = item.owner.seal(await fixed_seal(monkeypatch))
    started = StartedContainedProcess(
        item.process,
        item.parent,
        window(),
        7770,
        item.parent.kernel.cgroup_path,
        "observed_path",
        item.owner,
    )
    return item, context, started


def inspected(container: ExactContainer, is_running: bool, **changes: object) -> bytes:
    data: dict[str, object] = {
        "container_id": container.container_id,
        "container_name": container.container_name,
        "image_id": container.image_id,
        "company_id": str(container.company_id),
        "action_id": str(container.action_id),
        "running": is_running,
    }
    return json.dumps(data | changes).encode()


def install(
    monkeypatch: pytest.MonkeyPatch,
    stopper: ContainedOwnedStop,
    context: OwnedIssuedContext,
    *,
    running: bool = True,
    changes: dict[str, object] | None = None,
    kill_reply: bytes | None = None,
    wait_reply: bytes = b"137\n",
    post_running: bool = False,
) -> list[tuple[StopKind, int]]:
    calls: list[tuple[StopKind, int]] = []

    async def call(
        kind: StopKind,
        actual: OwnedIssuedContext,
        started: StartedContainedProcess,
        bound: ProcessRunBinding,
        end_us: int,
    ) -> StopCapture:
        assert actual is context
        assert started.owned_start is not None
        assert actual.require_owned_stop(started.owned_start, started.process, bound, end_us)
        calls.append((kind, end_us))
        body = {
            "inspect": inspected(context.seal.container, running, **(changes or {})),
            "kill": kill_reply
            if kill_reply is not None
            else context.seal.container.container_id.encode() + b"\n",
            "wait": wait_reply,
            "postinspect": inspected(context.seal.container, post_running),
        }[kind]
        return StopCapture(
            kind,
            stop_argv(kind, context.seal.container),
            12_020_000,
            12_020_001,
            888,
            body,
            b"",
            0,
            True,
            True,
            False,
        )

    monkeypatch.setattr(stopper.io, "call", call)
    return calls


@pytest.mark.parametrize("running", [True, False])
async def test_only_original_opaque_full_id_can_stop_or_wait_already_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, running: bool
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    stopper = ContainedOwnedStop(clock=lambda: 12_020_000)
    calls = install(monkeypatch, stopper, context, running=running)
    try:
        result = await stopper.stop(
            context, started, binding(), ObservationDeadline(end_us=13_000_000)
        )
        assert [kind for kind, _ in calls] == (
            ["inspect", "kill", "wait", "postinspect"]
            if running
            else ["inspect", "wait", "postinspect"]
        )
        assert result.container is context.seal.container and result.end_us == 13_000_000
        assert {end for _, end in calls} == {13_000_000}
        assert all(row.argv[-1] == context.seal.container.container_id for row in result.captures)
        assert not any("rm" in row.argv or "--all" in row.argv for row in result.captures)
    finally:
        item.owner.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"container_id": "f" * 64},
        {"container_name": "nexus-builder-foreign"},
        {"image_id": "f" * 64},
        {"company_id": str(UUID(int=9))},
        {"action_id": str(UUID(int=9))},
        {"running": "true"},
        {"foreign": True},
    ],
)
async def test_foreign_or_open_inspection_shape_never_reaches_kill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changes: dict[str, object]
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    stopper = ContainedOwnedStop(clock=lambda: 12_020_000)
    calls = install(monkeypatch, stopper, context, changes=changes)
    try:
        with pytest.raises(ValueError):
            await stopper.stop(context, started, binding(), ObservationDeadline(end_us=13_000_000))
        assert [kind for kind, _ in calls] == ["inspect"]
    finally:
        item.owner.close()


@pytest.mark.parametrize("variation", ["portable", "foreign-binding", "closed", "expired"])
async def test_portable_foreign_closed_and_expired_owners_issue_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, variation: str
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    stopper = ContainedOwnedStop(clock=lambda: 13_000_001 if variation == "expired" else 12_020_000)
    calls = install(monkeypatch, stopper, context)
    selected = (
        cast(OwnedIssuedContext, context.seal.container) if variation == "portable" else context
    )
    bound = (
        binding().model_copy(update={"task_id": UUID(int=9)})
        if variation == "foreign-binding"
        else binding()
    )
    if variation == "closed":
        item.owner.close()
    try:
        with pytest.raises((ValueError, TimeoutError)):
            await stopper.stop(selected, started, bound, ObservationDeadline(end_us=13_000_000))
        assert calls == []
    finally:
        item.owner.close()


@pytest.mark.parametrize("variation", ["kill-reply", "wait-reply", "still-running"])
async def test_partial_control_or_unstopped_final_object_cannot_become_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, variation: str
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    stopper = ContainedOwnedStop(clock=lambda: 12_020_000)
    calls = install(
        monkeypatch,
        stopper,
        context,
        kill_reply=b"foreign\n" if variation == "kill-reply" else None,
        wait_reply=b"137 extra\n" if variation == "wait-reply" else b"137\n",
        post_running=variation == "still-running",
    )
    try:
        with pytest.raises(ValueError):
            await stopper.stop(context, started, binding(), ObservationDeadline(end_us=13_000_000))
        assert len(calls) == {"kill-reply": 2, "wait-reply": 3, "still-running": 4}[variation]
    finally:
        item.owner.close()


async def test_reentry_is_denied_before_await_and_cannot_restart_shortened_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    stopper = ContainedOwnedStop(clock=lambda: 12_020_000)
    calls = install(monkeypatch, stopper, context)
    real = stopper.io.call
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(
        kind: StopKind,
        actual: OwnedIssuedContext,
        current: StartedContainedProcess,
        bound: ProcessRunBinding,
        end_us: int,
    ) -> StopCapture:
        entered.set()
        await release.wait()
        return await real(kind, actual, current, bound, end_us)

    monkeypatch.setattr(stopper.io, "call", delayed)
    first = asyncio.create_task(
        stopper.stop(context, started, binding(), ObservationDeadline(end_us=13_000_000))
    )
    try:
        await entered.wait()
        with pytest.raises(ValueError, match="repeated"):
            await stopper.stop(context, started, binding(), ObservationDeadline(end_us=13_000_000))
        assert calls == [] and not first.done()
        release.set()
        await first
        with pytest.raises(ValueError, match="repeated"):
            await stopper.stop(context, started, binding(), ObservationDeadline(end_us=13_000_000))
        assert len(calls) == 4
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)
        item.owner.close()


async def test_original_cli_exit_does_not_turn_full_id_into_unowned_pid_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    item.transport.kill()
    stopper = ContainedOwnedStop(clock=lambda: 12_020_000)
    calls = install(monkeypatch, stopper, context)
    try:
        await stopper.stop(context, started, binding(), ObservationDeadline(end_us=13_000_000))
        assert len(calls) == 4
    finally:
        item.owner.close()


def test_duplicate_fields_and_oversized_inspection_deny() -> None:
    from nexus.builder.contained_discovery import decode_discovery
    from nexus.tests.contained_process_fixture import launch
    from nexus.tests.unit.test_contained_discovery import body

    expected = decode_discovery(body(), launch(), runtime_pid=777)
    raw = inspected(expected, True)
    with pytest.raises(ValueError):
        decode_inspection(raw[:-1] + b',"running":true}', expected)
    with pytest.raises(ValueError):
        decode_inspection(b" " * 65537, expected)


async def test_new_stop_service_cannot_reissue_original_context_or_reset_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    first, replacement = (
        ContainedOwnedStop(clock=lambda: 12_020_000),
        ContainedOwnedStop(clock=lambda: 12_030_000),
    )
    initial = install(monkeypatch, first, context)
    extra = install(monkeypatch, replacement, context)
    try:
        await first.stop(context, started, binding(), ObservationDeadline(end_us=13_000_000))
        with pytest.raises(ValueError, match="repeated"):
            await replacement.stop(
                context, started, binding(), ObservationDeadline(end_us=13_000_000)
            )
        assert len(initial) == 4 and extra == []
    finally:
        item.owner.close()


@pytest.mark.parametrize("changed", ["seal", "transport"])
async def test_original_seal_and_transport_are_pinned_across_first_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changed: str
) -> None:
    import nexus.tests.issued_membership_fixture as fixture

    item, context, started = await owned(monkeypatch, tmp_path)
    from nexus.tests.unit.test_contained_discovery import body

    raw = json.loads(body())
    raw["container_id"] = "f" * 64
    monkeypatch.setattr(fixture, "body", lambda: json.dumps(raw).encode())
    replacement = await fixed_seal(monkeypatch)  # Another genuine supplied discovery seal.
    stopper = ContainedOwnedStop(clock=lambda: 12_020_000)
    calls = install(monkeypatch, stopper, context)
    original = stopper.io.call

    async def swapped(
        kind: StopKind,
        actual: OwnedIssuedContext,
        current: StartedContainedProcess,
        bound: ProcessRunBinding,
        end_us: int,
    ) -> StopCapture:
        result = await original(kind, actual, current, bound, end_us)
        if kind == "inspect":
            if changed == "seal":
                context.seal = replacement
            else:
                stopper.io = OwnedStopIO(clock=lambda: 12_020_000)
        return result

    monkeypatch.setattr(stopper.io, "call", swapped)
    try:
        with pytest.raises(ValueError):
            await stopper.stop(context, started, binding(), ObservationDeadline(end_us=13_000_000))
        assert [kind for kind, _ in calls] == ["inspect"]
    finally:
        item.owner.close()


async def test_first_stop_rejects_replaced_original_seal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import nexus.tests.issued_membership_fixture as fixture
    from nexus.tests.unit.test_contained_discovery import body

    item, context, started = await owned(monkeypatch, tmp_path)
    original = context.seal
    data = json.loads(body())
    data["container_id"] = "f" * 64
    monkeypatch.setattr(fixture, "body", lambda: json.dumps(data).encode())
    replacement = await fixed_seal(monkeypatch)
    assert original is not replacement
    assert original.container.container_id != replacement.container.container_id
    assert original.container.model_dump(exclude={"container_id"}) == (
        replacement.container.model_dump(exclude={"container_id"})
    )
    context.seal = replacement  # Before entering the stop service, not during an await.
    stopper = ContainedOwnedStop(clock=lambda: 12_020_000)
    calls = install(monkeypatch, stopper, context)
    try:
        with pytest.raises(ValueError):
            result = await stopper.stop(
                context, started, binding(), ObservationDeadline(end_us=13_000_000)
            )
            (tmp_path / "selected-seal-observation-1.json").write_text(
                json.dumps(
                    {
                        "original_cid": original.container.container_id,
                        "replacement_cid": replacement.container.container_id,
                        "selected_cid": result.container.container_id,
                        "calls": calls,
                        "argv": [list(row.argv) for row in result.captures],
                        "scope": "Finite supplied IO observation, no actual engine call",
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            )
        assert calls == []
    finally:
        context.seal = original
        item.owner.close()
