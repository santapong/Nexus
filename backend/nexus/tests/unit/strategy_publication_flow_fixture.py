"""Two-phase transaction markers and real clock witnesses; mocked SQL is not durable proof."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceGeneration, ResourceRef
from nexus.company.brain.artifact_input_support import ArtifactInputClosure
from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.strategy import bundle_store as module
from nexus.company.strategy.bundle_store import StrategyBundleStore
from nexus.company.strategy.contracts import StrategyCheckSnapshot
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.publication_contracts import PreparedStrategyPublication
from nexus.company.strategy.publication_identity import prepare_strategy_publication
from nexus.company.strategy.publication_protection import (
    StrategyPublicationProtection,
    StrategyReadProtection,
)
from nexus.company.strategy.source_inputs import StrategySourceProtection
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.strategy_producer_fixture import producer_case
from nexus.tests.unit.strategy_source_inputs_fixture import SourceCase, source_case


@dataclass
class PublicationFlow:
    source: SourceCase
    store: StrategyBundleStore
    reader: MagicMock
    session: MagicMock
    lease: ExecutionLease
    work: ExecutionWork
    prepared: PreparedStrategyPublication
    first: StrategyPublicationProtection
    second: StrategyPublicationProtection
    markers: list[str]
    writer: AsyncMock


def publication_flow(monkeypatch: pytest.MonkeyPatch) -> PublicationFlow:
    # This >50-line fixture retains registration, signed witness and both transaction phases.
    from nexus.company.strategy import publication_protection as protection_module

    source = source_case(monkeypatch)
    original, policy = producer_case()
    snapshot = source.original
    assert original.scope == snapshot.scope
    bound = snapshot.scope.author
    now = source.clock["now"]
    lease = ExecutionLease(
        company_id=snapshot.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        workflow_version=bound.workflow_version,
        segment_id=UUID(int=700),
        worker_id=UUID(int=701),
        fence=1,
        expires_at=now + timedelta(seconds=120),
        mode="execute",
    )
    registration = snapshot.author_registration
    work = ExecutionWork(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        workflow_name=bound.workflow_name,
        workflow_version=bound.workflow_version,
        model_profile=bound.model_profile,
        model_registry_version=bound.model_registry_version,
        registration_json=registration.model_dump_json(),
        registration_hash=registration_digest(registration),
        parent_task_id=None,
        state="running",
        fence=1,
        worker_id=lease.worker_id,
        lease_principal_id=bound.actor_id,
        lease_until=lease.expires_at,
        lease_mode="execute",
        segment_id=lease.segment_id,
        segment_number=1,
        waiting_action_id=None,
    )
    for kind in type(registration.quota).model_fields:
        setattr(work, f"{kind}_limit", getattr(registration.quota, kind))
        setattr(work, f"{kind}_used", 1 if kind == "tool_attempts" else 0)
        setattr(work, f"{kind}_delegated", 0)
    prepared = prepare_strategy_publication(
        snapshot,
        policy,
        UUID(int=501),
        ResourceRef(company_id=bound.company_id, resource_id=UUID(int=500)),
    )
    grant = ResourceGeneration(
        company_id=bound.company_id,
        resource_id=UUID(int=500),
        generation=1,
        expires_at=now + timedelta(seconds=10),
    )
    sources = StrategySourceProtection((source.grant,), (), source.credential)
    pair = SimpleNamespace(author_child=MagicMock(), verifier_child=MagicMock())
    read = StrategyReadProtection(sources, (grant,), pair, MagicMock())  # type: ignore[arg-type]
    refreshed = StrategyReadProtection(sources, (), pair, MagicMock())  # type: ignore[arg-type]
    approval = ApprovalDecision(
        company_id=bound.company_id,
        decision_id=UUID(int=702),
        action_id=prepared.action_id,
        action_revision=1,
        action_hash="a" * 64,
        approver_id=UUID(int=703),
        decision="approved",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(seconds=60),
    )
    first = StrategyPublicationProtection(read, lease, approval)
    second = StrategyPublicationProtection(refreshed, lease, approval)
    monkeypatch.setattr(protection_module, "validate_plan_profile", MagicMock())
    factory, blobs = MagicMock(), MagicMock()
    blobs.storage_symbol = "fixture"
    blobs.save = AsyncMock()
    reader = MagicMock(spec=StrategyInputReader)
    reader.artifacts = SimpleNamespace(factory=factory, blobs=blobs)
    reader.blobs = blobs
    reader.rules = SimpleNamespace(
        write=MagicMock(), bundle_policy=MagicMock(), brief_policy=MagicMock()
    )
    reader.revalidate_author_locked = AsyncMock(side_effect=[first, second])
    store = StrategyBundleStore(factory, blobs, reader)
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=None)
    session.scalar = AsyncMock(
        side_effect=lambda statement: False if "pg_roles" in str(statement) else None
    )
    session.flush = AsyncMock()
    markers: list[str] = []

    @asynccontextmanager
    async def transaction(
        *_: object,
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, MagicMock]]:
        markers.append("enter")
        try:
            yield session, source.control, MagicMock()
        except Exception:
            markers.append("rollback")
            raise
        else:
            markers.append("commit")

    async def clock(_: AsyncSession) -> datetime:
        return source.clock["now"]

    expected = (
        snapshot.inputs.artifacts[0].artifact_revision_id,
        prepared.compiled.original_bundle.artifact.artifact_revision_id,
        prepared.brief.artifact_revision_id,
    )
    monkeypatch.setattr(module, "runtime_transaction", transaction)
    monkeypatch.setattr(module, "db_now", clock)
    monkeypatch.setattr(module, "execution_row", AsyncMock(return_value=work))
    monkeypatch.setattr(
        module,
        "artifact_input_closure",
        AsyncMock(
            return_value=ArtifactInputClosure(
                artifact_revision_ids=expected, resource_ids=(), classifications=("internal",)
            )
        ),
    )
    writer = AsyncMock()
    monkeypatch.setattr(module, "write_strategy_publication_locked", writer)
    monkeypatch.setattr(module, "require_strategy_publication_replay_locked", AsyncMock())
    return PublicationFlow(
        source, store, reader, session, lease, work, prepared, first, second, markers, writer
    )


def author_lease(
    snapshot: StrategyCheckSnapshot, now: datetime
) -> tuple[ExecutionLease, ExecutionWork]:
    """Actual-shaped native S lease/registration for focused actor-state tests."""
    # This >50-line fixture retains one complete registration and matching lease/counter view.
    from nexus.execution.runtime_contracts import ExecutionLease
    from nexus.execution.runtime_models import ExecutionWork
    from nexus.execution.runtime_support import registration_digest

    bound, registration = snapshot.scope.author, snapshot.author_registration
    lease = ExecutionLease(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        workflow_version=bound.workflow_version,
        segment_id=UUID(int=900),
        worker_id=UUID(int=901),
        fence=1,
        expires_at=now + timedelta(seconds=60),
        mode="execute",
    )
    work = ExecutionWork(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        workspace_id=bound.workspace_id,
        run_id=bound.run_id,
        workflow_name=bound.workflow_name,
        workflow_version=bound.workflow_version,
        model_profile=bound.model_profile,
        model_registry_version=bound.model_registry_version,
        registration_json=registration.model_dump_json(),
        registration_hash=registration_digest(registration),
        parent_task_id=None,
        state="verifying",
        fence=1,
        worker_id=lease.worker_id,
        lease_principal_id=bound.actor_id,
        lease_until=lease.expires_at,
        lease_mode="execute",
        segment_id=lease.segment_id,
        segment_number=1,
        waiting_action_id=None,
    )
    for kind in type(registration.quota).model_fields:
        setattr(work, f"{kind}_limit", getattr(registration.quota, kind))
        setattr(work, f"{kind}_used", 1 if kind == "tool_attempts" else 0)
        setattr(work, f"{kind}_delegated", 0)
    return lease, work
