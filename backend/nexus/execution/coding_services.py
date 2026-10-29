"""Concrete fixed C server graph; construction performs no actor/key/SQL/model lookup."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.context import ContextSelection
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_prepared_store import CodingPreparedStore
from nexus.company.management.coding_repository import (
    CodingRepositoryReader,
    CodingRepositorySelection,
)
from nexus.company.management.coding_sources import CodingSourceRef, coding_selection
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission
from nexus.company.management.nexus_coding_catalog import configured_nexus_admission
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.planning_authority import ManagementPlanningAuthority
from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.core.llm.company_adapter_contracts import EndpointResolver
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.model_workflow_identity import application_version
from nexus.execution.planning_application_config import PlanningSourcePolicies
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.model_authorizer_contracts import ModelInputRecipe
from nexus.harness.model_evidence import FileModelEvidenceStore
from nexus.harness.model_input_estimator import FullContextInputEstimator

if TYPE_CHECKING:
    from nexus.execution.coding_operation import CodingOperation

WORKFLOW, VERSION = "company.coding.v1", "v1"
QUEUE, APPLICATION = "nexus.coding", "nexus-coding"
ENTRY_SECONDS, LEASE_SECONDS, CLIENT_SECONDS = 375, 60, 55
REGISTRATION = WorkflowRegistration(
    workflow_name=WORKFLOW, workflow_version=VERSION, queue_name=QUEUE, application_name=APPLICATION
)
APPLICATION_VERSION = application_version(REGISTRATION)


@dataclass(frozen=True, kw_only=True)
class CodingServices:
    """Same native graph and immutable server source choices; no decoded permission."""

    factory: async_sessionmaker[AsyncSession]
    management: ManagementExecutionServices
    contexts: PersistentContextAssembler
    prepared_blobs: ProtectedBlobStore
    source_views: OwnerViewSources
    repository_path: Path
    repository_selection: CodingRepositorySelection
    code_sources: tuple[CodingSourceRef, ...]
    estimator: FullContextInputEstimator
    recipe: ModelInputRecipe
    identities: NotificationWorkerIdentities
    resolver: EndpointResolver
    evidence: FileModelEvidenceStore
    worker_id: UUID
    registry_id: str
    max_output_tokens: int
    authority: ManagementPlanningAuthority = field(init=False)
    execution: ExecutionStore = field(init=False)
    selection: ContextSelection = field(init=False)
    _bound: tuple[object, ...] = field(init=False, repr=False)
    _operations: dict[str, CodingOperation] = field(default_factory=dict, init=False, repr=False)
    _stores: list[CodingPreparedStore] = field(default_factory=list, init=False, repr=False)
    _stopping: Event = field(default_factory=Event, init=False, repr=False)

    def __post_init__(self) -> None:
        # Cohesion exception: retain the complete exact C graph/nomination check (>50 lines).
        if (
            type(self.management) is not ManagementExecutionServices
            or type(self.contexts) is not PersistentContextAssembler
            or type(self.contexts._retriever) is not PersistentBrainRetriever
            or type(self.contexts._retriever.blobs) is not ProtectedBlobStore
            or type(self.contexts._authority) is not ManagementPlanningAuthority
            or type(self.management.freshness) is not RegisteredSourceFreshness
            or type(self.prepared_blobs) is not ProtectedBlobStore
            or type(self.source_views) is not OwnerViewSources
            or type(self.estimator) is not FullContextInputEstimator
            or type(self.identities) is not NotificationWorkerIdentities
            or type(self.evidence) is not FileModelEvidenceStore
            or type(self.max_output_tokens) is not int
        ):
            raise ValueError("Coding requires its actual fixed native/context/source graph")
        object.__setattr__(
            self, "recipe", ModelInputRecipe.model_validate_json(self.recipe.model_dump_json())
        )
        object.__setattr__(
            self,
            "repository_selection",
            CodingRepositorySelection.model_validate_json(
                self.repository_selection.model_dump_json()
            ),
        )
        object.__setattr__(
            self,
            "code_sources",
            tuple(
                CodingSourceRef.model_validate_json(row.model_dump_json())
                for row in self.code_sources
            ),
        )
        object.__setattr__(self, "selection", coding_selection(self.code_sources))
        authority = self.contexts._authority
        object.__setattr__(self, "authority", authority)
        admission = configured_nexus_admission(self.management.catalog)
        if not isinstance(admission, NexusCodingAdmission):
            raise ValueError("Coding requires its complete configured ten-role admission")
        slot = admission.slots[1]
        row = next(
            (
                row
                for row in self.management.catalog.models.models
                if row.registry_id == self.registry_id
            ),
            None,
        )
        if (
            row is None
            or slot.tool.resource != "model:" + self.registry_id
            or self.recipe.profile != "engineering"
            or not 0 < self.max_output_tokens <= row.max_output_tokens
            or authority.management is not self.management
            or authority.recipe != self.recipe
            or (
                authority.policy.workflow_name,
                authority.policy.workflow_version,
                authority.policy.model_profile,
            )
            != (WORKFLOW, VERSION, "engineering")
            or self.repository_selection.company_id != self.management.catalog.company_id
            or tuple(row.git for row in self.code_sources) != self.repository_selection.files
            or not self.repository_path.is_absolute()
            or self.repository_path.resolve() != self.repository_path
            or self.source_views.artifacts is not self.management.artifacts
            or self.source_views.freshness is not self.management.freshness
            or self.authority is not self.contexts._authority
            or self.contexts._factory is not self.factory
            or self.contexts._retriever.factory is not self.factory
            or self.contexts._retriever.blobs is not self.management.artifacts.blobs
            or self.management.artifacts.factory is not self.factory
            or self.management.freshness._factory is not self.factory
        ):
            raise ValueError("Coding configured C target/source/factory/authority differs")
        object.__setattr__(self, "execution", self.management.execution_store(self.factory))
        object.__setattr__(self, "_bound", self._pins())

    def _pins(self) -> tuple[object, ...]:
        return (
            self.factory,
            self.management,
            self.contexts,
            self.prepared_blobs,
            self.source_views,
            self.estimator,
            self.identities,
            self.resolver,
            self.evidence,
            self.execution,
            self.contexts._authority,
            self.contexts._retriever,
            self.management.artifacts,
            self.management.freshness,
            self.contexts._retriever.blobs,
            self._policies(),
            canonical_sha256(self._policies()),
            canonical_sha256(self.management.catalog),
            canonical_sha256(self.recipe),
            canonical_sha256(self.selection),
            canonical_sha256(self.repository_selection),
            tuple(canonical_sha256(row) for row in self.code_sources),
            self.repository_path,
            self.worker_id,
            self.registry_id,
            self.max_output_tokens,
            self.prepared_blobs._root,
            self.evidence._root,
        )

    def _policies(self) -> PlanningSourcePolicies:
        freshness = self.management.freshness
        if (
            type(freshness) is not RegisteredSourceFreshness
            or type(freshness._policies) is not PlanningSourcePolicies
        ):
            raise ValueError("Coding requires its concrete immutable source-policy lookup")
        return freshness._policies

    def require_composition(self) -> None:
        actual = self._pins()
        if (
            any(a is not b for a, b in zip(actual[:16], self._bound[:16], strict=True))
            or actual[16:] != self._bound[16:]
            or self.authority is not self.contexts._authority
            or self.execution._factory is not self.factory
            or self.contexts._factory is not self.factory
            or self.contexts._retriever.factory is not self.factory
            or self.contexts._retriever.blobs is not self.management.artifacts.blobs
            or self.source_views.artifacts is not self.management.artifacts
            or self.source_views.freshness is not self.management.freshness
        ):
            raise ValueError("Original coding composition changed")
        self.authority._require_original()
        for store in self._stores:
            store.require_composition()

    def require_actor_scope(
        self, scope: LedgerScope, credential: AuthenticatedWorkerIdentity
    ) -> None:
        """Reject posted identities before a claim; actual current native checks still follow."""
        self.require_composition()
        admission = self.management.catalog.nexus_coding_admission
        assert admission is not None
        bound = admission.slots[1].child.binding
        if type(credential) is not AuthenticatedWorkerIdentity or (
            scope.company_id,
            scope.principal_id,
            scope.task_id,
            scope.trace_id,
            credential.identity.principal_id,
            credential.identity.workspace_id,
        ) != (
            bound.company_id,
            bound.actor_id,
            bound.task_id,
            bound.trace_id,
            bound.actor_id,
            bound.workspace_id,
        ):
            raise ValueError("Coding requires its exact configured C actor/work scope")

    def require_accepting(self) -> None:
        self.require_composition()
        if self._stopping.is_set():
            raise ValueError("Coding admission is stopped")

    def create_prepared(self) -> CodingPreparedStore:
        """Retain a new concrete operation owner; a stopped old reader is never reset."""
        self.require_accepting()
        store = CodingPreparedStore(
            self.factory,
            self.management,
            self.contexts,
            self.prepared_blobs,
            self.source_views,
            self.recipe,
            CodingRepositoryReader(self.repository_path, self.repository_selection),
        )
        self._stores.append(store)
        return store

    def request_stop(self) -> None:
        """Stop admission and adoption; actual issued native/SDK/Git/file owners remain."""
        self._stopping.set()
        for operation in tuple(self._operations.values()):
            operation.request_stop()
        for store in self._stores:
            store.request_stop()

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return tuple(
            dict.fromkeys(
                (
                    *self.prepared_blobs.pending_owners(),
                    *self.evidence.pending_owners(),
                    *cast(ProtectedBlobStore, self.contexts._retriever.blobs).pending_owners(),
                    *(task for store in self._stores for task in store.pending_owners()),
                    *(
                        task
                        for operation in tuple(self._operations.values())
                        for task in operation.pending_owners()
                    ),
                )
            )
        )
