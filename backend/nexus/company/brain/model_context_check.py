"""Exact server-assembled Brain context revalidation inside one governed model intent."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import AssembledContext
from nexus.company.brain.interfaces import ContextRevalidator
from nexus.company.brain.models import BrainSource
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest
from nexus.core.llm.company_registry import DataClassification
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now, require_lease
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_authorizer_contracts import ModelInputRecipe, model_action_parameters

_CLASSIFICATIONS: tuple[DataClassification, ...] = (
    "public",
    "internal",
    "confidential",
    "restricted",
)


class BrainModelContextCheck:
    """Trusted per-call composition, never constructed from an HTTP/model manifest alone.

    The runtime supplies the actual verified identity and assembled context. This
    guard grants no model permit, token qualification, cost hold or work allowance;
    the existing M1 full-request estimator and authorization must also pass.
    """

    def __init__(
        self,
        revalidator: ContextRevalidator,
        context: AssembledContext,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        request: CompanyModelRequest,
        input_recipe: ModelInputRecipe,
        lease: ExecutionLease,
        *,
        allowed_classification: DataClassification,
    ) -> None:
        self._context = AssembledContext.model_validate_json(context.model_dump_json())
        self._scope = BrainReadScope.model_validate_json(scope.model_dump_json())
        self._identity = VerifiedIdentity.model_validate(identity.model_dump())
        self._request = CompanyModelRequest.model_validate_json(
            request.model_dump_json(by_alias=True)
        )
        self._recipe = ModelInputRecipe.model_validate_json(input_recipe.model_dump_json())
        self._lease = ExecutionLease.model_validate_json(lease.model_dump_json())
        self._revalidator, self._classification = revalidator, allowed_classification
        self._require_snapshot_binding()

    @property
    def context(self) -> AssembledContext:
        """Expose the frozen captured context, never a client-issued authorization permit."""
        return self._context

    def _require_snapshot_binding(self) -> None:
        scope, call, lease = self._scope, self._request, self._lease
        manifest, authority = self.context.manifest, self.context.manifest.authority
        self._require_audit_binding()
        registered = (lease.task_id, lease.trace_id, lease.actor_id)
        if (
            self._classification not in _CLASSIFICATIONS
            or (scope.principal_id, scope.workspace_id)
            != (self._identity.principal_id, self._identity.workspace_id)
            or (scope.company_id, scope.workspace_id, scope.principal_id)
            != (lease.company_id, lease.workspace_id, lease.actor_id)
            or (scope.task_id, scope.task_trace_id, scope.actor_id) != registered
            or (manifest.task_id, manifest.task_trace_id, manifest.actor_id) != registered
            or (call.company_id, call.task_id, call.trace_id, call.actor_id)
            != (lease.company_id, lease.task_id, lease.trace_id, lease.actor_id)
            or lease.mode != "execute"
            or call.attempt_id != call.action_id
            or (call.input_text, call.system_text)
            != (self.context.input_text, self.context.system_text)
            or (authority.model_profile, authority.model_recipe, authority.model_recipe_revision)
            != (self._recipe.profile, self._recipe.recipe_id, self._recipe.revision)
            or (manifest.data_classification, call.data_classification)
            != (self._classification, self._classification)
        ):
            raise BrainDeniedError("Model context/request/signed scope or explicit recipe differs")

    def _require_audit_binding(self) -> None:
        scope, manifest = self._scope, self.context.manifest
        if (
            manifest.company_id,
            manifest.principal_id,
            manifest.operation_id,
            manifest.trace_id,
        ) != (scope.company_id, scope.principal_id, scope.operation_id, scope.trace_id):
            raise BrainDeniedError("Model context audit scope differs from its verified scope")

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        """Recheck current context and approval under the existing M1 company/fence lock."""
        if not session.in_transaction() or control.company_id != self._scope.company_id:
            raise BrainDeniedError("Model context needs its current company transaction")
        require_lease(work, self._lease, await db_now(session), execute=True)
        if (work.company_id, work.workspace_id, work.task_id, work.trace_id, work.actor_id) != (
            self._scope.company_id,
            self._scope.workspace_id,
            self._scope.task_id,
            self._scope.task_trace_id,
            self._scope.actor_id,
        ):
            raise BrainDeniedError("Model context work binding is unavailable")
        proposal = ActionProposal.model_validate_json(action.proposal_json)
        if (
            proposal.action_id != self._request.action_id
            or (proposal.tool, proposal.tool_version, proposal.resource)
            != ("model.request.v1", "v1", f"model:{self._request.registry_id}")
            or proposal.parameters != model_action_parameters(self._request, self._recipe)
        ):
            raise BrainDeniedError("Model context differs from the exact approved action")
        required = await self._revalidator.revalidate_context(
            session,
            control,
            self._scope,
            self._identity,
            self.context.manifest,
            await db_now(session),
        )
        _require_preconditions(proposal, required)
        await self._require_classification(session)
        require_lease(work, self._lease, await db_now(session), execute=True)

    async def _require_classification(self, session: AsyncSession) -> None:
        """Use current source policy classifications, including every omitted contributor."""
        source_ids = tuple(row.source_id for row in self.context.manifest.source_heads)
        classes = tuple(
            (
                await session.scalars(
                    select(BrainSource.data_classification).where(
                        BrainSource.company_id == self._scope.company_id,
                        BrainSource.source_id.in_(source_ids),
                    )
                )
            ).all()
        )
        if len(classes) != len(source_ids):
            raise BrainDeniedError("Model context source classification is unavailable")
        current = max(
            (self.context.manifest.authority.data_classification, *classes),
            key=_CLASSIFICATIONS.index,
        )
        if current != self._classification:
            raise BrainDeniedError(
                "Model request must use the exact current maximum classification"
            )


def _require_preconditions(
    proposal: ActionProposal, required: tuple[ResourceRevision, ...]
) -> None:
    """All current Brain resource/head conditions must belong to the exact owner approval."""
    approved = tuple(
        row
        for row in proposal.preconditions
        if row.resource.startswith(("brain.resource:", "brain.source:"))
    )
    if len({row.resource for row in required}) != len(required) or {
        (row.resource, row.revision) for row in required
    } != {(row.resource, row.revision) for row in approved}:
        raise BrainDeniedError("Current Brain preconditions differ from the approved action")
