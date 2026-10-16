"""One concrete governed C request yields historical content, never a published patch.

The cohesive file-size exception keeps original actor admission, actual client/read
owners and final protected provenance/adoption together without a weaker inherited
planner path or another lifecycle abstraction.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.contracts.actions import ResourceRevision
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_content import (
    CodeChangeContent,
    CodingAttempt,
    CodingCandidate,
    validate_code_change,
)
from nexus.company.management.coding_intent import (
    CodingIntentCheck,
    PreparedCodingRequest,
    require_coding_registry,
)
from nexus.company.management.coding_prepared_checks import conditions
from nexus.company.management.coding_prepared_contracts import StoredCodingRequest
from nexus.company.management.coding_prepared_store import CodingPreparedStore
from nexus.company.management.coding_sources import require_coding_sources
from nexus.company.management.coding_stored_intent import StoredCodingIntent
from nexus.company.management.nexus_coding_model_intent import NexusCodingModelIntentCheck
from nexus.company.management.planning_authority import ManagementPlanningAuthority
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.core.llm.company_adapter_contracts import EndpointResolver, request_hash
from nexus.core.llm.company_pricing import reconcile_cost
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer
from nexus.harness.model_authorizer_contracts import ModelInputRecipe
from nexus.harness.model_client import GovernedModelClient
from nexus.harness.model_client_contracts import GovernedModelCancelledError, GovernedModelResult
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence
from nexus.harness.model_input_estimator import FullContextInputEstimator


class CodingReadCancelledError(GovernedModelCancelledError):
    """Keep the actual read owner and governed charge while propagating denied cancellation."""

    def __init__(
        self,
        governed: GovernedModelResult,
        read: asyncio.Task[ModelEvidence],
        first: asyncio.CancelledError,
    ) -> None:
        self.evidence_read = read
        super().__init__(governed)
        self.__dict__["_nexus_model_first"] = first


def _clock() -> int:
    return time.monotonic_ns() // 1000


class RegisteredCodingConsumer:
    """Actual C actor/context/estimator/native client, inactive until required native gates.

    The later producer/worker must retain this instance through actual resource
    settlement and require its durable original source-proof condition. A decoded
    preparation is no such permission; the current closed router may deny C.
    Issued metadata replay must not construct another consumer or request a lease.
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        management: ManagementExecutionServices,
        contexts: PersistentContextAssembler,
        evidence: FileModelEvidenceStore,
        resolver: EndpointResolver,
        input_estimator: FullContextInputEstimator,
        input_recipe: ModelInputRecipe,
        lease: ExecutionLease,
        credential: AuthenticatedWorkerIdentity,
        *,
        resources: tuple[ResourceRevision, ...],
        prepared_store: CodingPreparedStore,
        stored: StoredCodingRequest,
        end_us: int,
        sdk_end_us: int,
    ) -> None:
        if (
            type(prepared_store) is not CodingPreparedStore
            or type(management) is not ManagementExecutionServices
            or type(contexts) is not PersistentContextAssembler
            or type(contexts._retriever) is not PersistentBrainRetriever
            or type(contexts._retriever.blobs) is not ProtectedBlobStore
            or type(contexts._authority) is not ManagementPlanningAuthority
            or type(evidence) is not FileModelEvidenceStore
            or type(input_estimator) is not FullContextInputEstimator
            or type(credential) is not AuthenticatedWorkerIdentity
        ):
            raise ValueError(
                "Coding needs its concrete original server composition and genuine C actor"
            )
        prepared_store.require_loaded(stored, credential, lease)
        if (
            prepared_store.factory is not factory
            or prepared_store.management is not management
            or prepared_store.contexts is not contexts
            or stored.prepared.input_recipe != input_recipe
            or resources != conditions(stored.header)
        ):
            raise ValueError(
                "Coding consumer requires its actual original store/source condition graph"
            )
        self._prepared_store, self._stored = prepared_store, stored
        now, anchor = datetime.now(UTC), _clock()
        credential.require_time(now)
        if (
            type(end_us) is not int
            or type(sdk_end_us) is not int
            or not anchor < sdk_end_us <= end_us
            or lease.mode != "execute"
            or credential.identity.principal_id != lease.actor_id
            or credential.identity.workspace_id != lease.workspace_id
            or lease.expires_at > credential.expires_at
        ):
            raise ValueError("Coding original witness/lease/operation bounds differ")
        authority = contexts._authority
        if (
            contexts._factory is not factory
            or contexts._retriever.factory is not factory
            or authority.management is not management
            or management.artifacts.factory is not factory
            or management.artifacts.blobs is not contexts._retriever.blobs
            or authority.recipe != input_recipe
            or (
                authority.policy.workflow_name,
                authority.policy.workflow_version,
                authority.policy.model_profile,
            )
            != ("company.coding.v1", "v1", "engineering")
        ):
            raise ValueError("Coding concrete C authority/factory/protected source graph differs")
        self._factory, self._management, self._contexts = factory, management, contexts
        self._evidence, self._resolver, self._estimator = evidence, resolver, input_estimator
        # Constructor above checks this concrete leaf; retain its original owner graph.
        self._source_blobs = contexts._retriever.blobs
        self._recipe = ModelInputRecipe.model_validate_json(input_recipe.model_dump_json())
        self._lease = ExecutionLease.model_validate_json(lease.model_dump_json())
        self._credential = credential
        self._resources = tuple(
            ResourceRevision.model_validate_json(row.model_dump_json()) for row in resources
        )
        limit = min(lease.expires_at, credential.expires_at)
        self._end_us = min(
            end_us, stored.read_end_us, anchor + (limit - now) // timedelta(microseconds=1)
        )
        self._sdk_end_us = min(sdk_end_us, self._end_us - (end_us - sdk_end_us))
        self._used, self._stopped = False, False
        self._clients: list[GovernedModelClient] = []
        self._reads: list[asyncio.Task[ModelEvidence]] = []
        self._first_error: BaseException | None = None
        self._objects = (
            factory,
            management,
            contexts,
            evidence,
            resolver,
            input_estimator,
            credential,
            contexts._authority,
            contexts._retriever,
            contexts._retriever.blobs,
            prepared_store,
            stored,
        )
        self._pins = self._values()
        self._current()

    @property
    def evidence(self) -> FileModelEvidenceStore:
        return self._evidence

    @property
    def management(self) -> ManagementExecutionServices:
        return self._management

    @property
    def lease(self) -> ExecutionLease:
        return self._lease

    def _values(self) -> tuple[object, ...]:
        return (
            canonical_sha256(self._management.catalog),
            self._recipe,
            self._lease,
            self._resources,
            self._credential.identity,
            self._credential.issued_at,
            self._credential.expires_at,
            self._end_us,
            self._sdk_end_us,
        )

    def _current(self) -> None:
        if (
            any(
                a is not b
                for a, b in zip(
                    self._objects,
                    (
                        self._factory,
                        self._management,
                        self._contexts,
                        self._evidence,
                        self._resolver,
                        self._estimator,
                        self._credential,
                        self._contexts._authority,
                        self._contexts._retriever,
                        self._contexts._retriever.blobs,
                        self._prepared_store,
                        self._stored,
                    ),
                    strict=True,
                )
            )
            or self._values() != self._pins
        ):
            raise ValueError("Coding original runtime composition changed")
        if self._stopped or _clock() >= self._end_us:
            raise TimeoutError("Original coding operation was stopped or expired")
        self._credential.require_time(datetime.now(UTC))
        self._prepared_store.require_loaded(
            self._stored, self._credential, self._lease, end_us=self._end_us
        )

    def request_stop(self) -> None:
        """Deny new issue/adoption; never cancel the actual issued SDK/SQL/FS resources."""
        self._stopped = True
        self._prepared_store.request_stop()
        for client in self._clients:
            client.request_stop()

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        """Retain original clients, source blobs and actual protected read leaves."""
        return tuple(
            dict.fromkeys(
                (
                    *self._evidence.pending_owners(),
                    *self._prepared_store.pending_owners(),
                    *self._source_blobs.pending_owners(),
                    *(
                        cast(asyncio.Task[object], read)
                        for read in self._reads
                        if not read.done() or read.cancelled()
                    ),
                    *(task for client in self._clients for task in client.pending_owners()),
                )
            )
        )

    def _client(self, prepared: PreparedCodingRequest) -> GovernedModelClient:
        registry = self._management.catalog.models
        require_coding_registry(prepared, registry)
        if (
            prepared.input_recipe != self._recipe
            or self._estimator.estimate(prepared.request, registry, self._recipe)
            != prepared.input_estimate
        ):
            raise ValueError("Coding runtime differs from its reviewed full-input preparation")
        check = BrainModelContextCheck(
            self._contexts,
            prepared.context,
            prepared.scope,
            self._credential.identity,
            prepared.request,
            self._recipe,
            self._lease,
            allowed_classification=prepared.request.data_classification,
        )
        original = CodingIntentCheck(check, prepared, registry=registry)
        coding = StoredCodingIntent(
            NexusCodingModelIntentCheck(original, self._credential),
            self._prepared_store,
            self._stored,
        )
        coding.validate_time(datetime.now(UTC))
        gate = PersistentModelCallAuthorizer(
            self._factory,
            self._lease,
            self._credential.identity,
            registry,
            resources=self._resources,
            input_estimator=self._estimator,
            input_recipe=self._recipe,
            allowed_classification=prepared.request.data_classification,
            evidence_store=self._evidence,
            additional_before_intent=coding,
            management=self._management,
            model_observations=self._management.catalog.model_observations,
        )
        return GovernedModelClient(
            registry,
            self._resolver,
            gate,
            self._management.execution_store(self._factory),
            self._lease,
            self._credential.identity,
            model_observations=self._management.catalog.model_observations,
            end_us=self._end_us,
            sdk_end_us=self._sdk_end_us,
        )

    async def request_once(
        self, prepared: PreparedCodingRequest, *, now: datetime
    ) -> CodingAttempt:
        """Issue at most once; known successful content remains historical under original refs."""
        if self._used or self._stopped:
            raise ValueError("A consumer permits only one coding request")
        self._used = True
        self._current()
        prepared = PreparedCodingRequest.model_validate_json(
            prepared.model_dump_json(by_alias=True)
        )
        client = self._client(prepared)
        self._clients.append(client)
        try:
            governed = await client.request_once(prepared.request, now=now)
        except BaseException as first:
            self._first_error = self._first_error or first
            self.request_stop()
            first.__dict__["_nexus_coding_pending"] = self.pending_owners()
            raise
        if not _successful(governed):
            return CodingAttempt(governed=governed, candidate=None, denial="model_outcome")
        try:
            self._current()
        except (ValueError, TimeoutError) as first:
            self._first_error = self._first_error or first
            return CodingAttempt(governed=governed, candidate=None, denial="evidence_unavailable")
        recorded = governed.recorded
        assert recorded is not None
        read = asyncio.create_task(self._evidence.load(recorded.artifact))
        self._reads.append(read)
        read.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            async with asyncio.timeout(max(0, self._end_us - _clock()) / 1_000_000):
                saved = await asyncio.shield(read)
            self._current()
        except asyncio.CancelledError as first:
            self._first_error = self._first_error or first
            self.request_stop()
            error = CodingReadCancelledError(governed, read, first)
            error.__dict__["_nexus_coding_pending"] = self.pending_owners()
            raise error from None
        except (ValueError, OSError, TimeoutError) as first:
            self._first_error = self._first_error or first
            return CodingAttempt(governed=governed, candidate=None, denial="evidence_unavailable")
        try:
            if not self._matches(prepared, governed, saved):
                return CodingAttempt(governed=governed, candidate=None, denial="evidence_mismatch")
        except ValueError as first:
            self._first_error = self._first_error or first
            return CodingAttempt(governed=governed, candidate=None, denial="evidence_mismatch")
        try:
            assert saved.result.structured_json is not None
            content = CodeChangeContent.model_validate_json(saved.result.structured_json)
            originals = require_coding_sources(prepared.binding, prepared.context, prepared.sources)
            validate_code_change(
                content, prepared.binding, manifest=prepared.context.manifest, originals=originals
            )
        except ValueError as first:
            self._first_error = self._first_error or first
            return CodingAttempt(governed=governed, candidate=None, denial="invalid_content")
        assert recorded.receipt_id is not None
        result = CodingAttempt(
            governed=governed,
            candidate=CodingCandidate(
                binding=prepared.binding,
                manifest=prepared.context.manifest,
                request_id=prepared.request.request_id,
                action_id=prepared.request.action_id,
                request_sha256=prepared.request_sha256,
                action_proposal_sha256=saved.action_hash,
                content=content,
                artifact=recorded.artifact,
                receipt_id=recorded.receipt_id,
            ),
            denial=None,
            stop_required=False,
        )
        try:
            self._current()  # Final complete typed construction cannot cross the original cutoff.
        except (ValueError, TimeoutError) as first:
            self._first_error = self._first_error or first
            return CodingAttempt(governed=governed, candidate=None, denial="evidence_unavailable")
        return result

    def _matches(
        self, prepared: PreparedCodingRequest, governed: GovernedModelResult, saved: ModelEvidence
    ) -> bool:
        saved.require_binding()
        recorded, call = governed.recorded, prepared.request
        model = require_coding_registry(prepared, self._management.catalog.models)
        return (
            recorded is not None
            and saved.model.price is not None
            and saved.result.usage is not None
            and saved.request == call
            and saved.request_hash == request_hash(call) == prepared.request_sha256
            and saved.result == governed.provider_result
            and saved.recipe == prepared.input_recipe == self._recipe
            and saved.input_estimate == prepared.input_estimate
            and saved.model == model
            and (saved.registry_revision, saved.price_version)
            == (call.registry_revision, call.price_version)
            and recorded.artifact.company_id == call.company_id
            and recorded.artifact.artifact_id == uuid5(call.action_id, str(call.request_id))
            and recorded.artifact.revision == "model-result-envelope-v1"
            and recorded.receipt_id == uuid5(call.action_id, "model-receipt-v1")
            and recorded.actual_usd
            == reconcile_cost(
                saved.model.price, saved.result.usage, now=saved.source_event_at
            ).amount_usd
        )


def _successful(result: GovernedModelResult) -> bool:
    provider, recorded = result.provider_result, result.recorded
    return (
        provider.status == "response"
        and provider.billing == "known"
        and provider.structured_json is not None
        and not provider.tool_calls
        and result.recording_status == "recorded"
        and result.recording_error is None
        and result.ledger_billing == "known"
        and result.release_status == "released"
        and result.release_error is None
        and not result.stop_required
        and recorded is not None
        and recorded.billing == "known"
        and recorded.actual_usd is not None
        and recorded.receipt_id is not None
        and not recorded.stop_required
    )
