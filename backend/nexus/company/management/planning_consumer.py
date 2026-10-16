"""One registered governed model request produces historical content, never a formal plan."""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.contracts.actions import ResourceRevision
from nexus.company.management.model_observations import ModelEligibilityObservation
from nexus.company.management.planning_content import (
    PlanningAttempt,
    PlanningCandidate,
    PlanningContent,
)
from nexus.company.management.planning_intent import PlanningIntentCheck, PreparedPlanningRequest
from nexus.core.llm.company_adapter_contracts import EndpointResolver, request_hash
from nexus.core.llm.company_pricing import reconcile_cost
from nexus.core.llm.company_registry import DataClassification, ModelRegistry
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer
from nexus.harness.model_authorizer_contracts import InputEstimator, ModelInputRecipe
from nexus.harness.model_client import GovernedModelClient
from nexus.harness.model_client_contracts import GovernedModelCancelledError, GovernedModelResult
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence


class PlanningReadCancelledError(GovernedModelCancelledError):
    """Keep the actual read owner and recorded outcome; cancellation cannot adopt content."""

    def __init__(self, governed: GovernedModelResult, read: asyncio.Task[ModelEvidence]) -> None:
        self.evidence_read = read
        super().__init__(governed)


class RegisteredPlanningConsumer:
    """Server-owned concrete composition; no client/result protocol can substitute a gate.

    Registration, full-request estimation and exact action approval precede use.
    Successful content remains historical under its frozen goal/head references.
    A later formal mapper MUST perform current governance and CAS again.
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        registry: ModelRegistry,
        resolver: EndpointResolver,
        management: ManagementExecutionServices,
        contexts: PersistentContextAssembler,
        evidence: FileModelEvidenceStore,
        input_estimator: InputEstimator,
        input_recipe: ModelInputRecipe,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        *,
        resources: tuple[ResourceRevision, ...],
        allowed_classification: DataClassification,
        model_observations: tuple[ModelEligibilityObservation, ...] = (),
    ) -> None:
        if (
            not isinstance(contexts, PersistentContextAssembler)
            or not isinstance(evidence, FileModelEvidenceStore)
            or not isinstance(management, ManagementExecutionServices)
        ):
            raise ValueError(
                "Planning requires concrete server context, evidence and management services"
            )
        self._factory, self._resolver = factory, resolver
        self._registry = ModelRegistry.model_validate_json(registry.model_dump_json())
        self._management, self._contexts, self._evidence = management, contexts, evidence
        self._estimator = input_estimator
        self._recipe = ModelInputRecipe.model_validate_json(input_recipe.model_dump_json())
        self._lease = ExecutionLease.model_validate_json(lease.model_dump_json())
        self._identity = VerifiedIdentity.model_validate(identity.model_dump())
        self._resources = tuple(
            ResourceRevision.model_validate(row.model_dump()) for row in resources
        )
        self._classification = allowed_classification
        self._observations = tuple(model_observations)
        self._used = False
        self._reads: list[asyncio.Task[ModelEvidence]] = []

    @property
    def evidence(self) -> FileModelEvidenceStore:
        return self._evidence

    @property
    def management(self) -> ManagementExecutionServices:
        return self._management

    @property
    def lease(self) -> ExecutionLease:
        return self._lease

    @property
    def evidence_reads(self) -> tuple[asyncio.Task[ModelEvidence], ...]:
        """Actual retained owners for resource settlement; completion grants no authority."""
        return tuple(self._reads)

    def _client(self, prepared: PreparedPlanningRequest) -> GovernedModelClient:
        if (
            prepared.input_recipe != self._recipe
            or prepared.request.data_classification != self._classification
            or prepared.scope.workspace_id != self._identity.workspace_id
        ):
            raise ValueError("Planning runtime differs from pre-approval preparation")
        context_check = BrainModelContextCheck(
            self._contexts,
            prepared.context,
            prepared.scope,
            self._identity,
            prepared.request,
            self._recipe,
            self._lease,
            allowed_classification=self._classification,
        )
        gate = PersistentModelCallAuthorizer(
            self._factory,
            self._lease,
            self._identity,
            self._registry,
            resources=self._resources,
            input_estimator=self._estimator,
            input_recipe=self._recipe,
            allowed_classification=self._classification,
            evidence_store=self._evidence,
            additional_before_intent=PlanningIntentCheck(context_check, prepared),
            management=self._management,
            model_observations=self._observations,
        )
        return GovernedModelClient(
            self._registry,
            self._resolver,
            gate,
            self._management.execution_store(self._factory),
            self._lease,
            self._identity,
            model_observations=self._observations,
        )

    async def request_once(
        self, prepared: PreparedPlanningRequest, *, now: datetime
    ) -> PlanningAttempt:
        if self._used:
            raise ValueError("A consumer permits only one planning request")
        self._used = True  # No await separates the one-shot check and consumption.
        prepared = PreparedPlanningRequest.model_validate_json(
            prepared.model_dump_json(by_alias=True)
        )
        client = self._client(prepared)
        governed = await client.request_once(prepared.request, now=now)
        if not _successful(governed):
            return PlanningAttempt(governed=governed, candidate=None, denial="model_outcome")
        recorded = governed.recorded
        assert recorded is not None
        read = asyncio.create_task(self._evidence.load(recorded.artifact))
        self._reads.append(read)
        try:
            saved = await asyncio.shield(read)
        except asyncio.CancelledError:
            # Keep the real thread-backed read owner; never cancel it or promote its late value.
            read.add_done_callback(_consume_read)
            raise PlanningReadCancelledError(governed, read) from None
        except (ValueError, OSError):
            return PlanningAttempt(governed=governed, candidate=None, denial="evidence_unavailable")
        try:
            matches = self._matches(prepared, governed, saved)
        except ValueError:
            matches = False
        if not matches:
            return PlanningAttempt(governed=governed, candidate=None, denial="evidence_mismatch")
        try:
            assert saved.result.structured_json is not None
            content = PlanningContent.model_validate_json(saved.result.structured_json)
            content.require_evidence(
                tuple(row.handle.evidence_id for row in prepared.context.manifest.inclusions)
            )
        except ValueError:
            return PlanningAttempt(governed=governed, candidate=None, denial="invalid_content")
        assert recorded.receipt_id is not None
        return PlanningAttempt(
            governed=governed,
            candidate=PlanningCandidate(
                binding=prepared.binding,
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

    def _matches(
        self, prepared: PreparedPlanningRequest, governed: GovernedModelResult, saved: ModelEvidence
    ) -> bool:
        saved.require_binding()
        recorded, call = governed.recorded, prepared.request
        if recorded is None or saved.result.usage is None or saved.model.price is None:
            return False
        model = next(
            (row for row in self._registry.models if row.registry_id == call.registry_id), None
        )
        return (
            saved.request == call
            and saved.request_hash == request_hash(call) == prepared.request_sha256
            and saved.result == governed.provider_result
            and saved.recipe == prepared.input_recipe == self._recipe
            and saved.model == model
            and (saved.registry_revision, saved.price_version)
            == (self._registry.revision, self._registry.pricebook_version)
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


def _consume_read(read: asyncio.Task[ModelEvidence]) -> None:
    if not read.cancelled():
        read.exception()
