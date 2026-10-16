"""Persistent single Model.request gate and provider-result evidence, without live activation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID, uuid5

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ResourceRevision
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.model_observations import ModelEligibilityObservation
from nexus.core.llm.company_adapter_contracts import (
    AuthorizedModelAttempt,
    CompanyModelRequest,
    CompanyModelResult,
    request_hash,
)
from nexus.core.llm.company_eligibility import validated_observations
from nexus.core.llm.company_pricing import CostQuote, ModelContract, reconcile_cost
from nexus.core.llm.company_registry import DataClassification, ModelRegistry
from nexus.execution.effect_store import EffectStore
from nexus.execution.effect_support import effect_row
from nexus.execution.intent_checks import BeforeIntentCheck, CompositeBeforeIntentCheck
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    mark_unknown_intents,
    require_lease,
    runtime_transaction,
)
from nexus.harness.model_authorizer_contracts import InputEstimator, ModelInputRecipe
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence, ModelEvidenceStore
from nexus.harness.model_intent import ModelIntentCheck
from nexus.harness.model_managed_deadlines import require_managed_gateway_configuration
from nexus.harness.model_pre_sdk import (
    ClaimedModelRequest,
    ModelPreSdkServices,
    revalidate_before_sdk,
)


class RecordedModelOutcome(ModelContract):
    """Issued result evidence/billing only; successful response is not business acceptance."""

    artifact: ArtifactRef
    billing: Literal["known", "unknown"]
    actual_usd: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    stop_required: bool
    receipt_id: UUID | None = None


class PersistentModelCallAuthorizer:
    """Server composition only: no user estimator, secrets, URLs or implicit fallback."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        registry: ModelRegistry,
        *,
        resources: tuple[ResourceRevision, ...],
        input_estimator: InputEstimator,
        input_recipe: ModelInputRecipe,
        allowed_classification: DataClassification,
        evidence_store: ModelEvidenceStore,
        additional_before_intent: BeforeIntentCheck | None = None,
        management: ManagementExecutionServices | None = None,
        model_observations: tuple[ModelEligibilityObservation, ...] = (),
    ) -> None:
        self._lease = ExecutionLease.model_validate_json(lease.model_dump_json())
        self._identity = VerifiedIdentity.model_validate(identity.model_dump())
        if lease.mode != "execute" or (identity.principal_id, identity.workspace_id) != (
            lease.actor_id,
            lease.workspace_id,
        ):
            raise ValueError("Model calls require the registered actor's execute lease")
        self._factory = factory
        self._effects = (
            management.effect_store(factory) if management is not None else EffectStore(factory)
        )
        self._registry = ModelRegistry.model_validate_json(registry.model_dump_json())
        self._observations = validated_observations(self._registry, model_observations)
        require_managed_gateway_configuration(management, self._registry, self._observations)
        self._resources = tuple(
            ResourceRevision.model_validate(row.model_dump()) for row in resources
        )
        self._estimator = input_estimator
        self._recipe = ModelInputRecipe.model_validate_json(input_recipe.model_dump_json())
        self._classification, self._evidence = allowed_classification, evidence_store
        self._additional_check = additional_before_intent
        self._pre_sdk = ModelPreSdkServices(
            self._factory,
            self._effects,
            self._lease,
            self._identity,
            self._resources,
            self._additional_check,
            management,
        )
        self._claims: dict[UUID, ClaimedModelRequest] = {}
        self._owners: list[asyncio.Task[object]] = []

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        """Retain actual native calls and the concrete protected store's filesystem owners."""
        return tuple(
            dict.fromkeys(
                (
                    *(task for task in self._owners if not task.done() or task.cancelled()),
                    *(
                        self._evidence.pending_owners()
                        if isinstance(self._evidence, FileModelEvidenceStore)
                        else ()
                    ),
                )
            )
        )

    async def _owned[T](self, call: Awaitable[T]) -> T:
        self._owners[:] = [task for task in self._owners if not task.done() or task.cancelled()]
        task = asyncio.ensure_future(call)
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            return await asyncio.shield(task)
        except BaseException as first:
            first.__dict__["_nexus_model_pending"] = self.pending_owners()
            raise

    def require_eligibility_configuration(
        self, registry: ModelRegistry, observations: tuple[ModelEligibilityObservation, ...]
    ) -> None:
        """Prevent adapter/client/server plan paths from choosing different dated observations."""
        if (
            registry != self._registry
            or validated_observations(registry, observations) != self._observations
        ):
            raise ValueError("Client model eligibility differs from its actual persistent gate")

    async def revalidate_before_sdk(
        self, request: CompanyModelRequest, quote: CostQuote, eligibility_sha256: str | None
    ) -> datetime:
        """Revalidate one already-committed request; this method issues no new permit or attempt."""
        claimed = self._claims.get(request.request_id)
        if claimed is None:
            raise ValueError("Pre-SDK model request has no native claim from this gate")
        return await self._owned(
            revalidate_before_sdk(
                self._pre_sdk,
                claimed.check,
                claimed.effect,
                request,
                quote,
                eligibility_sha256,
            )
        )

    async def claim(self, request: CompanyModelRequest, quote: CostQuote) -> AuthorizedModelAttempt:
        """Commit one lifetime attempt/intent before one caller-owned SDK invocation."""
        request = CompanyModelRequest.model_validate_json(request.model_dump_json(by_alias=True))
        quote = CostQuote.model_validate_json(quote.model_dump_json())
        check = ModelIntentCheck(
            request,
            quote,
            self._lease,
            self._registry,
            self._estimator,
            self._recipe,
            self._classification,
            model_observations=self._observations,
        )
        start = await self._owned(
            self._effects.begin(
                self._lease,
                self._identity,
                request.action_id,
                resources=self._resources,
                kind="model_requests",
                # Reject stale context early and recheck after input/model validation,
                # whose bounded work can cross an independently expiring read grant.
                before_intent=CompositeBeforeIntentCheck(
                    (self._additional_check, check, self._additional_check)
                )
                if self._additional_check is not None
                else check,
            )
        )
        if not start.permit_external_call or check.hold is None:
            raise ValueError("Model intent already exists; invocation cannot be repeated")
        self._claims[request.request_id] = ClaimedModelRequest(check, start.record)
        return AuthorizedModelAttempt(
            scope=lease_scope(self._lease),
            action_id=request.action_id,
            attempt_id=request.attempt_id,
            request_id=request.request_id,
            request_hash=request_hash(request),
            registry_id=request.registry_id,
            registry_revision=request.registry_revision,
            price_version=request.price_version,
            reserved_usd=check.hold.amount_usd,
        )

    async def record_result(
        self, request: CompanyModelRequest, result: CompanyModelResult
    ) -> RecordedModelOutcome:
        """Save actual server result first; unknown billing retains the original hold.

        This trusted callback belongs immediately after request_once (also on cancellation).
        It accepts no client artifact/receipt. Recovery of saved output by a different
        process requires a separately fenced reconciliation adapter; it never reissues.
        """
        request = CompanyModelRequest.model_validate_json(request.model_dump_json(by_alias=True))
        result = CompanyModelResult.model_validate_json(result.model_dump_json())
        claimed = self._claims.get(request.request_id)
        if (
            claimed is None
            or result.request_id != request.request_id
            or claimed.check.call != request
            or result.billing == "not_issued"
        ):
            raise ValueError("Result does not bind an issued request from this server gate")
        evidence = await self._owned(self._make_evidence(claimed, result))
        artifact = await self._evidence.save(evidence)
        saved = await self._evidence.load(artifact)
        if saved.model_dump(exclude={"checked_at"}) != evidence.model_dump(exclude={"checked_at"}):
            raise ValueError("Protected store returned evidence from another result")
        if result.billing == "unknown":
            await self._owned(self._mark_unknown(claimed))
            return RecordedModelOutcome(artifact=artifact, billing="unknown", stop_required=True)
        return await self._owned(self._record_known(saved, artifact))

    async def _make_evidence(
        self, claimed: ClaimedModelRequest, result: CompanyModelResult
    ) -> ModelEvidence:
        check = claimed.check
        if (
            check.model is None
            or check.estimate is None
            or check.billing_at is None
            or check.owner_id is None
        ):
            raise ValueError("Issued model request has no validated catalog/price/estimator")
        # Preserve an already-issued server result even if its actor/fence was
        # revoked during the SDK call. Receipt/cost mutation below still requires
        # fresh scope/principal/fencing; this clock read grants no work authority.
        async with self._factory() as session:
            now = await db_now(session)
        return ModelEvidence(
            request=check.call,
            request_hash=request_hash(check.call),
            action_hash=claimed.effect.proposal_hash,
            model=check.original_model or check.model,
            registry_revision=self._registry.revision,
            price_version=self._registry.pricebook_version,
            recipe=self._recipe,
            input_estimate=check.estimate,
            result=result,
            source_event_at=check.billing_at,
            checked_at=now,
            owner_id=check.owner_id,
            eligibility_provenance=check.eligibility_provenance,
        )

    async def _mark_unknown(self, claimed: ClaimedModelRequest) -> None:
        async with runtime_transaction(
            self._factory,
            lease_scope(self._lease),
            self._identity,
            allow_paused=True,
            allow_inactive=True,
        ) as (session, _, _):
            work = await execution_row(session, lease_scope(self._lease))
            require_lease(work, self._lease, await db_now(session))
            row = await effect_row(session, work, claimed.effect.action_id)
            if (
                row.state not in {"intent", "outcome_unknown"}
                or row.proposal_hash != claimed.effect.proposal_hash
            ):
                raise ValueError("Unknown result cannot change a known or foreign effect")
            await mark_unknown_intents(session, work, [row])
            work.state = "outcome_unknown"

    async def _record_known(
        self, evidence: ModelEvidence, artifact: ArtifactRef
    ) -> RecordedModelOutcome:
        result, request = evidence.result, evidence.request
        if result.usage is None:
            raise ValueError("Known billing requires complete validated usage")
        cost = reconcile_cost(
            evidence.model.price, result.usage, now=evidence.source_event_at
        ).amount_usd
        exceeded = (
            result.usage.input_tokens > request.bounds.input_tokens
            or result.usage.output_tokens > request.bounds.max_output_tokens
        )
        stop_required = result.status != "response" or exceeded
        receipt = ActionReceipt(
            company_id=request.company_id,
            receipt_id=uuid5(request.action_id, "model-receipt-v1"),
            action_id=request.action_id,
            task_id=request.task_id,
            trace_id=request.trace_id,
            proposal_hash=evidence.action_hash,
            recorded_at=evidence.checked_at,
            outcome="failed" if stop_required else "succeeded",
            artifacts=(artifact,),
        )
        await self._effects.record_receipt(
            self._lease, self._identity, receipt, actual_usd=cost, blocked=stop_required
        )
        return RecordedModelOutcome(
            artifact=artifact,
            billing="known",
            actual_usd=cost,
            stop_required=stop_required,
            receipt_id=receipt.receipt_id,
        )
