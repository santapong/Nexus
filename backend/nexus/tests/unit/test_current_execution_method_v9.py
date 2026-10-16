"""Method/history boundaries using synthetic observations and real finite temp stores only."""

from pathlib import Path

import pytest

from nexus.builder import execution_method as methods
from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.contained_evidence_types import ContainedObservation
from nexus.builder.contained_results import require_contained_result, result_evidence_identity
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.verification_support import (
    require_containment_configuration,
    require_result_containment,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.contained_observer_fixture import parent
from nexus.tests.contained_sidecar_fixture import contained_result
from nexus.tests.unit.test_contained_runtime_identity import configured

V6 = "95f3098bda522d1a80eb44746c89aa2913f382cf5605c20fdd7295d33da641c7"
V7 = "083529a745f4827b10056e839d8f41dc9cfdd7eb8815e4947b26009927073161"
V8 = "90aa8a81de487509b88d251c953a7273aa07c27449235c72ce7adedc005aad28"
HISTORICAL = (V6, V7, V8)


def named_method(name: str) -> str:
    value = getattr(methods, name, None)
    assert isinstance(value, str), f"Required named method history is absent: {name}"
    assert len(value) == 64
    return value


def described_policy(method: str) -> tuple[BuilderExecutionSpec, BuilderToolPolicy]:
    """Match all supplied scope fields so only the full-method guard can deny."""
    spec, policy = configured()
    expected = parent().expectation
    policy = BuilderToolPolicy.model_validate_json(
        policy.model_copy(
            update={
                "company_id": expected.company_id,
                "full_execution_method_sha256": method,
            }
        ).model_dump_json()
    )
    job = spec.job.model_copy(
        update={
            field: getattr(expected, field)
            for field in ("company_id", "action_id", "task_id", "trace_id", "run_id")
        }
    )
    spec = BuilderExecutionSpec.model_validate_json(
        spec.model_copy(
            update={"job": job, "policy_sha256": canonical_sha256(policy)}
        ).model_dump_json()
    )
    return spec, policy


async def historical_result(root: Path) -> tuple[BuilderRunResult, ContainmentEvidenceStore]:
    """Synthetic V8 process description, persisted in the real private sidecar ABI.

    The source helper emits the current method. Rebinding its descriptive identity
    supplies historical test data only; neither form is an actual native run.
    """
    value, store = await contained_result(root)
    assert value.containment is not None
    observed = await store.load_exact(value.containment, value.containment.identity)
    historical = ContainedObservation.model_validate(
        observed.model_copy(update={"identity": result_evidence_identity(value, V8)}).model_dump()
    )
    ref = await store.save_once(historical)
    return BuilderRunResult.model_validate(
        value.model_copy(update={"containment": ref}).model_dump()
    ), store


def test_named_history_preserves_the_exact_v6_v7_v8_identities() -> None:
    assert methods.CONTAINED_EXECUTION_METHOD_V6_SHA256 == V6
    assert methods.CONTAINED_EXECUTION_METHOD_V7_SHA256 == V7
    assert named_method("CONTAINED_EXECUTION_METHOD_V8_SHA256") == V8


def test_current_v9_is_distinct_and_candidate_stays_unactivated() -> None:
    current = named_method("CONTAINED_EXECUTION_METHOD_V9_SHA256")
    assert current == methods.CONTAINED_EXECUTION_METHOD_SHA256
    assert current not in HISTORICAL
    assert methods.execution_method_candidate().execution_ready is False


@pytest.mark.parametrize("historical", HISTORICAL)
def test_old_method_cannot_construct_fresh_services(tmp_path: Path, historical: str) -> None:
    store = ContainmentEvidenceStore(tmp_path / "sidecars")
    with pytest.raises(ValueError, match="method"):
        ContainmentServices(parent().expectation, store, method_sha256=historical)
    assert not tuple(store.root.iterdir())


@pytest.mark.parametrize("historical", HISTORICAL)
def test_old_policy_cannot_pass_current_services(tmp_path: Path, historical: str) -> None:
    store = ContainmentEvidenceStore(tmp_path / "sidecars")
    services = ContainmentServices(parent().expectation, store)
    spec, policy = described_policy(historical)
    with pytest.raises(ValueError, match="method"):
        services.require_policy(spec, policy)
    assert not tuple(store.root.iterdir())


@pytest.mark.parametrize("historical", HISTORICAL)
def test_old_method_is_not_current_protected_configuration(tmp_path: Path, historical: str) -> None:
    store = ContainmentEvidenceStore(tmp_path / "sidecars")
    with pytest.raises(ValueError, match="configuration"):
        require_containment_configuration(store, historical)


async def test_original_v8_result_and_sidecar_remain_explicitly_readable(tmp_path: Path) -> None:
    value, store = await historical_result(tmp_path)
    results = BuilderResultStore(tmp_path / "results")
    await results.save(value)
    loaded = await results.load(value.spec)
    assert loaded == value and loaded is not None
    original = await require_contained_result(loaded, store, V8)
    assert original.identity.execution_method_sha256 == V8
    assert original.identity.original_intent_fence == value.intent_fence
    with pytest.raises(ValueError, match="configuration"):
        require_containment_configuration(store, V8)


async def test_current_protected_interpretation_cannot_relabel_v8_history(tmp_path: Path) -> None:
    value, store = await historical_result(tmp_path)
    require_containment_configuration(store, methods.CONTAINED_EXECUTION_METHOD_SHA256)
    with pytest.raises(ValueError, match="original issuance"):
        await require_result_containment(value, store, methods.CONTAINED_EXECUTION_METHOD_SHA256)


async def test_explicit_wrong_original_method_denies_actual_v8_sidecar(tmp_path: Path) -> None:
    value, store = await historical_result(tmp_path)
    with pytest.raises(ValueError, match="original issuance"):
        await require_contained_result(value, store, V7)


async def test_replacement_fence_cannot_read_as_original_v8_history(tmp_path: Path) -> None:
    value, store = await historical_result(tmp_path)
    changed = value.model_copy(update={"intent_fence": value.intent_fence + 1})
    with pytest.raises(ValueError, match="original result"):
        await require_contained_result(changed, store, V8)


async def test_historical_read_rereads_complete_original_bytes(tmp_path: Path) -> None:
    value, store = await historical_result(tmp_path)
    assert value.containment is not None
    await require_contained_result(value, store, V8)
    path = store.root / store.filename(value.containment.identity)
    path.write_bytes(b"{}")
    with pytest.raises(ValueError, match="actual sidecar bytes"):
        await require_contained_result(value, store, V8)
