"""Actual registered source metadata/complete READ/freshness binds the committed repository."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_services import ContainmentServices
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runtime_identity import RUNTIME_V2
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.source_models import BrainArtifactRevision, BrainSourceHead
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.company.management.generated_artifact_scope import action_expiry
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl, JournalAction


@dataclass(frozen=True)
class RegisteredBuilderSource:
    repository: Path
    metadata: ArtifactRevisionRef


class BuilderSourceGuard:
    def __init__(
        self,
        spec: BuilderExecutionSpec,
        policy: BuilderToolPolicy,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        source: RegisteredBuilderSource,
        artifacts: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
        catalog: PlanAdmissionCatalog,
        *,
        containment: ContainmentServices | None = None,
    ) -> None:
        self.spec, self.policy, self.lease, self.identity = spec, policy, lease, identity
        self.source, self.artifacts, self.freshness, self.catalog = (
            source,
            artifacts,
            freshness,
            catalog,
        )
        self.deadlines: tuple[datetime, ...] = ()
        self.containment = containment

    def scope(self) -> BrainReadScope:
        lease = self.lease
        return BrainReadScope(
            company_id=lease.company_id,
            workspace_id=lease.workspace_id,
            principal_id=self.identity.principal_id,
            operation_id=self.spec.job.action_id,
            trace_id=lease.trace_id,
            task_id=lease.task_id,
            task_trace_id=lease.trace_id,
            actor_id=lease.actor_id,
        )

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        actual = ActionProposal.model_validate_json(action.proposal_json)
        if actual.parameters != self.spec.model_dump(mode="json"):
            raise ValueError("Builder exact proposal descriptor differs")
        if self.spec.runtime_recipe == RUNTIME_V2:
            if type(self.containment) is not ContainmentServices:
                raise ValueError("Builder runtime v2 source guard is not configured")
            self.containment.require_policy(self.spec, self.policy)
        else:
            self.spec.require_policy(self.policy)
        if self.spec.output_resource is not None and tuple(
            row.resource
            for row in self.catalog.resources
            if row.symbol == self.spec.job.resource_symbol
        ) != (self.spec.output_resource,):
            raise ValueError("Builder exact output target changed before intent")
        await require_management_execution(
            session,
            control,
            work,
            self.identity,
            self.catalog,
            self.artifacts,
            self.freshness,
            actual,
            "tool_attempts",
        )
        self.deadlines = (
            self.lease.expires_at,
            await action_expiry(session, action),
            *await self.disclosure_windows(session, control),
        )
        self.validate_time(await db_now(session))

    async def disclosure_windows(
        self, session: AsyncSession, control: CompanyControl
    ) -> tuple[datetime, ...]:
        scope = self.scope()
        reference = self.source.metadata
        references = (
            reference,
            *((self.spec.protected_patch,) if self.spec.protected_patch else ()),
        )
        for current in references:
            await self.artifacts.revalidate_artifact_reference(
                session, control, scope, self.identity, current, await db_now(session)
            )
        await self.freshness.revalidate_references(
            session, scope, references, await db_now(session)
        )
        metadata = await session.get(
            BrainArtifactRevision, (scope.company_id, reference.artifact_revision_id)
        )
        if metadata is None or json.loads(metadata.raw_text) != {
            "source": self.spec.job.source.model_dump(mode="json")
        }:
            raise ValueError("Registered builder source metadata differs from the committed pin")
        ids, resources = await reference_sources(session, scope, references)
        if self.spec.output_resource is not None:
            resources = tuple(sorted({*resources, self.spec.output_resource.resource_id}))
        grants = await require_resources(session, scope, resources, await db_now(session))
        deadlines = [row.expires_at for row in grants if row.expires_at is not None]
        for key in ids:
            head = await session.get(BrainSourceHead, (scope.company_id, key))
            if head is None:
                raise ValueError("Builder input source is unavailable")
            if head.fresh_until is not None:
                deadlines.append(head.fresh_until)
        final = await db_now(session)
        if any(value <= final for value in deadlines):
            raise ValueError("Builder result source disclosure expired")
        return tuple(deadlines)

    def validate_time(self, now: datetime) -> None:
        if not self.deadlines or any(value <= now for value in self.deadlines):
            raise ValueError("Builder source, authority or execute lease expired")
