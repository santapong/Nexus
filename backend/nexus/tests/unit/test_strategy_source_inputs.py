"""Current source boundaries and final-clock denial; mocked SQL is not PostgreSQL qualification."""

from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.notifications.worker_identity import WorkerIdentityDeniedError
from nexus.company.strategy import source_inputs as module
from nexus.tests.unit.strategy_source_inputs_fixture import SourceCase, source_case


async def _read(case: SourceCase) -> module.StrategySourceProtection:
    return await case.service.revalidate_locked(
        case.session,
        case.control,
        case.scope,
        case.credential.identity,
        case.original,
        credential=case.credential,
    )


async def test_original_snapshot_is_preserved_and_current_windows_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = source_case(monkeypatch)
    original = case.original.model_dump_json()
    result = await _read(case)
    assert case.original.model_dump_json() == original
    assert result.credential is case.credential and result.grants == (case.grant,)
    assert result.freshness[0].source_id == case.original.sources[0].head.source_id


@pytest.mark.parametrize("kind", ["grant", "source", "credential"])
async def test_deadline_crossed_during_last_await_denies(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    case = source_case(monkeypatch)
    deadline = (
        case.grant.expires_at
        if kind == "grant"
        else case.original.sources[0].head.fresh_until
        if kind == "source"
        else case.credential.expires_at
    )
    assert deadline is not None

    async def grants(*_: object) -> tuple[ResourceGeneration, ...]:
        case.clock["now"] = deadline
        return (
            (case.grant.model_copy(update={"expires_at": None}),)
            if kind != "grant"
            else (case.grant,)
        )

    monkeypatch.setattr(module, "require_resources", grants)
    with pytest.raises((AcceptanceDeniedError, WorkerIdentityDeniedError)):
        await _read(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("external_key", "foreign"),
        ("authority_profile", "foreign"),
        ("data_classification", "public"),
        ("source_symbol", "foreign"),
    ],
)
async def test_registered_source_policy_mismatch_denies(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    case = source_case(monkeypatch)
    setattr(case.native, field, value)
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)


async def test_original_quote_bytes_cannot_be_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    case = source_case(monkeypatch)
    source = case.original.sources[0].model_copy(update={"raw_text": "changed"})
    case.original = case.original.model_copy(update={"sources": (source,)})
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)


async def test_missing_manifest_evidence_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    case = source_case(monkeypatch)
    inputs = case.original.inputs.model_copy(update={"evidence": ()})
    case.original = case.original.model_copy(update={"inputs": inputs})
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)


@pytest.mark.parametrize("omitted", ["artifact", "source"])
async def test_other_source_manifest_cannot_hide_cited_source_before_read(
    monkeypatch: pytest.MonkeyPatch, omitted: str
) -> None:
    case = source_case(monkeypatch)
    cited = case.original.sources[0]
    second_ref = cited.evidence.source.model_copy(
        update={"source_id": UUID(int=900), "source_revision_id": UUID(int=901)}
    )
    second_artifact = cited.evidence.artifact.model_copy(
        update={"artifact_id": UUID(int=902), "artifact_revision_id": UUID(int=903)}
    )
    second_head = cited.head.model_copy(
        update={"source_id": second_ref.source_id, "current": second_ref}
    )
    inputs = case.original.inputs.model_copy(
        update={
            "artifacts": (second_artifact,)
            if omitted == "artifact"
            else case.original.inputs.artifacts,
            "contributors": (second_ref,)
            if omitted == "source"
            else case.original.inputs.contributors,
        }
    )
    case.original = case.original.model_copy(update={"inputs": inputs})

    async def current_heads(*args: object) -> tuple[object, ...]:
        refs = args[2]
        return (second_head,) if refs == (second_ref,) else (cited.head,)

    monkeypatch.setattr(module, "heads", current_heads)
    monkeypatch.setattr(module, "native_manifest", AsyncMock(return_value=(inputs, "internal")))
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)
    module.bundles.assert_not_awaited()  # type: ignore[attr-defined]


async def test_incomplete_native_manifest_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    case = source_case(monkeypatch)
    incomplete = case.original.inputs.model_copy(update={"required_resource_ids": (UUID(int=999),)})
    monkeypatch.setattr(module, "native_manifest", AsyncMock(return_value=(incomplete, "internal")))
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)


async def test_changed_source_head_denies_without_rewriting_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = source_case(monkeypatch)
    original = case.original.model_dump_json()
    changed = case.original.sources[0].head.model_copy(update={"generation": 2})
    monkeypatch.setattr(module, "heads", AsyncMock(return_value=(changed,)))
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)
    assert case.original.model_dump_json() == original


async def test_future_original_observation_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    case = source_case(monkeypatch)
    case.original = case.original.model_copy(
        update={"observed_at": case.clock["now"] + timedelta(seconds=1)}
    )
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)


async def test_foreign_signed_identity_denies_before_source_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = source_case(monkeypatch)
    wrong = VerifiedIdentity(principal_id=UUID(int=999), workspace_id=case.scope.workspace_id)
    with pytest.raises(AcceptanceDeniedError):
        await case.service.revalidate_locked(
            case.session, case.control, case.scope, wrong, case.original, credential=case.credential
        )
    module.bundles.assert_not_awaited()  # type: ignore[attr-defined]


async def test_protected_reader_denial_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    case = source_case(monkeypatch)
    monkeypatch.setattr(
        case.service.artifacts,
        "revalidate_artifact_reference",
        AsyncMock(side_effect=PermissionError("fixture")),
    )
    with pytest.raises(PermissionError):
        await _read(case)
