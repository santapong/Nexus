"""Retained actor/current Strategy windows over explicit mocked SQL/material boundaries."""

from dataclasses import replace
from datetime import timedelta

import pytest

from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.notifications.worker_identity import WorkerIdentityDeniedError
from nexus.tests.unit.strategy_actor_proof_support import actor_case
from nexus.tests.unit.strategy_transition_observation_data import _work


@pytest.mark.parametrize("which", [0, 1])
@pytest.mark.parametrize("kind", ["target", "source"])
async def test_final_clock_keeps_each_initial_current_window_after_last_read(
    monkeypatch: pytest.MonkeyPatch, which: int, kind: str
) -> None:
    case = actor_case(monkeypatch)
    deadline = case.clock["now"] + timedelta(seconds=1)
    material = case.materials[which]
    protection = material.material.protection
    if kind == "target":
        protection = replace(
            protection,
            grants=tuple(
                row.model_copy(update={"expires_at": deadline}) for row in protection.grants
            ),
        )
    else:
        protection = replace(
            protection,
            sources=replace(
                protection.sources,
                grants=tuple(
                    row.model_copy(update={"expires_at": deadline})
                    for row in protection.sources.grants
                ),
            ),
        )
    case.materials[which] = replace(
        material,
        material=replace(material.material, protection=protection),
        original=replace(material.original, protection=protection),
    )

    async def read_gate(*args: object) -> None:
        if len(case.body_calls) == 2:
            case.clock["now"] = deadline

    case.read_gate.side_effect = read_gate
    with pytest.raises(AcceptanceDeniedError):
        await case.read()
    assert len(case.body_calls) == case.read_gate.await_count == 2


async def test_actor_credential_expires_during_final_read_without_an_owner_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = actor_case(monkeypatch)
    for index, material in enumerate(case.materials):
        read = material.material.protection
        read = replace(
            read,
            grants=tuple(row.model_copy(update={"expires_at": None}) for row in read.grants),
            sources=replace(read.sources, grants=()),
        )
        case.materials[index] = replace(
            material,
            material=replace(material.material, protection=read),
            original=replace(material.original, protection=read),
        )

    async def final_read(*args: object) -> None:
        if len(case.body_calls) == 2:
            case.clock["now"] = case.credential.expires_at

    case.read_gate.side_effect = final_read
    with pytest.raises(WorkerIdentityDeniedError):
        await case.read()
    assert len(case.body_calls) == 2


@pytest.mark.parametrize("field", ["author_current_fence", "verifier_current_fence"])
async def test_frozen_strategy_fence_changes_cannot_hide_behind_shared_orm_objects(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    case = actor_case(monkeypatch)
    case.materials[1] = (
        replace(case.materials[1], author_current_fence=3)
        if field == "author_current_fence"
        else replace(case.materials[1], verifier_current_fence=3)
    )
    with pytest.raises(AcceptanceDeniedError):
        await case.read()
    assert len(case.body_calls) == 2 and case.read_gate.await_count == 1


async def test_original_policy_must_equal_current_server_production_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = actor_case(monkeypatch)
    case.service.reader.production_policy = case.service.reader.production_policy.model_copy(
        update={"scope_sha256": "e" * 64}
    )
    with pytest.raises(AcceptanceDeniedError):
        await case.read()
    assert len(case.body_calls) == 2


@pytest.mark.parametrize("index", [0, 1, 4, 10])
async def test_other_real_configured_role_cannot_read_as_selected_engineering(
    monkeypatch: pytest.MonkeyPatch, index: int
) -> None:
    case = actor_case(monkeypatch)
    configured = case.service.reader.catalog.cycle_admission
    assert configured is not None
    slot = configured.slots[index]
    case.work = _work(configured, index)
    case.credential = case.witness()
    case.binding_read.return_value = case.binding.model_copy(
        update={"child": slot.child, "work": slot.work, "work_sha256": case.work.registration_hash}
    )
    with pytest.raises(AcceptanceDeniedError):
        await case.read()
    assert not case.body_calls and case.partitions.await_count == 0


@pytest.mark.parametrize("at_final", [False, True])
async def test_actual_family_gate_failure_is_not_replaced_by_a_pass_flag(
    monkeypatch: pytest.MonkeyPatch, at_final: bool
) -> None:
    case = actor_case(monkeypatch)
    failure = AcceptanceDeniedError("nominated actual native partition denial")
    case.partitions.side_effect = [None, failure] if at_final else failure
    with pytest.raises(AcceptanceDeniedError):
        await case.read()
    assert len(case.body_calls) == (2 if at_final else 0)


async def test_returned_observation_retains_expiry_and_first_profile_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = actor_case(monkeypatch)
    result = await case.read()
    assert result.profile_observed_at == case.materials[0].observed_at
    result.require_time(case.clock["now"])
    with pytest.raises(AcceptanceDeniedError):
        result.require_time(case.clock["now"] + timedelta(seconds=61))


@pytest.mark.parametrize("which", [0, 1])
async def test_actor_argument_cannot_retain_a_borrowed_owner_material_window(
    monkeypatch: pytest.MonkeyPatch, which: int
) -> None:
    case = actor_case(monkeypatch)
    material = case.materials[which]
    read = material.material.protection
    read = replace(read, sources=replace(read.sources, credential=case.witness("owner")))
    case.materials[which] = replace(
        material,
        material=replace(material.material, protection=read),
        original=replace(material.original, protection=read),
    )
    with pytest.raises(AcceptanceDeniedError):
        await case.read()


async def test_current_task_read_is_after_partition_awaits_at_each_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = actor_case(monkeypatch)
    events: list[str] = []

    async def partition(*args: object, **kwargs: object) -> None:
        events.append("partition")

    async def read(*args: object) -> None:
        events.append("task_READ")

    case.partitions.side_effect = partition
    case.read_gate.side_effect = read
    await case.read()
    assert events == ["partition", "task_READ", "partition", "task_READ"]
