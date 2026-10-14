"""Recompute full report/check publication inputs using actual registered work and receipts."""

import json
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_support import resolve_target
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import SourceQuoteClaim, StructuredInternalReport
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactPayload,
)
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


class NativeReportValidator:
    """Mandatory server recomputation; decoded payload hashes cannot authorize publication."""

    def __init__(self, producer: NativeReportProducer) -> None:
        self.producer = producer

    async def revalidate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        lease: ExecutionLease,
        actual_action: ActionProposal,
        prepared: GeneratedArtifactPayload,
        now: datetime,
    ) -> None:
        """Resolve native selectors and compare complete exact bytes, facts and manifests."""
        pins = GeneratedArtifactActionParameters.model_validate_json(
            json.dumps(actual_action.parameters, allow_nan=False)
        )
        require_acceptance(
            prepared.company_id == scope.company_id == lease.company_id == actual_action.company_id
            and actual_action.task_id == scope.task_id == lease.task_id
            and scope.principal_id == lease.actor_id == identity.principal_id
            and scope.actor_id == actual_action.actor_id == lease.actor_id
            and scope.task_trace_id == actual_action.trace_id == lease.trace_id
        )
        if actual_action.tool == "company.report.write.v1":
            current = await self.producer.recompute_report(
                session, control, scope, identity, prepared.raw_bytes
            )
            report = StructuredInternalReport.model_validate_json(current.raw_bytes)
            require_acceptance(
                pins.report_id == report.operating.snapshot.report_id
                and pins.evidence_ids
                == tuple(
                    claim.evidence_id
                    for claim in report.claims
                    if isinstance(claim, SourceQuoteClaim)
                )
            )
        else:
            require_acceptance(
                actual_action.tool == "company.report.check.v1"
                and pins.author_action_id is not None
            )
            assert pins.author_action_id is not None
            target = await resolve_target(
                session, control, lease, pins.author_action_id, await db_now(session)
            )
            require_acceptance(canonical_sha256(target) == pins.verification_target_sha256)
            command = await self.producer.inputs.load_native(
                session, control, scope, identity, target
            )
            current = await self.producer.check_payload(session, scope, command)
        require_acceptance(
            current == prepared
            and pins.output_sha256 == current.output_sha256
            and pins.input_snapshot_sha256 == current.input_snapshot_sha256
            and pins.recipe_version == current.recipe_version
        )
