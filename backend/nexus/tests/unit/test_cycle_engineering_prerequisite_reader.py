"""Own reader scope and early stale-lease denials use actual methods, no accepted E stub."""

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from nexus.company.cycle_artifacts.engineering_prerequisite_reader import CycleEngineeringReader
from nexus.execution.runtime_models import ExecutionWork
from nexus.tests.unit.cycle_prerequisite_fixture import (
    NOW,
    deliverable_case,
    own_lease,
    signed_identity,
)

if TYPE_CHECKING:
    from pathlib import Path


async def test_own_scope_never_impersonates_an_engineering_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = deliverable_case(monkeypatch)
    lease = own_lease(case)
    scope = CycleEngineeringReader.scope(lease, case.identity)
    assert (scope.task_id, scope.actor_id, scope.principal_id, scope.workspace_id) == (
        case.work.task_id,
        case.work.actor_id,
        case.work.actor_id,
        case.work.workspace_id,
    )
    assert scope.task_id != case.executions[4].task_id
    foreign = case.identity.model_copy(update={"principal_id": case.executions[4].actor_id})
    with pytest.raises(ValueError):
        CycleEngineeringReader.scope(lease, foreign)


@pytest.mark.parametrize("change", ["expiry", "fence", "principal", "reconcile", "renewed"])
async def test_actual_stale_own_lease_denies_before_partition_or_body(
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    case = deliverable_case(monkeypatch)
    lease = own_lease(case)
    credential = await signed_identity(case.identity)
    if change == "expiry":
        case.work.lease_until = NOW - timedelta(seconds=1)
    elif change == "fence":
        case.work.fence += 1
    elif change == "principal":
        case.work.lease_principal_id = UUID(int=999)
    elif change == "reconcile":
        case.work.lease_mode = "reconcile"
    else:
        lease = lease.model_copy(update={"expires_at": NOW - timedelta(seconds=1)})

    async def scalar(statement: object) -> object:
        if "pg_roles" in str(statement):
            return False
        if "clock_timestamp" in str(statement):
            return NOW
        assert statement.column_descriptions[0]["entity"] is ExecutionWork  # type: ignore[attr-defined]
        return case.work

    case.session.scalar = AsyncMock(side_effect=scalar)
    reader = MagicMock(spec=CycleEngineeringReader)
    reader.scope.side_effect = CycleEngineeringReader.scope
    with pytest.raises(ValueError):
        await CycleEngineeringReader._actor(
            reader, case.session, case.control, lease, case.identity, credential
        )
    case.session.get.assert_not_awaited()


async def test_unissued_signed_identity_cannot_be_a_permission_boolean() -> None:
    from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity

    with pytest.raises(ValueError):
        AuthenticatedWorkerIdentity(True, NOW, NOW + timedelta(seconds=1))  # type: ignore[arg-type]


def test_complete_protected_digest_detects_a_spliced_private_result() -> None:
    import json

    from nexus.builder.result_store import BuilderResultStore
    from nexus.company.cycle_artifacts.engineering_prerequisite_material import require_result_body
    from nexus.tests.engineering_check_support import check_input
    from nexus.tests.unit.engineering_body_fixture import described_body

    value = check_input()
    result = value.author
    raw = json.dumps(
        {
            "spec": result.spec.model_dump(mode="json"),
            "result_sha256": BuilderResultStore.digest(result),
            "proposal_sha256": result.proposal_sha256,
            "intent_fence": result.intent_fence,
            "engineering_source_witness": value.author_witness.model_dump(mode="json"),
        }
    ).encode()
    body = described_body(raw, company=value.company_id)
    assert require_result_body(result, body) == value.author_witness
    changed = result.model_copy(update={"elapsed_millis": result.elapsed_millis + 1})
    with pytest.raises(ValueError):
        require_result_body(changed, body)


@pytest.mark.parametrize("change", ["object", "catalog", "shape"])
def test_composition_change_cannot_survive_later_awaits(change: str) -> None:
    from nexus.company.cycle_artifacts.native_contracts import require_matching_composition

    configured = object()
    first = (configured, ("original catalog", "original policies"))
    current = (
        (object(), first[-1])
        if change == "object"
        else (
            (configured, ("different catalog", "original policies")) if change == "catalog" else ()
        )
    )
    require_matching_composition(first, first)
    with pytest.raises(ValueError):
        require_matching_composition(current, first)


async def test_same_path_containment_store_swap_after_await_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: "Path",
) -> None:
    import asyncio

    from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
    from nexus.tests.unit.cycle_prerequisite_fixture import configured_reader

    reader = configured_reader(monkeypatch, tmp_path)
    first = reader.composition()
    original = reader.containment_store
    assert original is not None

    async def awaited_metadata() -> None:
        await asyncio.sleep(0)
        reader.containment_store = ContainmentEvidenceStore(original.root)

    await awaited_metadata()
    assert reader.containment_store is not None and reader.containment_store is not original
    assert reader.containment_store.root == original.root
    with pytest.raises(ValueError):
        reader.require_composition(first)


