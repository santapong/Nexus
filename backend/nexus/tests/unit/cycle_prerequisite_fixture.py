"""Supplied-session delivery shapes only; no native acceptance or SQL qualification."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.cycle_artifacts.common import CycleKind, criteria_for
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import KINDS, registration_digest
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import JournalAction
from nexus.tests.engineering_check_support import check_input
from nexus.tests.unit import cycle_partition_fixture
from nexus.tests.unit.cycle_admission_fixture import Cycle, cycle, declared
from nexus.tests.unit.cycle_partition_fixture import Partition

if TYPE_CHECKING:
    from pathlib import Path

    from nexus.company.cycle_artifacts.engineering_prerequisite_reader import CycleEngineeringReader


# Historical supplied native facts only. Fresh leases and signed witnesses use
# their per-call actual clock, so test collection age cannot expire them early.
NOW = datetime.now(UTC)


def deliverable_case(monkeypatch: pytest.MonkeyPatch, index: int = 4) -> Partition:
    original = cycle()
    slots = list(original.admission.slots)
    for offset in range(4, 8):
        kind: CycleKind = "presentation" if offset < 6 else "support"
        work = slots[offset].work.model_copy(update={"acceptance": criteria_for(kind)})
        slots[offset] = slots[offset].model_copy(update={"work": work})
    admission = original.admission.model_copy(update={"slots": tuple(slots)})
    declared_case = Cycle(
        admission, original.registry, declared(admission, 1), declared(admission, 2)
    )
    monkeypatch.setattr(cycle_partition_fixture, "cycle", lambda: declared_case)
    result = cycle_partition_fixture.partition(monkeypatch)
    result.work = result.executions[index + 1]
    result.identity = VerifiedIdentity(
        principal_id=result.work.actor_id, workspace_id=result.work.workspace_id
    )
    from nexus.execution import cycle_partition_checks

    monkeypatch.setattr(
        cycle_partition_checks,
        "require_runtime_scope",
        AsyncMock(return_value=result.directories[index + 1]),
    )
    return result


def own_lease(case: Partition, *, now: datetime | None = None) -> ExecutionLease:
    """Describe the same finite lease using this case's actual creation clock."""
    now = datetime.now(UTC) if now is None else now
    work = case.work
    work.state, work.fence, work.segment_number = "running", 1, 1
    work.worker_id, work.segment_id = UUID(int=980), UUID(int=981)
    work.lease_principal_id, work.lease_mode = work.actor_id, "execute"
    work.lease_until = now + timedelta(seconds=60)
    return ExecutionLease(
        company_id=work.company_id,
        task_id=work.task_id,
        trace_id=work.trace_id,
        actor_id=work.actor_id,
        workspace_id=work.workspace_id,
        run_id=work.run_id,
        workflow_version=work.workflow_version,
        segment_id=work.segment_id,
        worker_id=work.worker_id,
        fence=work.fence,
        expires_at=work.lease_until,
        mode="execute",
    )


async def signed_identity(
    identity: VerifiedIdentity, *, now: datetime | None = None
) -> AuthenticatedWorkerIdentity:
    """Verify a genuine synthetic token at call time; its captured expiry never renews."""
    now = datetime.now(UTC) if now is None else now
    key = SecretStr("cycle-prerequisite-unit-only-signing-key-2026")
    token = SecretStr(
        jwt.encode(
            {
                "sub": str(identity.principal_id),
                "workspace_id": str(identity.workspace_id),
                "iat": int((now - timedelta(seconds=10)).timestamp()),
                "exp": int((now + timedelta(seconds=120)).timestamp()),
            },
            key.get_secret_value(),
            algorithm="HS256",
        )
    )

    class Provider:
        async def credential(self) -> SecretStr:
            return token

    return await NotificationWorkerIdentities(Provider(), key, enabled=True).current()


@dataclass
class IssuedCase:
    session: MagicMock
    work: ExecutionWork
    action: JournalAction
    effect: EffectIntent
    attempt: ExecutionAttempt
    receipt: ActionReceipt


