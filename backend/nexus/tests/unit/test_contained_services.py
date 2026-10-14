"""Exact trusted composition is required; a copied full digest alone never executes."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.contained_evidence_types import ObservationDeadline
from nexus.builder.contained_intent_check import ContainedParentIntentCheck
from nexus.builder.contained_process import ProcessOwnershipUnresolvedError
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.policy import BuilderToolPolicy
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.contained_observer_fixture import parent
from nexus.tests.contained_process_fixture import Process
from nexus.tests.unit.test_contained_runtime_identity import configured


def test_full_implementation_pin_needs_exact_policy_and_scope_before_any_observation(
    tmp_path: Path,
) -> None:
    spec, policy = configured()
    services = ContainmentServices(
        parent().expectation, ContainmentEvidenceStore(tmp_path / "sidecars")
    )
    with pytest.raises(ValueError, match="method"):
        services.require_policy(spec, policy)
    policy = BuilderToolPolicy.model_validate(
        policy.model_dump()
        | {
            "full_execution_method_sha256": CONTAINED_EXECUTION_METHOD_SHA256,
        }
    )
    spec = spec.model_copy(update={"policy_sha256": canonical_sha256(policy)})
    # The synthetic source work is foreign to the generated trusted scope.
    with pytest.raises(ValueError, match="scope"):
        services.require_policy(spec, policy)


def test_foreign_method_or_nonconcrete_dependencies_deny_before_store_read(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ContainmentServices(parent().expectation, object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="method"):
        ContainmentServices(
            parent().expectation,
            ContainmentEvidenceStore(tmp_path / "sidecars"),
            method_sha256="0" * 64,
        )


async def test_unresolved_child_handle_stays_owned_after_exception_scope(tmp_path: Path) -> None:
    services = ContainmentServices(
        parent().expectation, ContainmentEvidenceStore(tmp_path / "sidecars")
    )
    child = Process(stopped=False)
    failure = ProcessOwnershipUnresolvedError(
        "unknown", process=cast(asyncio.subprocess.Process, child)
    )
    services.retain_unresolved(failure)
    del failure
    current = services.unresolved_runtime()
    assert services.unresolved is not None and services.unresolved.process is cast(
        asyncio.subprocess.Process, child
    )
    assert current is not None and current.pid == child.pid and current.reap == "unresolved"
    assert not child.killed and child.wait_count == 0


async def test_parent_intent_retains_fixed_end_through_final_native_clock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.builder.contained_intent_check as module

    expected = parent().expectation
    services = ContainmentServices(expected, ContainmentEvidenceStore(tmp_path / "sidecars"))
    services.deadline = ObservationDeadline(end_us=13_000_000)
    monkeypatch.setattr(services, "observe", AsyncMock(return_value=parent()))
    check = ContainedParentIntentCheck(services)
    work = MagicMock(
        company_id=expected.company_id,
        task_id=expected.task_id,
        trace_id=expected.trace_id,
        run_id=expected.run_id,
    )
    await check.validate(
        MagicMock(), MagicMock(), work, MagicMock(id=expected.action_id), datetime.now(UTC)
    )
    monkeypatch.setattr(module, "clock_us", lambda: 12_040_000)
    check.validate_time(datetime.now(UTC))
    monkeypatch.setattr(module, "clock_us", lambda: 13_000_000)
    with pytest.raises(ValueError, match="expired"):
        check.validate_time(datetime.now(UTC))