@pytest.mark.parametrize("side", ["author", "verifier"])
@pytest.mark.parametrize("damage", ["missing", "corrupt"])
async def test_retained_revalidate_rereads_actual_original_sidecars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: "Path",
    side: str,
    damage: str,
) -> None:
    """Prior qualification delivery is mocked; real sidecar bytes deny before a later gate.

    Synthetic local result descriptions are not an accepted engineering pair. No native E
    positive/permission is manufactured; this isolates the real retained-revalidation loop.
    """
    from types import SimpleNamespace
    from typing import cast

    from nexus.builder.verification_support import require_result_containment
    from nexus.company.cycle_artifacts import engineering_prerequisite_reader as module
    from nexus.company.cycle_artifacts.native_contracts import CurrentEngineeringProof
    from nexus.tests.contained_sidecar_fixture import contained_result
    from nexus.tests.unit.cycle_prerequisite_fixture import configured_reader
    from nexus.tests.unit.engineering_body_fixture import described_body

    case = deliverable_case(monkeypatch)
    lease, credential = own_lease(case), await signed_identity(case.identity)
    reader = configured_reader(monkeypatch, tmp_path)
    author, store = await contained_result(tmp_path)
    verifier, _ = await contained_result(tmp_path)
    assert author.containment is not None and verifier.containment is not None
    assert author.containment.identity != verifier.containment.identity
    reader.containment_store = store
    for result in (author, verifier):
        await require_result_containment(result, store, reader.execution_method_sha256)
    original_read = store.load_exact
    reads = AsyncMock(wraps=original_read)
    monkeypatch.setattr(store, "load_exact", reads)
    selected = author if side == "author" else verifier
    assert selected.containment is not None
    path = store.root / store.filename(selected.containment.identity)
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"{}")
    body = described_body(b"retained body")
    facts = SimpleNamespace(
        metadata=SimpleNamespace(
            author_output=body.first.artifact, verifier_output=body.first.artifact
        )
    )
    protection = SimpleNamespace(
        credential=credential,
        lease=lease,
        grants=(),
        grant_rows=(),
        source_rows=(),
        versions=("p1", "p1"),
    )
    proof = cast(
        CurrentEngineeringProof,
        SimpleNamespace(
            initial=protection,
            material=SimpleNamespace(
                facts=facts,
                command=SimpleNamespace(author=author, verifier=verifier),
                bodies=(body,),
            ),
        ),
    )
    # Only prior material/native observation delivery is mocked. The nominated containment
    # validator, filesystem store and final method loop always execute their actual code.
    monkeypatch.setattr(module, "require_engineering_material", lambda *args: None)
    monkeypatch.setattr(
        reader,
        "_actor",
        AsyncMock(return_value=(case.work, None, reader.scope(lease, case.identity))),
    )
    monkeypatch.setattr(reader, "_observe", AsyncMock(return_value=(facts, protection, None)))
    case.session.scalar = AsyncMock(return_value=NOW)
    references = AsyncMock(return_value=body.first.artifact)
    monkeypatch.setattr(module, "actual_result_reference", references)
    later = AsyncMock(side_effect=AssertionError("continued past unchecked private sidecar"))
    monkeypatch.setattr(module, "revalidate_complete_engineering_artifact_locked", later)
    with pytest.raises((FileNotFoundError, ValueError)):
        await reader.revalidate_locked(
            case.session,
            case.control,
            case.work,
            lease,
            case.identity,
            proof,
            credential=credential,
        )
    expected = 1 if side == "author" else 2
    assert reads.await_count == references.await_count == expected
    assert reads.await_args is not None
    assert reads.await_args.args == (selected.containment, selected.containment.identity)
    later.assert_not_awaited()
    case.session.add.assert_not_called()
    case.session.flush.assert_not_called()
