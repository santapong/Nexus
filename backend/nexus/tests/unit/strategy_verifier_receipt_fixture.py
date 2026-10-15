"""Native-row mock fixture with an actually verified synthetic token; no SQL qualification."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid5

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity, _verify
from nexus.company.strategy import verifier_receipt as module
from nexus.company.strategy.artifact_contracts import StrategyArtifactRule, StrategyCheckParameters
from nexus.company.strategy.artifact_identity import strategy_artifact_id, strategy_derivation_id
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionLease, ExecutionRegistration
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.tests.unit.strategy_brief_fixture import strategy_case


@dataclass
class ReceiptCase:
    session: MagicMock
    control: CompanyControl
    lease: ExecutionLease
    credential: AuthenticatedWorkerIdentity
    target: VerificationSpec
    action: ActionProposal
    journal: JournalAction
    effect: EffectIntent
    attempt: ExecutionAttempt
    receipt: ActionReceipt
    artifact: BrainArtifactRevision
    reference: ArtifactRevisionRef
    rule: StrategyArtifactRule
    work: ExecutionWork
    clock: dict[str, datetime]


def _lease(target: VerificationSpec, now: datetime) -> ExecutionLease:
    actor = target.verifier
    return ExecutionLease(
        company_id=target.company_id,
        task_id=actor.task_id,
        trace_id=actor.trace_id,
        actor_id=actor.actor_id,
        workspace_id=actor.workspace_id,
        run_id=actor.run_id,
        workflow_version="v1",
        segment_id=UUID(int=301),
        worker_id=UUID(int=302),
        fence=3,
        expires_at=now + timedelta(seconds=60),
        mode="execute",
    )


def _work(target: VerificationSpec, lease: ExecutionLease) -> ExecutionWork:
    original = strategy_case().command.snapshot
    assert original is not None
    author = target.verifier
    work = original.author_registration.work.model_copy(
        update={"task_id": author.task_id, "trace_id": author.trace_id}
    )
    registration = ExecutionRegistration(
        work=work,
        run_id=author.run_id,
        workflow_name=author.workflow_name,
        workflow_version="v1",
        model_profile=author.model_profile,
        model_registry_version=author.model_registry_version,
        quota=AttemptQuota(model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0),
    )
    return ExecutionWork(
        company_id=target.company_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        actor_id=lease.actor_id,
        workspace_id=lease.workspace_id,
        run_id=lease.run_id,
        registration_json=registration.model_dump_json(),
        registration_hash=registration_digest(registration),
        workflow_name=author.workflow_name,
        workflow_version="v1",
        model_profile=author.model_profile,
        model_registry_version=author.model_registry_version,
        state="verifying",
        fence=lease.fence,
        segment_id=lease.segment_id,
        worker_id=lease.worker_id,
        lease_principal_id=lease.actor_id,
        lease_mode=lease.mode,
        lease_until=lease.expires_at,
        segment_number=1,
        model_requests_used=0,
        model_requests_delegated=0,
        tool_attempts_used=1,
        tool_attempts_delegated=0,
        rework_rounds_used=0,
        rework_rounds_delegated=0,
        plan_revisions_used=0,
        plan_revisions_delegated=0,
    )


def receipt_case(monkeypatch: pytest.MonkeyPatch) -> ReceiptCase:
    # This >50-line mock fixture keeps journal, intent, receipt and exact artifact pins cohesive.
    target = strategy_case().command.target
    now = datetime.now(UTC)
    lease = _lease(target, now)
    key = SecretStr("strategy-verifier-public-fixture-signing-key-with-at-least-64-characters")
    token = jwt.encode(
        {
            "sub": str(lease.actor_id),
            "workspace_id": str(lease.workspace_id),
            "iat": int(now.timestamp()) - 1,
            "exp": int(now.timestamp()) + 300,
        },
        key.get_secret_value(),
        algorithm="HS256",
    )
    credential = _verify(SecretStr(token), key)
    raw = b'{"fixture":"only receipt binding, not mechanical pass"}'
    parameters = StrategyCheckParameters(
        author_action_id=target.action_id,
        verification_target_sha256=canonical_sha256(target),
        output_sha256=hashlib.sha256(raw).hexdigest(),
        input_snapshot_sha256="a" * 64,
    )
    action = ActionProposal(
        company_id=target.company_id,
        action_id=UUID(int=310),
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        actor_id=lease.actor_id,
        revision=1,
        tool="company.cycle-artifact.check.v1",
        tool_version="v1",
        resource="strategy.check",
        parameters=parameters.model_dump(mode="json"),
        policy_version="fixture-v1",
        price_version="fixture-v1",
        estimated_cost_usd=Decimal(".01"),
    )
    artifact_id = strategy_artifact_id(lease.company_id, action.action_id)
    reference = ArtifactRevisionRef(
        company_id=lease.company_id,
        artifact_id=artifact_id,
        artifact_revision_id=uuid5(artifact_id, "revision:v1"),
        revision="strategy-v1",
        sha256=parameters.output_sha256,
        byte_length=len(raw),
    )
    artifact = BrainArtifactRevision(
        company_id=lease.company_id,
        artifact_id=reference.artifact_id,
        artifact_revision_id=reference.artifact_revision_id,
        revision=reference.revision,
        sha256=reference.sha256,
        byte_length=reference.byte_length,
        raw_text=raw.decode(),
        resource_id=UUID(int=311),
        derivation_id=strategy_derivation_id(lease.company_id, action.action_id),
        media_type="application/json",
        data_classification="internal",
        recorded_at=now,
    )
    receipt = ActionReceipt(
        company_id=lease.company_id,
        receipt_id=UUID(int=312),
        action_id=action.action_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        proposal_hash=action_hash(action),
        outcome="succeeded",
        recorded_at=now,
        artifacts=(
            ArtifactRef(
                company_id=lease.company_id,
                artifact_id=reference.artifact_id,
                reference="protected fixture",
                revision=reference.revision,
                sha256=reference.sha256,
            ),
        ),
    )
    journal = JournalAction(
        id=action.action_id,
        company_id=lease.company_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        proposal_hash=action_hash(action),
        proposal_json=action.model_dump_json(),
        state="authorized",
        consumed_at=now,
    )
    effect = EffectIntent(
        company_id=lease.company_id,
        action_id=action.action_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        run_id=lease.run_id,
        proposal_hash=action_hash(action),
        intent_fence=1,
        attempt_kind="tool_attempts",
        state="succeeded",
        created_at=now,
        receipt_json=receipt.model_dump_json(),
    )
    attempt = ExecutionAttempt(
        company_id=lease.company_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        attempt_id=action.action_id,
        kind="tool_attempts",
        fence=effect.intent_fence,
        reserved_at=now,
    )
    rule = StrategyArtifactRule(
        company_id=lease.company_id,
        tool="company.cycle-artifact.check.v1",
        resource_symbol=action.resource,
        target=ResourceRef(company_id=lease.company_id, resource_id=artifact.resource_id),
        source_policy="generated.strategy-check.v1",
    )
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True

    async def get(model: object, _: object) -> object:
        return (
            journal
            if model is JournalAction
            else effect
            if model is EffectIntent
            else artifact
            if model is BrainArtifactRevision
            else attempt
            if model is ExecutionAttempt
            else None
        )

    session.get = AsyncMock(side_effect=get)
    work = _work(target, lease)
    clock = {"now": now}

    async def current(_: AsyncSession) -> datetime:
        return clock["now"]

    monkeypatch.setattr(module, "db_now", current)
    monkeypatch.setattr(module, "execution_row", AsyncMock(return_value=work))
    return ReceiptCase(
        session,
        CompanyControl(company_id=lease.company_id, owner_id=UUID(int=3)),
        lease,
        credential,
        target,
        action,
        journal,
        effect,
        attempt,
        receipt,
        artifact,
        reference,
        rule,
        work,
        clock,
    )
