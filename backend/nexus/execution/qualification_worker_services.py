"""Explicit process-local qualification composition, without credentials in queue payloads."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.core.llm.company_adapter_contracts import EndpointResolver
from nexus.core.llm.qualification_contracts import APPLICATION, QUEUE, VERSION, WORKFLOW
from nexus.execution.effect_store import EffectStore
from nexus.execution.qualification_service import QualificationPreparationService
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.qualification_evidence import FileQualificationEvidenceStore

if TYPE_CHECKING:
    from nexus.execution.qualification_worker_context import QualificationOperation

ENTRY_SECONDS = 375
ACQUISITION_SECONDS = 310
LEASE_SECONDS = 60
CLIENT_SECONDS = 55
RELEASE_SECONDS = 5


class QualificationWorkerIdentities(Protocol):
    """Existing configured credential verifier, not an actor selected by the command."""

    async def current(self) -> AuthenticatedWorkerIdentity: ...


@dataclass(frozen=True)
class QualificationWorkerServices:
    """One native factory, fixed catalog and protected store, disabled until configured."""

    factory: async_sessionmaker[AsyncSession]
    execution: ExecutionStore
    effects: EffectStore
    preparation: QualificationPreparationService
    identities: QualificationWorkerIdentities
    resolver: EndpointResolver
    evidence: FileQualificationEvidenceStore
    worker_id: UUID
    registration: WorkflowRegistration
    _operations: dict[str, QualificationOperation] = field(
        default_factory=dict, init=False, repr=False
    )
    _bound: tuple[object, ...] = field(default=(), init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.execution) is not ExecutionStore
            or type(self.effects) is not EffectStore
            or type(self.preparation) is not QualificationPreparationService
            or type(self.evidence) is not FileQualificationEvidenceStore
            or (
                self.registration.workflow_name,
                self.registration.workflow_version,
                self.registration.queue_name,
                self.registration.application_name,
            )
            != (WORKFLOW, VERSION, QUEUE, APPLICATION)
        ):
            raise ValueError("Qualification needs its fixed concrete native composition")
        object.__setattr__(
            self,
            "_bound",
            (
                self.factory,
                self.execution,
                self.effects,
                self.preparation,
                self.identities,
                self.resolver,
                self.evidence,
                self.worker_id,
                self.registration,
                self.evidence._root,
                self.preparation._recipes,
            ),
        )
        self.require_composition()

    def require_composition(self) -> None:
        """Reject dependency/factory/catalog splices before and after awaited boundaries."""
        actual = (
            self.factory,
            self.execution,
            self.effects,
            self.preparation,
            self.identities,
            self.resolver,
            self.evidence,
            self.worker_id,
            self.registration,
            self.evidence._root,
            self.preparation._recipes,
        )
        if (
            any(a is not b for a, b in zip(actual[:7], self._bound[:7], strict=True))
            or actual[7:] != self._bound[7:]
            or self.execution._factory is not self.factory
            or self.effects._factory is not self.factory
            or self.preparation.factory is not self.factory
        ):
            raise ValueError("Qualification original native composition changed")

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        """Keep actual resource tasks reachable; no completed wrapper implies settlement."""
        return tuple(
            dict.fromkeys(
                task
                for operation in self._operations.values()
                for task in operation.pending_owners()
            )
        )
