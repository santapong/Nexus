"""Real immutable sidecar bytes, with mocked already-qualified native/artifact boundaries."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.engineering_bodies import CompleteEngineeringBody
from nexus.builder.engineering_contracts import EngineeringChangeDeclaration
from nexus.builder.engineering_inputs import RegisteredEngineeringInputs
from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.builder.verification_support import actual_summary
from nexus.company.access import VerifiedIdentity
from nexus.tests.contained_sidecar_fixture import contained_result, publisher, source_witness
from nexus.tests.unit.engineering_body_fixture import (
    body_case,
    described_body,
    load_body,
    without_expiry,
)


def inputs(
    value: BuilderRunResult, store: ContainmentEvidenceStore | None
) -> RegisteredEngineeringInputs:
    """Mock only the prior permission/result lookup; the containment read uses the actual store."""
    results = MagicMock(spec=BuilderResultStore)
    results.load = AsyncMock(return_value=value)
    declaration = cast(EngineeringChangeDeclaration, SimpleNamespace(goal_id=UUID(int=1)))
    if store is None:
        return RegisteredEngineeringInputs(
            MagicMock(), MagicMock(), results, (declaration,), MagicMock()
        )
    return RegisteredEngineeringInputs(
        MagicMock(),
        MagicMock(),
        results,
        (declaration,),
        MagicMock(),
        containment_store=store,
        execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256 if store else None,
    )


def protected(value: BuilderRunResult, store: ContainmentEvidenceStore) -> CompleteEngineeringBody:
    """Synthetic protected boundary, preserving the real publisher's full summary bytes."""
    assert value.containment is not None
    payload = {
        "result_sha256": BuilderResultStore.digest(value),
        "spec": value.spec.model_dump(mode="json"),
        "proposal_sha256": value.proposal_sha256,
        "intent_fence": value.intent_fence,
        "containment": value.containment.model_dump(mode="json"),
        "engineering_source_witness": source_witness(value).model_dump(mode="json"),
    }
    return described_body(json.dumps(payload).encode(), company=value.spec.job.company_id)


async def test_engineering_result_rereads_actual_sidecar_and_denies_later_tampering(
    tmp_path: Path,
) -> None:
    value, store = await contained_result(tmp_path)
    loader, summary = inputs(value, store), protected(value, store)
    assert (await loader._result(value.spec, summary))[0] == value
    assert value.containment is not None
    (store.root / store.filename(value.containment.identity)).write_bytes(b"{}")
    with pytest.raises(ValueError, match="bytes"):
        await loader._result(value.spec, summary)


async def test_unconfigured_engineering_loader_denies_qualified_v2_metadata(tmp_path: Path) -> None:
    value, store = await contained_result(tmp_path)
    with pytest.raises(ValueError, match="unconfigured"):
        await inputs(value, None)._result(value.spec, protected(value, store))


async def test_complete_large_summary_is_not_rejected_as_a_partial_consumer(
    tmp_path: Path,
) -> None:
    value, store = await contained_result(tmp_path)
    summary = protected(value, store)
    body = described_body(b" " * 16384 + summary.raw, company=value.spec.job.company_id)
    assert body.first.has_more
    assert (await inputs(value, store)._result(value.spec, body))[0] == value


async def test_qualified_no_ttl_remains_no_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    case = body_case(monkeypatch)
    without_expiry(case)
    assert (await load_body(case)).freshness == case.body.freshness


@pytest.mark.parametrize("change", ["missing", "null", "hash", "fence", "method", "base"])
async def test_protected_summary_reference_cannot_be_substituted(
    tmp_path: Path, change: str
) -> None:
    value, store = await contained_result(tmp_path)
    summary = protected(value, store)
    payload = json.loads(summary.raw)
    if change == "missing":
        del payload["containment"]
    elif change == "null":
        payload["containment"] = None
    elif change == "hash":
        payload["containment"]["sha256"] = "0" * 64
    else:
        key = {
            "fence": "original_intent_fence",
            "method": "execution_method_sha256",
            "base": "result_base_sha256",
        }[change]
        payload["containment"]["identity"][key] = 99 if change == "fence" else "0" * 64
    changed = described_body(json.dumps(payload).encode(), company=value.spec.job.company_id)
    with pytest.raises(ValueError):
        await inputs(value, store)._result(value.spec, changed)


async def test_independent_summary_materialization_rereads_private_sidecar(tmp_path: Path) -> None:
    value, store = await contained_result(tmp_path)
    configured = publisher(
        containment_store=store, execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256
    )
    raw, reference = configured.payload(value).decode(), configured.reference(value)
    guard = MagicMock(spec=BuilderSourceGuard)
    guard.identity = VerifiedIdentity(
        principal_id=value.spec.job.actor_id, workspace_id=value.spec.job.workspace_id
    )
    guard.artifacts = MagicMock()
    guard.artifacts.bounded_artifact = AsyncMock(
        return_value=SimpleNamespace(
            artifact=reference,
            source_state="current",
            span=SimpleNamespace(start_byte=0),
            text=raw,
        )
    )
    await actual_summary(
        guard,
        value,
        reference,
        containment_store=store,
        execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256,
    )
    assert value.containment is not None
    (store.root / store.filename(value.containment.identity)).write_bytes(b"{}")
    with pytest.raises(ValueError, match="bytes"):
        await actual_summary(
            guard,
            value,
            reference,
            containment_store=store,
            execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256,
        )