def issued_case() -> IssuedCase:
    """Real serialized action/ORM shapes, mocked storage delivery; no acceptance is created."""
    value = check_input()
    spec, registration = value.author.spec, value.author_registration
    job = spec.job
    action = ActionProposal.model_validate(
        {
            "company_id": job.company_id,
            "action_id": job.action_id,
            "task_id": job.task_id,
            "trace_id": job.trace_id,
            "actor_id": job.actor_id,
            "revision": 1,
            "tool": "company.builder.run.v1",
            "tool_version": "v1",
            "resource": job.resource_symbol,
            "parameters": spec.model_dump(mode="json"),
            "policy_version": "p1",
            "price_version": "p1",
            "estimated_cost_usd": "0.01",
        }
    )
    work = ExecutionWork(
        company_id=job.company_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        run_id=job.run_id,
        actor_id=job.actor_id,
        workspace_id=job.workspace_id,
        registration_json=registration.model_dump_json(),
        registration_hash=registration_digest(registration),
        workflow_name=registration.workflow_name,
        workflow_version=registration.workflow_version,
        model_profile=registration.model_profile,
        model_registry_version=registration.model_registry_version,
        state="verifying",
        fence=2,
        segment_number=1,
        **{
            f"{kind}_{suffix}": getattr(registration.quota, kind)
            if suffix == "limit"
            else int(kind == "tool_attempts" and suffix == "used")
            for kind in KINDS
            for suffix in ("limit", "used", "delegated")
        },
    )
    receipt = value.author_receipt.model_copy(
        update={"proposal_hash": action_hash(action), "recorded_at": NOW - timedelta(seconds=1)}
    )
    row = JournalAction(
        id=job.action_id,
        company_id=job.company_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        proposal_hash=action_hash(action),
        proposal_json=action.model_dump_json(),
        state="authorized",
        consumed_at=NOW - timedelta(seconds=4),
    )
    effect = EffectIntent(
        company_id=job.company_id,
        action_id=job.action_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        run_id=job.run_id,
        proposal_hash=action_hash(action),
        intent_fence=1,
        attempt_kind="tool_attempts",
        state="succeeded",
        receipt_json=receipt.model_dump_json(),
        created_at=NOW - timedelta(seconds=2),
    )
    attempt = ExecutionAttempt(
        company_id=job.company_id,
        task_id=job.task_id,
        trace_id=job.trace_id,
        attempt_id=job.action_id,
        kind="tool_attempts",
        fence=1,
        reserved_at=NOW - timedelta(seconds=3),
    )
    rows: dict[tuple[type[object], object], object] = {
        (JournalAction, job.action_id): row,
        (EffectIntent, (job.company_id, job.action_id)): effect,
        (ExecutionAttempt, (job.company_id, job.task_id, job.action_id)): attempt,
    }

    async def get(model: type[object], key: object) -> object:
        return rows.get((model, key))

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(side_effect=get)
    session.scalar = AsyncMock(return_value=NOW)
    for name in ("add", "flush", "commit", "begin"):
        setattr(session, name, MagicMock(side_effect=AssertionError("read path attempted " + name)))
    return IssuedCase(session, work, row, effect, attempt, receipt)


def configured_reader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: "Path"
) -> "CycleEngineeringReader":
    """Concrete private IO configuration only; no engineering acceptance/read is supplied."""
    from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
    from nexus.builder.engineering_proof import EngineeringProofStorage
    from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
    from nexus.builder.result_store import BuilderResultStore
    from nexus.builder.source_guard import RegisteredBuilderSource
    from nexus.company.brain.blob_store import ProtectedBlobStore
    from nexus.company.cycle_artifacts.engineering_prerequisite_reader import CycleEngineeringReader
    from nexus.tests.unit.engineering_body_fixture import described_body
    from nexus.tests.unit.strategy_actor_proof_support import actor_case

    strategy = actor_case(monkeypatch).service.reader
    company = strategy.catalog.company_id
    blobs = ProtectedBlobStore(tmp_path / "blobs", storage_symbol="fixture.private")
    strategy.artifacts.blobs = strategy.blobs = blobs
    value = check_input().declaration
    declaration = value.model_copy(
        update={
            "company_id": company,
            "policy": value.policy.model_copy(update={"company_id": company}),
        }
    )
    source = RegisteredBuilderSource(
        tmp_path, described_body(b"source metadata", company=company).first.artifact
    )
    proof = EngineeringProofStorage(
        blobs,
        strategy.catalog.resources[0].resource,
        strategy.policies.policy("generated.strategy-check.v1"),
    )
    return CycleEngineeringReader(
        strategy.artifacts.factory,
        strategy.catalog,
        strategy.artifacts,
        strategy.freshness,
        BuilderResultStore(tmp_path / "results"),
        (declaration,),
        source,
        proof,
        strategy.policies.policy("generated.strategy.v1"),
        strategy,
        (proof.target.resource_id,),
        containment_store=ContainmentEvidenceStore(tmp_path / "sidecars"),
        execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256,
    )
