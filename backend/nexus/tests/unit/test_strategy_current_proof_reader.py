"""Current owner proof reads use actual native facts, never an SV lease or a supplied PASS."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.notifications.worker_identity import WorkerIdentityDeniedError
from nexus.company.strategy.current_proof_reader import StrategyCurrentProofReader
from nexus.tests.unit.strategy_current_proof_fixture import proof_case


async def test_real_owner_reads_original_proof_without_writes_or_sv_impersonation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = proof_case(monkeypatch)
    result = await case.read()
    assert result.selection == case.selection and result.acceptance == case.record
    assert (result.author_original_fence, result.verifier.original_intent_fence) == (1, 1)
    assert (result.author_current_fence, result.verifier_current_fence) == (2, 3)
    assert case.scope.task_id is None and case.scope.principal_id not in {
        case.record.target.author.actor_id,
        case.record.target.verifier.actor_id,
    }
    case.session.add.assert_not_called()
    case.session.flush.assert_not_called()
    case.session.commit.assert_not_called()
    assert case.graph_calls["B/S"] == 2 and case.graph_calls["C"] == 2


@pytest.mark.parametrize("actor", ["author", "verifier"])
@pytest.mark.parametrize("state", ["blocked", "outcome_unknown"])
async def test_logical_s_and_sv_unavailable_even_with_succeeded_receipt(
    monkeypatch: pytest.MonkeyPatch, actor: str, state: str
) -> None:
    case = proof_case(monkeypatch)
    getattr(case.pair, actor).state = state
    with pytest.raises(AcceptanceDeniedError):
        await case.read()


@pytest.mark.parametrize("change", ["role", "owner", "member", "workspace", "privileged"])
async def test_current_actual_owner_and_restricted_role_are_required(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    case = proof_case(monkeypatch)
    if change == "role":
        case.member.role = "admin"
    elif change == "owner":
        case.company.owner_id = UUID(int=999)
    elif change == "member":
        case.member.membership_active = False
    elif change == "workspace":
        case.company.workspace_id = UUID(int=999)
    else:
        case.privileged[0] = True
    with pytest.raises((BrainDeniedError, AcceptanceDeniedError)):
        await case.read()
    assert case.body_gets == []


@pytest.mark.parametrize(
    "which",
    ["receipt", "action", "attempt", "extra_action", "no_action", "graph", "bytes", "invalidated"],
)
async def test_crossed_current_proof_denies_without_repair(
    monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    case = proof_case(monkeypatch)
    case.break_proof(which)
    with pytest.raises(AcceptanceDeniedError):
        await case.read()
    case.session.add.assert_not_called()
    case.session.flush.assert_not_called()


async def test_c_complete_read_denial_precedes_c_body_get(monkeypatch: pytest.MonkeyPatch) -> None:
    case = proof_case(monkeypatch)

    async def denied(*args: object, **kwargs: object) -> None:
        reference = args[4]
        if reference == case.check_ref:
            raise BrainDeniedError("nominated C READ denial")

    monkeypatch.setattr(
        case.reader.artifacts, "revalidate_artifact_reference", AsyncMock(side_effect=denied)
    )
    with pytest.raises(BrainDeniedError, match="nominated"):
        await case.read()
    assert case.check_ref.artifact_revision_id not in case.body_gets


@pytest.mark.parametrize("which", ["initial", "current", "credential"])
async def test_final_clock_keeps_both_read_windows_after_last_await(
    monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    case = proof_case(monkeypatch)
    case.expire_at_final(which)
    error = WorkerIdentityDeniedError if which == "credential" else AcceptanceDeniedError
    with pytest.raises(error):
        await case.read()
    assert case.owner_reads[0] == 4
    assert case.graph_calls == {"B/S": 2, "C": 2}


def test_current_reader_requires_concrete_configured_composition() -> None:
    with pytest.raises(AcceptanceDeniedError):
        StrategyCurrentProofReader(object())  # type: ignore[arg-type]


@pytest.mark.parametrize("change", ["candidate", "scope_hash", "brief", "acceptance", "task_scope"])
async def test_selection_and_taskless_scope_are_exact(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    case = proof_case(monkeypatch)
    if change == "candidate":
        case.selection = case.selection.model_copy(update={"candidate_id": "not-reviewed"})
    elif change == "scope_hash":
        case.selection = case.selection.model_copy(update={"candidate_scope_sha256": "b" * 64})
    elif change == "brief":
        case.selection = case.selection.model_copy(
            update={"brief": case.selection.brief.model_copy(update={"sha256": "b" * 64})}
        )
    elif change == "acceptance":
        case.selection = case.selection.model_copy(update={"acceptance_id": UUID(int=999)})
    else:
        actor = case.record.target.verifier
        case.scope = case.scope.model_copy(
            update={
                "task_id": actor.task_id,
                "task_trace_id": actor.trace_id,
                "actor_id": actor.actor_id,
            }
        )
    error = ValueError if change == "candidate" else AcceptanceDeniedError
    with pytest.raises(error) as denied:
        await case.read()
    assert type(denied.value) is error
    case.session.add.assert_not_called()


async def test_returned_windows_still_deny_after_later_caller_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = proof_case(monkeypatch)
    result = await case.read()
    assert result.original.prepared.brief == case.selection.brief
    assert result.original.receipt.receipt_id == case.record.target.receipt_id
    assert result.original.original_intent_fence == 1
    expires = case.base.source.grant.expires_at
    assert expires is not None
    with pytest.raises(AcceptanceDeniedError):
        result.require_time(expires)
    result.require_time(result.observed_at)
