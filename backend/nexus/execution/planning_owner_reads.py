"""Exact current-owner planning input disclosure; no approval or model-call authority."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.base import SHA256, Name, ValueContract
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.base import USD
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.planning_intent import (
    PreparedPlanningRequest,
    require_planning_registry,
)
from nexus.company.management.planning_native_facts import clock_us, read_end, require_time
from nexus.company.management.planning_prepared_contracts import (
    BODY_LIMIT,
    PlanningModelParameters,
    prepared_reference,
)
from nexus.company.management.planning_prepared_store import PlanningPreparedStore
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.core.llm.company_registry import ModelRegistry, Provider
from nexus.execution.planning_lifecycle import PlanningLifecycle
from nexus.execution.planning_lifecycle_contracts import PlanningLifecycleRead
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import JournalAction
from nexus.harness.model_authorizer_contracts import model_action_parameters


class PlanningInputReview(ValueContract):
    """Owner-readable frozen input; none of these descriptive fields is a permit."""

    company_id: UUID
    action_id: UUID
    proposal_sha256: SHA256
    request_sha256: SHA256
    descriptor_sha256: SHA256
    provider: Provider
    model_id: Name
    maximum_reservation_usd: USD
    currency: Literal["USD"] = "USD"
    prepared: PreparedPlanningRequest
    company_completed: Literal[False] = False
    execution_permitted: Literal[False] = False


@dataclass(frozen=True, slots=True)
class PlanningInputReader:
    """Configured original catalog plus concrete same-factory protected/native storage."""

    store: PlanningPreparedStore
    registry: ModelRegistry
    _original: tuple[object, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.store) is not PlanningPreparedStore
            or type(self.registry) is not ModelRegistry
        ):
            raise ValueError("Planning review needs its concrete protected store and catalog")
        object.__setattr__(
            self, "registry", ModelRegistry.model_validate_json(self.registry.model_dump_json())
        )
        object.__setattr__(
            self,
            "_original",
            (
                self.store,
                self.store.factory,
                self.registry,
                canonical_sha256(self.registry),
            ),
        )

    @property
    def factory(self) -> async_sessionmaker[AsyncSession]:
        return self.store.factory

    def _composition(self) -> None:
        if (
            self.store is not self._original[0]
            or self.store.factory is not self._original[1]
            or self.registry is not self._original[2]
            or canonical_sha256(self.registry) != self._original[3]
        ):
            raise ManagementDeniedError("Original planning review composition changed")

    async def _proposal(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
    ) -> ActionProposal:
        async with management_owner_transaction(
            self.factory,
            scope,
            identity,
            allow_paused=True,
        ) as (session, control, _):
            if (scope.principal_id, identity.principal_id) != (control.owner_id, control.owner_id):
                raise ManagementDeniedError("Planning review requires its current signed owner")
            row = await session.get(JournalAction, action_id)
            if row is None or (row.company_id, row.id) != (scope.company_id, action_id):
                raise ManagementDeniedError("Planning input action is unavailable")
            proposal = ActionProposal.model_validate_json(row.proposal_json)
            parameters = PlanningModelParameters.model_validate_json(
                json.dumps(proposal.parameters)
            )
            prepared_reference(proposal)
            if (
                action_hash(proposal) != row.proposal_hash
                or (proposal.company_id, proposal.action_id, proposal.task_id, proposal.trace_id)
                != (scope.company_id, action_id, row.task_id, row.trace_id)
                or (proposal.tool, proposal.tool_version, proposal.resource)
                != ("model.request.v1", "v1", f"model:{parameters.registry_id}")
                or (
                    self.registry.company_id,
                    self.registry.revision,
                    self.registry.pricebook_version,
                )
                != (scope.company_id, parameters.registry_revision, parameters.price_version)
                or not any(
                    model.registry_id == parameters.registry_id for model in self.registry.models
                )
            ):
                raise ManagementDeniedError("Planning input differs from native action/catalog")
            return proposal

    async def input(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> PlanningInputReview:
        """Compatibility view retaining the protected read's original shortened cutoff."""
        result = await self.read(scope, identity, action_id, end_us=end_us)
        require_time(result.read_end_us)
        return result.value

    async def read(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> PlanningLifecycleRead[PlanningInputReview]:
        """Metadata first, then final awaited protected READ, then immutable CPU-only joins."""
        end_us = read_end(end_us)
        self._composition()
        async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
            proposal = await self._proposal(scope, identity, action_id)
        require_time(end_us)
        self._composition()
        reference = prepared_reference(proposal)
        proposal_sha256 = action_hash(proposal)
        # This is deliberately the last await: it rechecks actual owner/source/native/goal/CAS.
        loaded = await self.store.load_owner(scope, identity, action_id, end_us=end_us)
        end_us = min(end_us, loaded.read_end_us)
        self._composition()
        prepared = loaded.prepared
        model = require_planning_registry(prepared, self.registry)
        if (
            loaded.reference != reference
            or proposal.parameters
            != model_action_parameters(prepared.request, prepared.input_recipe)
            or (
                prepared.request.company_id,
                prepared.request.action_id,
                prepared.request.task_id,
                prepared.request.trace_id,
                prepared.request.actor_id,
            )
            != (scope.company_id, action_id, proposal.task_id, proposal.trace_id, proposal.actor_id)
        ):
            raise ManagementDeniedError("Protected planning input differs from its exact proposal")
        view = PlanningInputReview(
            company_id=scope.company_id,
            action_id=action_id,
            proposal_sha256=proposal_sha256,
            request_sha256=prepared.request_sha256,
            descriptor_sha256=reference.descriptor.sha256,
            provider=model.provider,
            model_id=model.model_id,
            maximum_reservation_usd=proposal.estimated_cost_usd,
            prepared=prepared,
        )
        if len(view.model_dump_json(by_alias=True).encode()) > BODY_LIMIT + 16_384:
            raise ManagementDeniedError("Complete planning input response exceeds its bound")
        self._composition()
        require_time(end_us)
        return PlanningLifecycleRead(view, end_us)


@dataclass(frozen=True, slots=True)
class PlanningApiServices:
    """Optional data-only owner routes; construction opens no DB, worker or provider."""

    reads: PlanningInputReader
    lifecycle: PlanningLifecycle | None = None
    directory: PersistentCompanyDirectory = field(init=False)
    _lifecycle_binding: tuple[object, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.reads) is not PlanningInputReader:
            raise ValueError("Planning API requires its concrete protected input reader")
        self.reads._composition()
        object.__setattr__(self, "directory", PersistentCompanyDirectory(self.reads.factory))
        object.__setattr__(self, "_lifecycle_binding", (self.reads, self.lifecycle, self.directory))
        self.require_lifecycle()

    def require_lifecycle(self) -> PlanningLifecycle | None:
        """Optional product routes share the exact protected input and native graph."""
        if any(
            a is not b
            for a, b in zip(
                (self.reads, self.lifecycle, self.directory), self._lifecycle_binding, strict=True
            )
        ):
            raise ManagementDeniedError("Original planning API lifecycle changed")
        self.reads._composition()
        value = self.lifecycle
        if value is None:
            return None
        from nexus.execution.planning_lifecycle import PlanningLifecycle

        if value is not None:
            if (
                type(value) is not PlanningLifecycle
                or self.reads.store is not value.services.prepared
                or self.directory._factory is not value.factory
                or canonical_sha256(self.reads.registry)
                != canonical_sha256(value.config.catalog.models)
            ):
                raise ManagementDeniedError(
                    "Planning lifecycle differs from actual protected input graph"
                )
            value.require_composition()
        return value
