"""Pure acceptance descriptions only; supplied checker data is never actual E/EV acceptance."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.cycle_artifacts.action_parameters import PresentationCheckParameters
from nexus.company.cycle_artifacts.issued_facts import CycleVerifierFacts
from nexus.company.cycle_artifacts.publication_contracts import prepare_cycle_check
from nexus.company.management.canonical import canonical_sha256
from nexus.harness.canonical import action_hash
from nexus.tests.unit.cycle_deliverable_fixture import deliverable_case


@pytest.mark.parametrize("damage", [None, "receipt", "manifest", "snapshot", "output", "result"])
def test_acceptance_description_recomputes_every_issued_pin(damage: str | None) -> None:
    # Keep the >50-line supplied action/receipt/check construction and its single splice together.
    from nexus.company.cycle_artifacts.acceptance_store import build_cycle_acceptance

    case = deliverable_case()
    command = case.command()
    prepared = prepare_cycle_check(command, UUID(int=987), case.basis.data_classification)
    pins = PresentationCheckParameters(
        artifact_kind="presentation",
        author_action_id=case.action_id,
        verification_target_sha256=canonical_sha256(command.target),
        author_output_manifest_sha256=canonical_sha256(command.manifest),
        output_sha256=prepared.output_sha256,
        input_snapshot_sha256=prepared.input_snapshot_sha256,
        input_manifest_sha256=prepared.input_manifest_sha256,
    )
    action = ActionProposal(
        company_id=case.basis.company_id,
        action_id=prepared.action_id,
        task_id=case.basis.verifier.task_id,
        trace_id=case.basis.verifier.trace_id,
        actor_id=case.basis.verifier.actor_id,
        revision=1,
        tool="company.cycle-artifact.check.v1",
        tool_version="v1",
        resource="cycle.check",
        parameters=pins.model_dump(mode="json"),
        estimated_cost_usd="0.01",
        policy_version="p1",
        price_version="p1",
    )
    ref = prepared.artifact
    receipt = ActionReceipt(
        company_id=case.basis.company_id,
        receipt_id=UUID(int=988),
        action_id=action.action_id,
        task_id=action.task_id,
        trace_id=action.trace_id,
        proposal_hash=action_hash(action),
        outcome="succeeded",
        recorded_at=datetime.now(UTC),
        artifacts=(
            ArtifactRef(
                company_id=ref.company_id,
                artifact_id=ref.artifact_id,
                revision=ref.revision,
                sha256=ref.sha256,
                reference="supplied-pure-check",
            ),
        ),
    )
    facts = CycleVerifierFacts(action, receipt, 1, ref, pins)
    if damage == "receipt":
        facts = replace(facts, receipt=receipt.model_copy(update={"outcome": "failed"}))
    elif damage in {"manifest", "snapshot", "output"}:
        key = {
            "manifest": "author_output_manifest_sha256",
            "snapshot": "input_snapshot_sha256",
            "output": "output_sha256",
        }[damage]
        facts = replace(facts, parameters=pins.model_copy(update={key: "0" * 64}))
    body = prepared.raw_bytes + (b" " if damage == "result" else b"")
    if damage is None:
        value = build_cycle_acceptance(command, prepared, facts, body, datetime.now(UTC))
        assert value.verdict == "pass" and value.target.artifacts == tuple(
            row.artifact for row in case.prepared.manifest.parts
        )
        assert value.proofs[0].result_artifact == ref
    else:
        with pytest.raises(ValueError):
            build_cycle_acceptance(command, prepared, facts, body, datetime.now(UTC))


@pytest.mark.parametrize("damage", [None, "SQL_time", "proof_json", "extra_proof", "target"])
async def test_actual_acceptance_encoding_replay_rejects_row_and_embedded_splices(
    damage: str | None,
) -> None:
    from copy import deepcopy
    from datetime import timedelta
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.company.cycle_artifacts.acceptance_store import persist_cycle_acceptance_locked
    from nexus.company.management.acceptance import ProtectedCheckProof, WorkAcceptance
    from nexus.company.management.acceptance_models import (
        ManagementAcceptanceProof,
        ManagementWorkAcceptance,
    )

    case = deliverable_case()
    command = case.command()
    prepared = prepare_cycle_check(command, UUID(int=991), case.basis.data_classification)
    now = datetime.now(UTC)
    described = WorkAcceptance(
        company_id=command.company_id,
        acceptance_id=UUID(int=992),
        target=command.target,
        verdict="pass",
        limitations=("native_mechanical_only",),
        recorded_at=now,
        proofs=(
            ProtectedCheckProof(
                company_id=command.company_id,
                proof_id=UUID(int=993),
                recipe=command.target.check_recipe,
                target_sha256=canonical_sha256(command.target),
                result_artifact=prepared.artifact,
            ),
        ),
    )
    rows: list[object] = []
    session = MagicMock(spec=AsyncSession)
    session.add.side_effect, session.flush = rows.append, AsyncMock()

    async def get(model: type[object], key: object) -> object | None:
        return next((r for r in rows if isinstance(r, model)), None)

    async def scalars(statement: object) -> MagicMock:
        result = MagicMock()
        result.all.return_value = [r for r in rows if isinstance(r, ManagementAcceptanceProof)]
        return result

    session.get, session.scalars = AsyncMock(side_effect=get), AsyncMock(side_effect=scalars)
    # Only persistence delivery is supplied. The real encoding, immutable replay and proof
    # comparisons execute; no native engineering acceptance or caller permission is claimed.
    first = await persist_cycle_acceptance_locked(session, described)
    later = described.model_copy(update={"recorded_at": now + timedelta(seconds=1)})
    assert await persist_cycle_acceptance_locked(session, later) == first
    saved = next(r for r in rows if isinstance(r, ManagementWorkAcceptance))
    proof = next(r for r in rows if isinstance(r, ManagementAcceptanceProof))
    if damage is None:
        return
    if damage == "SQL_time":
        saved.recorded_at += timedelta(seconds=1)
    elif damage == "proof_json":
        proof.proof_json = "{}"
    elif damage == "extra_proof":
        extra = deepcopy(proof)
        extra.proof_id = UUID(int=994)
        rows.append(extra)
    else:
        saved.target_sha256 = "0" * 64
    with pytest.raises(ValueError):
        await persist_cycle_acceptance_locked(session, described)
    session.commit.assert_not_awaited()
