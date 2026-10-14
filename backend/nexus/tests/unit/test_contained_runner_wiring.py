"""Shared runner wiring preserves one native path and denies unconfigured v2 before stores."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runner import NativeBuilderRunner
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.builder_support import described_binding
from nexus.tests.contained_observer_fixture import parent
from nexus.tests.unit.test_contained_runtime_identity import configured


async def test_v2_missing_services_denies_before_native_metadata_prepare_or_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.builder.runner as module

    spec, policy = configured()
    action, lease, _ = described_binding(spec.job)
    identity = VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id)
    guard = cast(
        BuilderSourceGuard,
        SimpleNamespace(spec=spec, policy=policy, identity=identity, lease=lease, containment=None),
    )
    runner = NativeBuilderRunner.__new__(NativeBuilderRunner)
    runner.policy, runner.publisher, runner.containment = policy, None, None
    actual = AsyncMock()
    monkeypatch.setattr(module, "actual_action", actual)
    with pytest.raises(ValueError, match="not configured"):
        await runner.run(lease, identity, action, spec, guard)
    actual.assert_not_awaited()


def test_runner_has_one_closed_policy_entry_for_durable_dispatch() -> None:
    runner = NativeBuilderRunner.__new__(NativeBuilderRunner)
    spec, runner.policy = configured()
    runner.containment = None
    with pytest.raises(ValueError, match="not configured"):
        runner.require_execution_policy(spec)


def test_generic_runner_rejects_missing_node_configuration_before_native_admission(
    tmp_path: Path,
) -> None:
    from nexus.builder.runtime_identity import RUNTIME_V2, RUNTIME_V2_METHOD_SHA256
    from nexus.tests.node_v4_support import described_v4_check

    item = described_v4_check()
    expected = parent().expectation
    policy = item.declaration.policy.model_copy(
        update={
            "company_id": expected.company_id,
            "runtime_recipe": RUNTIME_V2,
            "runtime_method_sha256": RUNTIME_V2_METHOD_SHA256,
            "full_execution_method_sha256": CONTAINED_EXECUTION_METHOD_SHA256,
        }
    )
    job = item.author.spec.job.model_copy(
        update={
            "company_id": expected.company_id,
            "action_id": expected.action_id,
            "task_id": expected.task_id,
            "trace_id": expected.trace_id,
            "run_id": expected.run_id,
        }
    )
    spec = item.author.spec.model_copy(
        update={"job": job, "runtime_recipe": RUNTIME_V2, "policy_sha256": canonical_sha256(policy)}
    )
    runner = NativeBuilderRunner.__new__(NativeBuilderRunner)
    runner.policy = policy
    runner.containment = ContainmentServices(
        expected, ContainmentEvidenceStore(tmp_path / "sidecars")
    )
    with pytest.raises(ValueError, match="configured runner"):
        runner.require_execution_policy(spec)


async def test_current_parent_precedes_prepare_and_actual_intent_receives_composite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep this >50-line exact configured job and ordered native-composition probe
    # together so the same policy/scope reaches the one nominated intent boundary.
    import nexus.builder.runner as module
    from nexus.execution.intent_checks import CompositeBeforeIntentCheck

    spec, policy = configured()
    expected = parent().expectation
    job = spec.job.model_copy(
        update={
            "company_id": expected.company_id,
            "action_id": expected.action_id,
            "task_id": expected.task_id,
            "trace_id": expected.trace_id,
            "run_id": expected.run_id,
        }
    )
    policy = BuilderToolPolicy.model_validate(
        policy.model_dump()
        | {
            "company_id": expected.company_id,
            "full_execution_method_sha256": CONTAINED_EXECUTION_METHOD_SHA256,
        }
    )
    spec = spec.model_copy(update={"job": job, "policy_sha256": canonical_sha256(policy)})
    action, lease, _ = described_binding(job)
    identity = VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id)
    services = ContainmentServices(expected, ContainmentEvidenceStore(tmp_path / "sidecars"))
    guard = cast(
        BuilderSourceGuard,
        SimpleNamespace(
            spec=spec, policy=policy, identity=identity, lease=lease, containment=services
        ),
    )
    runner = NativeBuilderRunner.__new__(NativeBuilderRunner)
    runner.policy, runner.publisher, runner.containment = (
        policy,
        MagicMock(
            target=None,
            containment_store=services.store,
            execution_method_sha256=services.method_sha256,
        ),
        services,
    )
    runner.factory, runner.capabilities = MagicMock(), MagicMock()
    runner.results = MagicMock()
    runner.results.slot.return_value = nullcontext()
    order: list[str] = []
    monkeypatch.setattr(module, "actual_action", AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(module, "require_preparation", lambda *args: None)
    monkeypatch.setattr(
        module, "current_source", AsyncMock(side_effect=lambda *a, **k: order.append("source"))
    )
    monkeypatch.setattr(
        services, "before_prepare", AsyncMock(side_effect=lambda *a: order.append("parent"))
    )
    monkeypatch.setattr(
        runner, "prepare", AsyncMock(side_effect=lambda *a: order.append("prepare"))
    )

    async def begin(*args: object, **kwargs: object) -> SimpleNamespace:
        order.append("intent")
        assert isinstance(kwargs["before_intent"], CompositeBeforeIntentCheck)
        raise ValueError("stop before native mutation")

    runner.effects = MagicMock()
    runner.effects.begin = begin
    with pytest.raises(ValueError, match="stop before"):
        await runner.run(lease, identity, action, spec, guard)
    assert order == ["parent", "source", "prepare", "intent"]
