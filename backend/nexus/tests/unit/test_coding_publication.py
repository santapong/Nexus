"""Finite native delivery with real protected bytes/parser; not a SQL/provider proof.

Cohesion exception: real paired-row replay, source revocation and actual retained
IO ownership/first-cutoff checks stay together against their shared fixed fixture.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.company.management.coding_publication_contracts import (
    CodingPublicationRead,
    CodingPublicationRules,
    publication_identity,
)
from nexus.tests.unit.coding_publication_fixture import graph, native_files, rules, supplied_case
from nexus.tests.unit.test_coding_intent import prepared_case


def test_only_exact_server_registered_derived_sources_and_fixed_recipients_are_configurable() -> (
    None
):
    value = rules()
    assert value.origin.resource != value.patch.resource
    for field, changed in (
        ("patch", value.patch.model_copy(update={"source_id": UUID(int=999)})),
        ("patch_policy", value.patch_policy.model_copy(update={"origin_kind": "direct"})),
        (
            "patch_policy",
            value.patch_policy.model_copy(update={"authority_profile": "owner.primary.v1"}),
        ),
        ("readers", (value.readers[0], value.readers[0])),
    ):
        with pytest.raises(ValueError):
            CodingPublicationRules.model_validate_json(
                value.model_copy(update={field: changed}).model_dump_json()
            )


def test_publication_identity_is_not_model_artifact_identity_or_date_dependent() -> None:
    prepared, _, _, _ = prepared_case()
    first = publication_identity(
        prepared.request.company_id,
        prepared.request.action_id,
        prepared.request_sha256,
        "code_patch",
        b"actual patch bytes",
    )
    assert first == publication_identity(
        prepared.request.company_id,
        prepared.request.action_id,
        prepared.request_sha256,
        "code_patch",
        b"actual patch bytes",
    )
    changed = publication_identity(
        prepared.request.company_id,
        prepared.request.action_id,
        prepared.request_sha256,
        "code_patch",
        b"other bytes",
    )
    assert first[1].artifact_revision_id == changed[1].artifact_revision_id
    assert first[1].sha256 != changed[1].sha256  # replay must DENY, not allocate a new identity.


async def test_published_brain_bytes_must_use_the_actual_artifact_readers_store(
    tmp_path: Path,
) -> None:
    from nexus.company.brain.blob_store import ProtectedBlobStore
    from nexus.company.management.coding_publication_store import CodingPublicationStore

    value = await graph(tmp_path)
    with pytest.raises(ValueError):
        CodingPublicationStore(
            value.private.factory,
            value.catalog,
            value.private,
            value.model,
            ProtectedBlobStore(
                tmp_path / "unreadable-by-artifacts", storage_symbol="other-brain-root"
            ),
            value.publisher.repository,
            rules=value.rules,
        )


async def test_actual_saved_model_output_and_exact_git_bytes_form_truthful_raw_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.management.coding_publication_rows import model_origin, prepare_pair

    value = await native_files(tmp_path, monkeypatch)
    record = await value.model.load_record(value.artifact)
    origin = model_origin(
        value.loaded, value.native, record.evidence, value.catalog.models, wire=record.wire
    )
    pair = prepare_pair(
        origin,
        value.rules,
        value.publisher.blobs.storage_symbol,
        origin.checked_at,
        tuple(row.artifact for row in value.prepared.sources),
    )
    assert pair.patch.artifact.raw_text == origin.content.patch
    assert pair.origin.derivation is not None and pair.patch.derivation is not None
    assert (
        pair.origin.derivation.kind == "model_origin" and pair.patch.derivation.kind == "code_patch"
    )
    assert pair.patch.derivation.contributors == (pair.value.origin.source,)
    assert pair.patch.source.source_event.value == value.saved.checked_at.isoformat()
    raw = pair.origin.artifact.raw_text
    assert value.prepared.request.input_text not in raw
    assert all(
        '"' + field + '":' not in raw for field in ("input_text", "system_text", "reference")
    )
    assert origin.changed_files[0].sha256 != value.prepared.binding.source_files[0].sha256


@pytest.mark.parametrize("fault", ["native_failed", "unknown", "invalid_patch", "foreign_evidence"])
async def test_known_or_uncertain_native_money_never_becomes_publication_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    import json

    from nexus.company.management.coding_publication_rows import model_origin
    from nexus.harness.model_evidence import FileModelEvidenceStore

    value = await native_files(tmp_path, monkeypatch)
    native, saved = value.native, value.saved
    record = await value.model.load_record(value.artifact)
    original_money = native.hold.actual_usd
    if fault == "native_failed":
        native = native.model_copy(
            update={
                "intent": native.intent.model_copy(
                    update={
                        "state": "failed",
                        "receipt": native.intent.receipt.model_copy(update={"outcome": "failed"}),
                    }
                )
            }
        )
    elif fault == "unknown":
        native = native.model_copy(
            update={
                "intent": native.intent.model_copy(
                    update={"state": "outcome_unknown", "receipt": None}
                ),
                "hold": native.hold.model_copy(update={"state": "unknown", "actual_usd": None}),
            }
        )
    else:
        content = json.loads(saved.result.structured_json)
        if fault == "invalid_patch":
            content["patch"] = "not a unified patch"
        else:
            content["evidence_ids"] = [str(UUID(int=995))]
        saved = saved.model_copy(
            update={
                "result": saved.result.model_copy(update={"structured_json": json.dumps(content)})
            }
        )
        # Another supplied already-issued outcome, not replacement of immutable old bytes.
        different = FileModelEvidenceStore(tmp_path / "different-outcome")
        artifact = await different.save(saved)
        record = await different.load_record(artifact)
        native = native.model_copy(
            update={
                "intent": native.intent.model_copy(
                    update={
                        "receipt": native.intent.receipt.model_copy(
                            update={"artifacts": (artifact,)}
                        )
                    }
                )
            }
        )
    with pytest.raises(ValueError):
        model_origin(value.loaded, native, saved, value.catalog.models, wire=record.wire)
    assert value.native.hold.actual_usd == original_money


async def test_concrete_original_factories_and_real_owner_witness_before_private_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.access import VerifiedIdentity
    from nexus.company.management.planning_native_facts import clock_us
    from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity

    value = await graph(tmp_path)
    private = AsyncMock(side_effect=AssertionError("no private byte before true owner witness"))
    monkeypatch.setattr(value.private, "load_owner", private)
    with pytest.raises(ValueError):
        await value.publisher.publish(
            value.scope,
            cast(
                AuthenticatedWorkerIdentity,
                VerifiedIdentity(
                    principal_id=value.scope.principal_id,
                    workspace_id=value.owner.identity.workspace_id,
                ),
            ),
            value.rules.action_id,
            "a" * 64,
            expected_goal=value.prepared.binding.goal,
            expected_current_revision_id=value.prepared.binding.plan.plan_revision_id,
            end_us=clock_us() + 30_000_000,
        )
    private.assert_not_awaited()


async def publish(value: SimpleNamespace) -> CodingPublicationRead:
    from nexus.company.management.planning_native_facts import clock_us

    return cast(
        CodingPublicationRead,
        await value.publisher.publish(
            value.scope,
            value.owner,
            value.rules.action_id,
            value.native.action.proposal_hash,
            expected_goal=value.prepared.binding.goal,
            expected_current_revision_id=value.prepared.binding.plan.plan_revision_id,
            end_us=clock_us() + 20_000_000,
        ),
    )


async def test_atomic_actual_rows_real_blob_and_exact_replay_without_charge_or_head_renewal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.brain.artifact_input_models import BrainArtifactInput
    from nexus.company.brain.derivation_models import BrainDerivation
    from nexus.company.brain.source_models import (
        BrainArtifactRevision,
        BrainSourceHead,
        BrainSourceRevision,
    )
    from nexus.company.management.coding_content import CodeChangeContent

    value = await supplied_case(tmp_path, monkeypatch)
    result = await publish(value)
    first = result.value
    assert not value.memory.inside and not first.company_completed
    content = CodeChangeContent.model_validate_json(value.saved.result.structured_json)
    assert await value.publisher.blobs.read(first.patch.artifact) == content.patch.encode()
    assert len([row for row in value.memory.rows if isinstance(row, BrainDerivation)]) == 2
    assert len([row for row in value.memory.rows if isinstance(row, BrainSourceRevision)]) == 4
    assert len([row for row in value.memory.rows if isinstance(row, BrainArtifactRevision)]) == 4
    assert {row.kind for row in value.memory.rows if isinstance(row, BrainDerivation)} == {
        "model_origin",
        "code_patch",
    }
    edges = [row for row in value.memory.rows if isinstance(row, BrainArtifactInput)]
    assert {
        row.input_artifact_revision_id
        for row in edges
        if row.artifact_revision_id == first.origin.artifact.artifact_revision_id
    } == {row.artifact.artifact_revision_id for row in value.prepared.sources}
    assert {
        row.input_artifact_revision_id
        for row in edges
        if row.artifact_revision_id == first.patch.artifact.artifact_revision_id
    } == {first.origin.artifact.artifact_revision_id}
    clocks = [
        (row.source_id, row.generation, row.observed_at)
        for row in value.memory.rows
        if isinstance(row, BrainSourceHead)
    ]
    second = await publish(value)
    assert second.value == first
    assert clocks == [
        (row.source_id, row.generation, row.observed_at)
        for row in value.memory.rows
        if isinstance(row, BrainSourceHead)
    ]
    assert value.native.directory.work.counters.model_requests == 1
    assert not value.publisher.pending_owners()


async def test_crossed_native_receipt_denies_before_model_private_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await supplied_case(tmp_path, monkeypatch)
    value.native = value.native.model_copy(
        update={
            "intent": value.native.intent.model_copy(
                update={
                    "receipt": value.native.intent.receipt.model_copy(
                        update={"receipt_id": UUID(int=999)}
                    )
                }
            )
        }
    )
    private = AsyncMock(side_effect=AssertionError("crossed receipt reached private model record"))
    monkeypatch.setattr(value.model, "load", private)
    with pytest.raises(ValueError):
        await publish(value)
    private.assert_not_awaited()


@pytest.mark.parametrize("when", ["before_private", "after_private"])
async def test_current_recipient_read_revoke_never_restores_grants_or_publishes_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    when: str,
) -> None:
    from nexus.company.brain.access_models import BrainResourceAccess
    from nexus.company.brain.derivation_models import BrainDerivation

    value = await supplied_case(tmp_path, monkeypatch)
    native_before = value.native.model_dump_json()
    resource = value.prepared.context.manifest.contributors[0].resource_id
    grant = next(
        row
        for row in value.memory.rows
        if isinstance(row, BrainResourceAccess) and row.resource_id == resource
    )
    original = value.model.load

    async def read(reference: object) -> object:
        assert not value.memory.inside
        result = await original(reference)
        grant.active = False
        return result

    if when == "before_private":
        grant.active = False
    else:
        monkeypatch.setattr(value.model, "load", read)
    with pytest.raises(ValueError):
        await publish(value)
    assert not any(isinstance(row, BrainDerivation) for row in value.memory.rows)
    assert any(
        isinstance(row, BrainResourceAccess) and row.resource_id == resource and not row.active
        for row in value.memory.rows
    )
    assert value.native.model_dump_json() == native_before


async def test_cancelled_actual_private_read_remains_owned_without_late_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from nexus.company.brain.derivation_models import BrainDerivation

    value = await supplied_case(tmp_path, monkeypatch)
    entered, finish = asyncio.Event(), asyncio.Event()
    original = value.model.load

    async def read(reference: object) -> object:
        entered.set()
        await finish.wait()
        return await original(reference)

    monkeypatch.setattr(value.model, "load", read)
    caller = asyncio.create_task(publish(value))
    await asyncio.wait_for(entered.wait(), 3)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError) as caught:
        await caller
    assert value.publisher._first_error is caught.value
    owners = value.publisher.pending_owners()
    assert owners and not all(row.done() for row in owners)
    finish.set()
    await asyncio.gather(*owners)
    assert not value.publisher.pending_owners() and caller.cancelled()
    assert value.private._stopped and value.publisher.repository._stopped
    assert not any(isinstance(row, BrainDerivation) for row in value.memory.rows)


async def test_known_native_charge_is_not_a_private_directory_permission_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await supplied_case(tmp_path, monkeypatch)
    value.model._root.chmod(0o755)
    private = AsyncMock(side_effect=AssertionError("unsafe model directory was read"))
    monkeypatch.setattr(value.model, "load", private)
    try:
        with pytest.raises(ValueError):
            await publish(value)
        private.assert_not_awaited()
    finally:
        value.model._root.chmod(0o700)


async def test_original_first_recipient_expiry_cannot_be_renewed_by_refresh_during_private_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from datetime import UTC, datetime, timedelta

    from nexus.company.brain.access_models import BrainResourceAccess
    from nexus.company.brain.derivation_models import BrainDerivation

    value = await supplied_case(tmp_path, monkeypatch)
    resource = value.prepared.context.manifest.contributors[0].resource_id
    grant = next(
        row
        for row in value.memory.rows
        if isinstance(row, BrainResourceAccess) and row.resource_id == resource
    )
    grant.expires_at = datetime.now(UTC) + timedelta(seconds=3)
    entered, finish = asyncio.Event(), asyncio.Event()
    original = value.model.load

    async def read(reference: object) -> object:
        entered.set()
        await finish.wait()
        grant.expires_at = datetime.now(UTC) + timedelta(seconds=60)
        return await original(reference)

    monkeypatch.setattr(value.model, "load", read)
    caller = asyncio.create_task(publish(value))
    await asyncio.wait_for(entered.wait(), 5)
    with pytest.raises(TimeoutError):
        await caller
    owners = value.publisher.pending_owners()
    assert owners
    finish.set()
    await asyncio.gather(*owners, return_exceptions=True)
    assert not value.publisher.pending_owners()
    assert not any(isinstance(row, BrainDerivation) for row in value.memory.rows)


async def test_original_end_after_actual_last_pair_flush_retains_sql_owner_until_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from nexus.company.brain.artifact_input_models import BrainArtifactInput
    from nexus.company.brain.derivation_models import BrainDerivation
    from nexus.company.management.planning_native_facts import clock_us

    value = await supplied_case(tmp_path, monkeypatch)
    _, patch, _ = publication_identity(
        value.scope.company_id,
        value.rules.action_id,
        value.prepared.request_sha256,
        "code_patch",
        b"metadata only",
    )
    delayed = False
    original_end = clock_us() + 3_000_000

    async def flush() -> None:
        nonlocal delayed
        if not delayed and any(
            isinstance(row, BrainArtifactInput)
            and row.artifact_revision_id == patch.artifact_revision_id
            for row in value.memory.rows
        ):
            delayed = True
            await asyncio.sleep(max(0, original_end - clock_us()) / 1_000_000 + 0.1)

    value.memory.session.flush.side_effect = flush
    with pytest.raises(TimeoutError) as caught:
        await value.publisher.publish(
            value.scope,
            value.owner,
            value.rules.action_id,
            value.native.action.proposal_hash,
            expected_goal=value.prepared.binding.goal,
            expected_current_revision_id=value.prepared.binding.plan.plan_revision_id,
            end_us=original_end,
        )
    owners = value.publisher.pending_owners()
    assert delayed and owners and value.publisher._first_error is caught.value
    await asyncio.gather(*owners, return_exceptions=True)
    assert not value.publisher.pending_owners() and not value.memory.inside
    assert not any(isinstance(row, BrainDerivation) for row in value.memory.rows)


async def test_incomplete_retained_publication_is_not_repaired_or_relabelled_by_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.brain.source_models import BrainSourceRevision

    value = await supplied_case(tmp_path, monkeypatch)
    result = await publish(value)
    key = result.value.patch.source.source_revision_id
    value.memory.rows[:] = [
        row
        for row in value.memory.rows
        if not (isinstance(row, BrainSourceRevision) and row.source_revision_id == key)
    ]
    with pytest.raises(ValueError):
        await publish(value)
    assert not any(
        isinstance(row, BrainSourceRevision) and row.source_revision_id == key
        for row in value.memory.rows
    )
