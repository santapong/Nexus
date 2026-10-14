"""DB-only full rederivation at the exact pending-action boundary."""

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.management.acceptance_support import resolve_target
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactPayload,
)
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


async def recompute_pending(
    producer: NativeReportProducer,
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    lease: ExecutionLease | None,
    pins: GeneratedArtifactActionParameters,
    prepared: GeneratedArtifactPayload,
    phase: Literal["author", "verifier"],
) -> GeneratedArtifactPayload:
    """Recompute full native bytes/inputs, never echo caller-supplied hash assertions."""
    if phase == "author":
        return await producer.recompute_report(
            session, control, scope, identity, prepared.raw_bytes
        )
    if lease is None or pins.author_action_id is None:
        raise ManagementDeniedError(
            "Verifier preparation needs the exact actual lease and selector"
        )
    target = await resolve_target(
        session, control, lease, pins.author_action_id, await db_now(session)
    )
    command = await producer.inputs.load_native(session, control, scope, identity, target)
    return await producer.check_payload(session, scope, command)
