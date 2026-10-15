"""Component delivery denials/configuration windows; no accepted native Engineering positive."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.cycle_artifacts.native_contracts import CurrentEngineeringProof
from nexus.company.cycle_artifacts.original_reader import CycleOriginalReader
from nexus.company.cycle_artifacts.publication_contracts import CyclePhase
from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.management.plan_admission_window import PlanGrantWindow
from nexus.tests.unit.cycle_prerequisite_fixture import signed_identity
from nexus.tests.unit.cycle_publication_fixture import described_lease, input_reader
from nexus.tests.unit.cycle_publication_row_fixture import row_case
from nexus.tests.unit.strategy_publication_reader_fixture import Policies


@pytest.mark.parametrize("slot", [0, 1, 2, 3, 5, 7, 8, 9, 10])
async def test_author_wrong_actual_catalog_role_denies_before_engineering_io(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    slot: int,
) -> None:
    reader = input_reader(monkeypatch, tmp_path)
    lease = described_lease(reader, slot)
    identity = VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id)
    load = AsyncMock(side_effect=AssertionError("wrong role reached Engineering READ"))
    monkeypatch.setattr(reader.engineering, "load", load)
    with pytest.raises(AcceptanceDeniedError):
        await reader.prepare_author(
            lease, identity, uuid4(), credential=await signed_identity(identity)
        )
    load.assert_not_called()


@pytest.mark.parametrize("slot", [0, 1, 2, 3, 4, 6, 8, 9, 10])
async def test_check_wrong_role_denies_before_original_body_io(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    slot: int,
) -> None:
    inputs = input_reader(monkeypatch, tmp_path)
    reader = CycleOriginalReader(inputs)
    lease = described_lease(inputs, slot)
    identity = VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id)
    load = AsyncMock(side_effect=AssertionError("wrong role reached original body"))
    monkeypatch.setattr(reader.engineering, "load", load)
    with pytest.raises(AcceptanceDeniedError):
        await reader.prepare_check(
            lease, identity, uuid4(), uuid4(), credential=await signed_identity(identity)
        )
    load.assert_not_called()


@pytest.mark.parametrize(
    "index,phase,kind",
    [
        (4, "write", "presentation"),
        (5, "check", "presentation"),
        (6, "write", "support"),
        (7, "check", "support"),
    ],
)
def test_catalog_only_selectors_keep_independent_phase_and_shared_targets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    index: int,
    phase: str,
    kind: str,
) -> None:
    reader = input_reader(monkeypatch, tmp_path)
    lease = described_lease(reader, index)
    identity = VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id)
    rule = reader._lease_rule(lease, identity, cast(CyclePhase, phase))
    assert (rule.kind, rule.phase) == (kind, phase)
    assert reader.rules.write_target == reader.rules.rule("support", "write").target
    assert reader.rules.check_target == reader.rules.rule("support", "check").target
    with pytest.raises(AcceptanceDeniedError):
        reader.scope(lease, identity.model_copy(update={"principal_id": uuid4()}), uuid4())


@pytest.mark.parametrize(
    "replacement", ["store", "rules", "policy", "policy_type", "blob", "factory"]
)
def test_original_composition_rejects_post_await_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    replacement: str,
) -> None:
    inputs = input_reader(monkeypatch, tmp_path)
    reader = CycleOriginalReader(inputs)
    original = reader.composition()
    if replacement == "store":
        store = inputs.engineering.containment_store
        assert store is not None
        inputs.engineering.containment_store = ContainmentEvidenceStore(store.root)
    elif replacement == "rules":
        inputs.rules = type(inputs.rules)(inputs.catalog, inputs.rules.policies)
    elif replacement in {"policy", "policy_type"}:
        policies = cast(Policies, inputs.rules.policies)
        value = policies.values["generated.presentation-json.v1"]
        policies.values[value.source_symbol] = value.model_copy(
            update={"max_bytes": float(value.max_bytes) if replacement == "policy_type" else 1}
        )
    elif replacement == "blob":
        monkeypatch.setattr(inputs.artifacts, "blobs", object())
    else:
        monkeypatch.setattr(inputs.engineering, "factory", object())
    with pytest.raises((AcceptanceDeniedError, ValidationError)):
        reader.require_composition(original)


async def test_capture_keeps_actual_recipient_grant_generations_and_original_expiry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    reader = input_reader(monkeypatch, tmp_path)
    lease = described_lease(reader, 4)
    identity = VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id)
    scope = reader.scope(lease, identity, uuid4())
    supplied = row_case().case.basis.inputs
    resources = tuple(
        sorted({reader.rules.write_target.resource_id, reader.rules.check_target.resource_id})
    )
    inputs = supplied.model_copy(
        update={"company_id": lease.company_id, "required_resource_ids": resources}
    )
    now, recipient = datetime.now(UTC), uuid4()
    deadline = now + timedelta(seconds=1)
    target_rows = [
        BrainResourceAccess(
            company_id=lease.company_id,
            resource_id=key,
            principal_id=recipient,
            active=True,
            generation=7,
            expires_at=deadline,
        )
        for key in resources
    ]
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=now)
    delivered = MagicMock()
    delivered.all.return_value = target_rows[:1]
    session.scalars = AsyncMock(return_value=delivered)

    async def get(model: type[object], key: object) -> object:
        if model is BrainResource:
            return BrainResource(
                company_id=lease.company_id,
                resource_id=resources[0],
                kind="artifact",
                active=True,
                acl_generation=3,
            )
        if model is DirectoryMembership:
            return DirectoryMembership(principal_active=True, membership_active=True)
        if model is BrainResourceAccess:
            return BrainResourceAccess(active=True, generation=7, expires_at=deadline)
        raise AssertionError(model)

    session.get = AsyncMock(side_effect=get)
    read_rows = MagicMock()
    read_rows.all.return_value = [
        (await get(BrainResource, key), await get(BrainResourceAccess, key)) for key in resources
    ]
    session.execute = AsyncMock(return_value=read_rows)
    proof = MagicMock(spec=CurrentEngineeringProof)
    protection = await reader._capture(session, scope, proof, inputs, reader.composition())
    assert {value.principal_id for value in protection.grants} == {identity.principal_id, recipient}
    assert all(
        (value.resource_generation, value.grant_generation, value.expires_at) == (3, 7, deadline)
        for value in protection.grants
    )
    assert len(protection.grants) == len(resources) * 2
    with pytest.raises(AcceptanceDeniedError):
        protection.require_time(deadline)
    changed = replace(
        protection, grants=(PlanGrantWindow(resources[0], recipient, 3, 8, deadline),)
    )
    with pytest.raises(AcceptanceDeniedError):
        protection.require_same_scope(changed)
    proof.require_time.assert_called()


def test_check_requires_private_exact_registered_policy() -> None:
    row = row_case("support")
    policy = row.check_rule.policy("check")
    assert isinstance(policy, SourcePolicy) and policy.origin_kind == "derived"
    assert policy.data_classification == "internal"


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "revision",
        "sha",
        "length",
        "resource",
        "media",
        "storage",
        "class",
        "duplicate",
        "reverse",
    ],
)
async def test_actual_projection_checks_both_namespaces_without_selecting_raw_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault: str,
) -> None:
    from nexus.company.contracts.knowledge import ArtifactRef
    from nexus.company.contracts.results import ActionReceipt

    inputs = input_reader(monkeypatch, tmp_path)
    reader, row = CycleOriginalReader(inputs), row_case()
    case = row.case
    lease = described_lease(inputs, 5)
    scope = reader.scope(
        lease,
        VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id),
        uuid4(),
    )
    scope = scope.model_copy(update={"company_id": case.basis.company_id})
    rule = reader.rules.rule("presentation", "check")
    refs = tuple(part.artifact for part in row.prepared.manifest.parts)
    receipt = ActionReceipt(
        company_id=scope.company_id,
        receipt_id=uuid4(),
        action_id=case.action_id,
        task_id=case.basis.author.task_id,
        trace_id=case.basis.author.trace_id,
        proposal_hash="a" * 64,
        outcome="succeeded",
        recorded_at=datetime.now(UTC),
        artifacts=tuple(
            ArtifactRef(
                company_id=scope.company_id,
                artifact_id=ref.artifact_id,
                revision=ref.revision,
                sha256=ref.sha256,
                reference=f"brain:{ref.artifact_revision_id}",
            )
            for ref in refs
        ),
    )
    if fault == "reverse":
        receipt = receipt.model_copy(update={"artifacts": tuple(reversed(receipt.artifacts))})
    delivered = []
    write = reader.rules.rule("presentation", "write")
    for part, ref in zip(write.parts, refs, strict=True):
        delivered.append(
            [
                ref.artifact_revision_id,
                ref.sha256,
                ref.byte_length,
                write.target.resource_id,
                write.policy(part).media_type,
                reader.blobs.storage_symbol,
                "internal",
                receipt.recorded_at,
            ]
        )
    changes: dict[str, tuple[int, object]] = {
        "revision": (0, uuid4()),
        "sha": (1, "f" * 64),
        "length": (2, 0),
        "resource": (3, uuid4()),
        "media": (4, "text/plain"),
        "storage": (5, "other.private"),
        "class": (6, "public"),
    }
    if fault in changes:
        key, value = changes[fault]
        delivered[1][key] = value
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=receipt.recorded_at)
    queries = []

    async def execute(statement: object) -> MagicMock:
        queries.append(str(statement))
        result = MagicMock()
        result.all.return_value = [delivered[len(queries) - 1]] * (2 if fault == "duplicate" else 1)
        return result

    session.execute = AsyncMock(side_effect=execute)
    if fault == "none":
        assert await reader._references(session, scope, rule, case.action_id, receipt) == refs
        assert len(queries) == 2
    else:
        with pytest.raises(AcceptanceDeniedError):
            await reader._references(session, scope, rule, case.action_id, receipt)
    assert (queries or fault == "reverse") and all(
        "raw_text" not in statement for statement in queries
    )
    session.get.assert_not_called()


def test_retained_source_and_body_windows_do_not_accept_later_deadline() -> None:
    from nexus.company.cycle_artifacts.publication_contracts import CycleReadProtection
    from nexus.company.management.acceptance_freshness import QualifiedFreshness
    from nexus.company.management.plan_admission_window import PlanSourceWindow
    from nexus.tests.unit.engineering_body_fixture import described_body

    now = datetime.now(UTC)
    proof = MagicMock(spec=CurrentEngineeringProof)
    policy = (
        row_case("support").check_rule.policy("check").model_copy(update={"freshness_seconds": 1})
    )
    source, revision = uuid4(), uuid4()
    first = QualifiedFreshness(source, policy, now + timedelta(seconds=1), True)
    retained = CycleReadProtection(
        proof,
        (),
        (first,),
        (PlanSourceWindow(source, revision, 1, now, first),),
        now,
        (),
        (described_body(b"complete private original"),),
    )
    renewed = replace(first, fresh_until=now + timedelta(seconds=60))
    current = replace(
        retained,
        freshness=(renewed,),
        sources=(PlanSourceWindow(source, revision, 1, now, renewed),),
    )
    with pytest.raises(AcceptanceDeniedError):
        retained.require_same_scope(current)
    with pytest.raises(AcceptanceDeniedError):
        retained.require_time(now + timedelta(seconds=1))
