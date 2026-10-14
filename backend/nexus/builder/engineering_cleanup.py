"""Fenced known engineering infrastructure cleanup never issues an effect or discloses output."""

import hashlib
import json
import re
from dataclasses import dataclass
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_cleanup import CleanupDeadline, CleanupIdentity
from nexus.builder.contained_query import clock_us
from nexus.builder.contained_results import require_contained_result
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.native_state import actual_action
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.process import owned_engine
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.runtime_identity import RUNTIME_V2
from nexus.builder.verification_support import actual_result_reference, require_summary_containment
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.execution.effect_support import effect_record
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)

INSPECT_FORMAT = (
    '{{.Id}} {{index .Config.Labels "nexus.builder.action"}} '
    '{{index .Config.Labels "nexus.builder.company"}} {{.State.Running}} {{.Image}}'
)


@dataclass(frozen=True)
class CapturedOwnedContainer:
    """Immutable exact stopped object capture; no caller name can select deletion afterward."""

    container_id: str
    action_id: str
    company_id: str
    image_id: str


async def inspect_owned_stopped(
    name: str, action_id: str, company_id: str, image_id: str
) -> CapturedOwnedContainer | None:
    """A bounded explicit inventory confirms absence; inspect errors never become absent."""
    if not re.fullmatch(r"nexus-builder-[0-9a-f]{32}", name):
        raise ValueError("Engineering container name unavailable")
    listing = await owned_engine(("ps", "--all", "--no-trunc", "--format", "{{.ID}} {{.Names}}"))
    selected = []
    for line in listing.decode("ascii").splitlines():
        fields = line.split()
        if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[0]):
            raise ValueError("Engineering container inventory unavailable")
        if fields[1] == name:
            selected.append(fields[0])
    if not selected:
        return None
    if len(selected) != 1:
        raise ValueError("Engineering owned container identity ambiguous")
    raw = await owned_engine(
        (
            "inspect",
            "--format",
            INSPECT_FORMAT,
            selected[0],
        )
    )
    fields = raw.decode("ascii").strip().split()
    if fields != [selected[0], action_id, company_id, "false", image_id]:
        raise ValueError("Engineering cleanup requires exact stopped owned container")
    return CapturedOwnedContainer(selected[0], action_id, company_id, image_id)


async def require_captured_stopped(captured: CapturedOwnedContainer) -> None:
    """Reinspect the immutable full ID before the caller's final native fence clock."""
    if not re.fullmatch(r"[0-9a-f]{64}", captured.container_id):
        raise ValueError("Engineering immutable container ID unavailable")
    raw = await owned_engine(
        (
            "inspect",
            "--format",
            INSPECT_FORMAT,
            captured.container_id,
        )
    )
    if raw.decode("ascii").strip().split() != [
        captured.container_id,
        captured.action_id,
        captured.company_id,
        "false",
        captured.image_id,
    ]:
        raise ValueError("Engineering stopped container capture changed")


async def remove_captured(captured: CapturedOwnedContainer) -> None:
    """Standalone infrastructure helper uses the captured ID, never a mutable name."""
    await require_captured_stopped(captured)
    await owned_engine(("rm", captured.container_id))


