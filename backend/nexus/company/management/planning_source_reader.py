"""Current owner READ of exact native/protected planning provenance, never a lease."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.context import AssembledContext, ContextManifest
from nexus.company.brain.retrieval_records import heads
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import db_clock
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.owner_view_sources import (
    OwnerViewSources,
    owner_brain_scope,
)
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.planning_content import PlanningContent, planning_annotation
from nexus.company.management.planning_native_facts import (
    NativePlanning,
    clock_us,
    native_planning,
    read_end,
    require_time,
)
from nexus.company.management.planning_origin_contracts import PlanningOriginRef
from nexus.company.management.revision_store import plan_record
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.core.llm.company_adapter_contracts import request_hash
from nexus.core.llm.company_pricing import reconcile_cost
from nexus.harness.journal_models import CompanyControl
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence

if TYPE_CHECKING:
    from nexus.company.management.planning_proposal_bridge import PlanningProposalTemplate
    from nexus.company.management.plans import PlanPayload


@dataclass(frozen=True)
class PlanningSource:
    """Descriptions/questions remain available for review; this is no approved plan."""

    origin: PlanningOriginRef
    content: PlanningContent
    manifest: ContextManifest
    model_recorded_at: datetime


class PlanningSourceReader:
    """Concrete composition; posted origin fields select and never attest provenance."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        models: FileModelEvidenceStore,
        retriever: PersistentBrainRetriever,
        sources: OwnerViewSources,
        template: PlanningProposalTemplate,
    ) -> None:
        from nexus.company.management.planning_proposal_bridge import PlanningProposalTemplate

        if (
            type(models) is not FileModelEvidenceStore
            or type(retriever) is not PersistentBrainRetriever
            or retriever.factory is not factory
            or sources.artifacts.factory is not factory
            or retriever.blobs is not sources.artifacts.blobs
        ):
            raise ValueError("Planning reader requires the actual same-factory protected readers")
        self.factory, self.models, self.retriever, self.sources = (
            factory,
            models,
            retriever,
            sources,
        )
        self.template = PlanningProposalTemplate.model_validate_json(template.model_dump_json())
        self._original = (factory, models, retriever, sources, self.template)
        self._reads: list[asyncio.Task[ModelEvidence]] = []

    def _composition(self) -> None:
        if (
            any(
                current is not original
                for current, original in zip(
                    (self.factory, self.models, self.retriever, self.sources, self.template),
                    self._original,
                    strict=True,
                )
            )
            or self.retriever.factory is not self.factory
            or self.sources.artifacts.factory is not self.factory
            or self.retriever.blobs is not self.sources.artifacts.blobs
        ):
            raise ManagementDeniedError("Planning reader composition changed")

    def pending_owners(self) -> tuple[asyncio.Task[ModelEvidence], ...]:
        return tuple(row for row in self._reads if not row.done())

    async def load(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        expected_goal: GoalRevisionRef,
        expected_current_revision_id: UUID,
        end_us: int,
    ) -> PlanningSource:
        end_us = read_end(end_us)
        if (expected_goal, expected_current_revision_id) != (
            self.template.base_plan.payload.goal,
            self.template.base_plan.plan_revision_id,
        ):
            raise ManagementDeniedError("Planning selection differs from its exact bootstrap")
        async with management_owner_transaction(self.factory, scope, identity) as (
            session,
            control,
            _,
        ):
            return await self._load_locked(
                session, control, scope, identity, action_id, None, end_us
            )

    async def revalidate_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        payload: PlanPayload,
        *,
        target_revision_id: UUID | None,
        end_us: int,
    ) -> None:
        from nexus.company.management.planning_proposal_bridge import map_content

        if payload.planning_origin is None:
            raise ManagementDeniedError("Planning payload has no origin")
        exact_target = uuid5(
            payload.plan.plan_id, f"plan:{payload.plan.revision}:{canonical_sha256(payload)}"
        )
        if target_revision_id is not None and target_revision_id != exact_target:
            raise ManagementDeniedError("Planning target selector differs from the exact payload")
        source = await self._load_locked(
            session,
            control,
            scope,
            identity,
            payload.planning_origin.action_id,
            exact_target,
            end_us,
        )
        if (
            source.origin != payload.planning_origin
            or map_content(source.content, source.origin, self.template) != payload
        ):
            raise ManagementDeniedError(
                "Formal payload differs from protected content/server slots"
            )
        target = await session.get(ManagementPlanRevision, (scope.company_id, exact_target))
        if (target_revision_id is not None and target is None) or (
            target is not None and plan_record(target).payload != payload
        ):
            raise ManagementDeniedError("Actual stored planning target differs from payload")
        require_time(end_us)

    async def _load_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        target_id: UUID | None,
        end_us: int,
    ) -> PlanningSource:
        self._composition()
        native = await native_planning(
            session,
            control,
            scope,
            identity,
            action_id,
            target_id,
            end_us,
            self.template,
            self.sources,
        )
        self._composition()
        read = asyncio.create_task(self.models.load(native.receipt.artifacts[0]))
        self._reads.append(read)
        try:
            saved = await asyncio.wait_for(
                asyncio.shield(read), max(0, (end_us - clock_us()) / 1_000_000)
            )
        except BaseException as error:
            read.add_done_callback(_consume)
            error._nexus_planning_pending = (read,)  # type: ignore[attr-defined]
            raise
        require_time(end_us)
        source = self._interpret(saved, native)
        brain = owner_brain_scope(scope, identity)
        manifest = source.manifest
        grants = await require_resources(
            session,
            brain,
            tuple(row.resource_id for row in manifest.contributors),
            await db_clock(session),
        )
        if (
            grants != manifest.contributors
            or await heads(session, brain, tuple(row.current for row in manifest.source_heads))
            != manifest.source_heads
        ):
            raise ManagementDeniedError("Planning context resources or source heads changed")
        await self.retriever.revalidate_handles(
            session,
            control,
            brain,
            identity,
            tuple(row.handle for row in manifest.inclusions),
            await db_clock(session),
        )
        if (
            await native_planning(
                session,
                control,
                scope,
                identity,
                action_id,
                target_id,
                end_us,
                self.template,
                self.sources,
            )
            != native
        ):
            raise ManagementDeniedError("Planning native provenance changed during protected READ")
        self._composition()
        require_time(end_us)
        return source

    def _interpret(self, saved: ModelEvidence, native: NativePlanning) -> PlanningSource:
        saved.require_binding()
        call, result, receipt = saved.request, saved.result, native.receipt
        if (
            call.output_schema is None
            or call.system_text is None
            or result.status != "response"
            or result.billing != "known"
            or result.usage is None
            or result.structured_json is None
            or result.tool_calls
            or saved.model.price is None
        ):
            raise ManagementDeniedError(
                "Only known successful structured planning results are readable"
            )
        binding, manifest = planning_annotation(call.output_schema)
        AssembledContext(
            company_id=call.company_id,
            manifest=manifest,
            system_text=call.system_text,
            input_text=call.input_text,
        )
        base = self.template.base_plan
        original = base.payload.children[0].binding
        if (
            (binding.goal, binding.plan_id, binding.expected_plan_revision_id)
            != (base.payload.goal, base.plan_id, base.plan_revision_id)
            or (saved.recipe.profile, call.registry_revision)
            != (original.model_profile, original.model_registry_version)
            or (
                manifest.authority.model_profile,
                manifest.authority.model_recipe,
                manifest.authority.model_recipe_revision,
            )
            != (saved.recipe.profile, saved.recipe.recipe_id, saved.recipe.revision)
            or manifest.principal_id != call.actor_id
            or (manifest.company_id, manifest.task_id, manifest.task_trace_id, manifest.actor_id)
            != (call.company_id, call.task_id, call.trace_id, call.actor_id)
            or (call.company_id, call.task_id, call.trace_id, call.actor_id, call.action_id)
            != (
                native.proposal.company_id,
                native.proposal.task_id,
                native.proposal.trace_id,
                native.proposal.actor_id,
                native.proposal.action_id,
            )
            or native.proposal.resource != f"model:{call.registry_id}"
            or native.proposal.parameters != model_action_parameters(call, saved.recipe)
            or saved.action_hash != receipt.proposal_hash
            or receipt.artifacts[0].artifact_id != uuid5(call.action_id, str(call.request_id))
            or receipt.recorded_at != saved.checked_at
            or saved.owner_id not in receipt.artifacts[0].allowed_principals
            or not native.intent_created_at <= saved.source_event_at <= saved.checked_at
            or native.actual_usd
            != reconcile_cost(saved.model.price, result.usage, now=saved.source_event_at).amount_usd
        ):
            raise ManagementDeniedError(
                "Protected planning envelope differs from its native result"
            )
        content = PlanningContent.model_validate_json(result.structured_json)
        content.require_evidence(tuple(row.handle.evidence_id for row in manifest.inclusions))
        origin = PlanningOriginRef(
            company_id=call.company_id,
            goal=binding.goal,
            source_plan_id=base.plan_id,
            source_plan_revision_id=base.plan_revision_id,
            task_id=call.task_id,
            action_id=call.action_id,
            request_id=call.request_id,
            receipt_id=receipt.receipt_id,
            artifact_id=receipt.artifacts[0].artifact_id,
            artifact_sha256=receipt.artifacts[0].sha256,
            request_sha256=request_hash(call),
            context_manifest_sha256=binding.context_manifest_sha256,
            content_sha256=canonical_sha256(content),
            mapping_revision=self.template.revision,
            mapping_sha256=canonical_sha256(self.template),
        )
        return PlanningSource(origin, content, manifest, saved.checked_at)


def _consume(read: asyncio.Task[ModelEvidence]) -> None:
    if not read.cancelled():
        read.exception()
