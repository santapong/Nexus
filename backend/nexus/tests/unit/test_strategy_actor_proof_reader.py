"""Actor wrapper ordering over mocked SQL/material boundaries; no actual native authority."""

from uuid import UUID

import pytest

from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.strategy.actor_proof_reader import StrategyActorProofReader
from nexus.tests.unit.strategy_actor_proof_support import actor_case


def test_reader_requires_real_configured_input_reader() -> None:
    with pytest.raises(AcceptanceDeniedError):
        StrategyActorProofReader(object())  # type: ignore[arg-type]


@pytest.mark.parametrize("verifier", [False, True])
async def test_actor_reads_derived_full_plan_choice_without_any_owner_scope(
    monkeypatch: pytest.MonkeyPatch, verifier: bool
) -> None:
    case = actor_case(monkeypatch, verifier=verifier)
    result = await case.read()
    assert result.binding == case.binding and result.candidate == case.candidate
    assert result.proof.selection == case.payload.strategy_selection
    assert result.profile_observed_at == case.materials[0].observed_at
    assert len(case.body_calls) == 2 and case.partitions.await_count == 2
    assert case.read_gate.await_count == 2
    for scope in case.body_calls:
        assert scope.principal_id == scope.actor_id == case.work.actor_id
        assert scope.task_id == case.work.task_id and scope.task_trace_id == case.work.trace_id
        assert scope.principal_id != case.control.owner_id
    case.session.add.assert_not_called()
    case.session.flush.assert_not_called()
    case.session.commit.assert_not_called()


@pytest.mark.parametrize("who", ["owner", "author", "verifier", "foreign"])
async def test_borrowed_credential_denies_before_material(
    monkeypatch: pytest.MonkeyPatch, who: str
) -> None:
    case = actor_case(monkeypatch)
    credential = case.witness(who)
    with pytest.raises(AcceptanceDeniedError):
        await case.service.load_selected_locked(
            case.session, case.control, case.work, credential.identity, credential=credential
        )
    assert not case.body_calls


async def test_bare_identity_is_not_a_genuine_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    case = actor_case(monkeypatch)
    with pytest.raises(AcceptanceDeniedError):
        await case.service.load_selected_locked(
            case.session,
            case.control,
            case.work,
            case.credential.identity,
            credential=case.credential.identity,  # type: ignore[arg-type]
        )
    assert not case.body_calls


@pytest.mark.parametrize(
    "which",
    [
        "transaction",
        "pause",
        "company",
        "blocked",
        "outcome_unknown",
        "run",
        "trace",
        "missing_binding",
        "missing_plan",
        "stage_one",
        "missing_choice",
    ],
)
async def test_unavailable_current_actor_or_plan_denies_before_bodies(
    monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    case = actor_case(monkeypatch)
    case.break_entry(which)
    with pytest.raises((AcceptanceDeniedError, ValueError)):
        await case.read()
    assert not case.body_calls


async def test_missing_task_read_denies_before_material(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexus.company.brain.scope_support import BrainDeniedError

    case = actor_case(monkeypatch)
    case.read_gate.side_effect = BrainDeniedError("nominated current task READ denial")
    with pytest.raises(BrainDeniedError):
        await case.read()
    assert not case.body_calls


@pytest.mark.parametrize("read_number", [1, 2])
async def test_actual_material_graph_or_read_failure_is_not_replaced(
    monkeypatch: pytest.MonkeyPatch, read_number: int
) -> None:
    case = actor_case(monkeypatch)
    case.material_failure = read_number
    with pytest.raises(AcceptanceDeniedError):
        await case.read()
    assert len(case.body_calls) == read_number


@pytest.mark.parametrize("which", ["fence", "binding", "head", "blocked", "membership"])
async def test_final_current_actor_checks_happen_after_body_awaits(
    monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    case = actor_case(monkeypatch)
    case.after_second = lambda: case.break_final(which)
    with pytest.raises((AcceptanceDeniedError, ValueError)):
        await case.read()
    assert len(case.body_calls) == 2


async def test_caller_cannot_supply_a_choice_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    case = actor_case(monkeypatch)
    with pytest.raises(TypeError):
        await case.service.load_selected_locked(
            case.session,
            case.control,
            case.work,
            case.credential.identity,
            credential=case.credential,
            selection=UUID(int=999),
        )  # type: ignore[call-arg]
    assert not case.body_calls