async def cleanup_known_engineering_container(
    factory: async_sessionmaker[AsyncSession],
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action: ActionProposal,
    spec: BuilderExecutionSpec,
    result: BuilderRunResult,
    expected_receipt: ActionReceipt,
    *,
    containment: ContainmentServices | None = None,
    policy: BuilderToolPolicy | None = None,
) -> None:
    """Known receipt and current fenced mode authorize only owned infrastructure cleanup."""
    # Keep this >50-line company-first transaction and final effect fence cohesive:
    # issued receipt/result, captured container ID and last clock must agree before rm.
    if result.outcome == "outcome_unknown" or result.spec != spec:
        raise ValueError("Engineering cleanup needs known reconciliation output")
    await actual_action(factory, lease, identity, action, spec)
    expected = "nexus-builder-" + uuid5(spec.job.company_id, str(action.action_id)).hex
    if result.container_name != expected:
        raise ValueError("Engineering saved container name differs")
    async with runtime_transaction(
        factory,
        lease_scope(lease),
        identity,
        allow_paused=lease.mode == "reconcile",
        allow_inactive=lease.mode == "reconcile",
    ) as (session, _, _):
        work = await execution_row(session, lease_scope(lease))
        require_lease(work, lease, await db_now(session))
        row = await session.get(EffectIntent, (lease.company_id, action.action_id))
        if row is None:
            raise ValueError("Engineering issued receipt unavailable")
        record = effect_record(row)
        reference = await actual_result_reference(session, result)
        await require_stored_result_summary(session, result, reference.artifact_revision_id)
        if (
            record.state != "succeeded"
            or record.receipt != expected_receipt
            or expected_receipt.receipt_id != uuid5(action.action_id, "native-builder-receipt-v1")
            or expected_receipt.recorded_at != result.recorded_at
            or len(expected_receipt.artifacts) != 1
            or (
                expected_receipt.artifacts[0].artifact_id,
                expected_receipt.artifacts[0].revision,
                expected_receipt.artifacts[0].sha256,
            )
            != (reference.artifact_id, reference.revision, reference.sha256)
        ):
            raise ValueError("Engineering cleanup receipt/result binding differs")
        if spec.runtime_recipe == RUNTIME_V2:
            if type(containment) is not ContainmentServices or policy is None:
                raise ValueError("Contained known cleanup is not configured")
            containment.require_policy(spec, policy)
            sidecar = await require_contained_result(
                result, containment.store, containment.method_sha256
            )
            original = sidecar.container
            anchor = clock_us()
            final = await db_now(session)
            require_lease(work, lease, final)
            delta = lease.expires_at - final
            remaining_us = (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
            deadline = CleanupDeadline(
                started_us=anchor, end_us=min(anchor + 5_000_000, anchor + remaining_us)
            )
            captured_v2 = await containment.cleanup.inspect_stopped(
                CleanupIdentity(
                    company_id=lease.company_id,
                    action_id=action.action_id,
                    container_name=original.container_name,
                    container_id=original.container_id,
                    image_id=original.image_id,
                ),
                deadline,
            )
            require_lease(work, lease, await db_now(session))
            if captured_v2.state == "stopped":
                await containment.cleanup.remove_stopped(captured_v2, deadline)
            return
        captured = await inspect_owned_stopped(
            expected, str(action.action_id), str(action.company_id), result.image_id
        )
        require_lease(work, lease, await db_now(session))
        if captured is not None:
            await require_captured_stopped(captured)
            require_lease(work, lease, await db_now(session))
            await owned_engine(("rm", captured.container_id))


async def require_stored_result_summary(
    session: AsyncSession,
    result: BuilderRunResult,
    artifact_revision_id: UUID,
) -> None:
    """Protected metadata bytes bind the complete saved result before cleanup."""
    artifact = await session.get(
        BrainArtifactRevision, (result.spec.job.company_id, artifact_revision_id)
    )
    if artifact is None or artifact.byte_length > 262144:
        raise ValueError("Engineering protected result summary unavailable")
    raw = artifact.raw_text.encode()
    if len(raw) != artifact.byte_length or hashlib.sha256(raw).hexdigest() != artifact.sha256:
        raise ValueError("Engineering protected result summary bytes differ")
    value = json.loads(raw)
    if (
        value.get("result_sha256"),
        value.get("spec"),
        value.get("proposal_sha256"),
        value.get("intent_fence"),
    ) != (
        BuilderResultStore.digest(result),
        result.spec.model_dump(mode="json"),
        result.proposal_sha256,
        result.intent_fence,
    ):
        raise ValueError("Engineering protected result summary binding differs")
    require_summary_containment(result, raw.decode())
