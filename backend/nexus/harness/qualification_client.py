"""One qualification-only SDK request and evidence-before-ledger settlement; no promotion."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Literal, cast
from uuid import uuid5

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.core.llm.company_adapter_contracts import (
    CompanyModelRequest,
    CompanyModelResult,
    EndpointResolver,
    ServerEndpoint,
    request_hash,
)
from nexus.core.llm.company_adapter_sdk import outputs, request_model, sdk_model
from nexus.core.llm.company_endpoints import ServerEndpointBinding
from nexus.core.llm.company_pricing import reconcile_cost
from nexus.core.llm.company_wire_usage import WireObserver
from nexus.core.llm.qualification_contracts import QualificationRecipe, capture_sdk_pins
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import EffectRecord, ExecutionLease
from nexus.harness.qualification_evidence import (
    FileQualificationEvidenceStore,
    QualificationEvidence,
    current,
)
from nexus.harness.qualification_intent import QualificationIntentCheck


class QualificationRunResult(BaseModel):
    """Actual SDK/ledger observations only; neither model eligibility nor profile quality."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    provider_result: CompanyModelResult
    evidence: ArtifactRef | None = None
    record: EffectRecord | None = None
    actual_usd: Decimal | None = None
    recording_error: Literal["evidence_or_ledger_failed", "original_end_expired"] | None = None
    caller_interrupted: bool = False
    profile_quality_evaluated: Literal[False] = False
    stop_required: Literal[True] = True


class QualificationClient:
    """Concrete original composition; caller owns lease release and actual pending resources."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        effects: EffectStore,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        recipe: QualificationRecipe,
        request: CompanyModelRequest,
        resolver: EndpointResolver,
        evidence_store: FileQualificationEvidenceStore,
        *,
        end_us: int,
    ) -> None:
        if resolver is None or type(evidence_store) is not FileQualificationEvidenceStore:
            raise ValueError(
                "Qualification needs explicit resolver and concrete protected evidence"
            )
        current(end_us)
        self._check = QualificationIntentCheck(factory, effects, lease, identity, recipe, request)
        self._factory, self._effects, self._resolver = factory, effects, resolver
        self._lease = ExecutionLease.model_validate_json(lease.model_dump_json(by_alias=True))
        self._identity = VerifiedIdentity.model_validate(identity.model_dump())
        self._recipe = QualificationRecipe.model_validate_json(
            recipe.model_dump_json(by_alias=True)
        )
        self._request = CompanyModelRequest.model_validate_json(
            request.model_dump_json(by_alias=True)
        )
        self._store, self._root = evidence_store, evidence_store._root
        self._end, self._used = end_us, False
        self._aborted = self._caller_interrupted = False
        self._sdk_error: asyncio.CancelledError | None = None
        self._owners: list[asyncio.Task[object]] = []
        self._bound_dependencies = (factory, effects, resolver, evidence_store, self._check)
        self._bound_values = (self._lease, self._identity, self._recipe, self._request, end_us)

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        original_store = self._bound_dependencies[3]
        return tuple(
            dict.fromkeys(
                (
                    *original_store.pending_owners(),
                    *(task for task in self._owners if not task.done() or task.cancelled()),
                )
            )
        )

    def _current(self) -> None:
        current(self._end)
        self._check.require_composition()
        if (
            any(
                actual is not original
                for actual, original in zip(
                    (self._factory, self._effects, self._resolver, self._store, self._check),
                    self._bound_dependencies,
                    strict=True,
                )
            )
            or (self._lease, self._identity, self._recipe, self._request, self._end)
            != self._bound_values
            or self._effects._factory is not self._factory
            or self._store._root != self._root
        ):
            raise ValueError("Qualification original native/evidence composition changed")

    async def _sdk_pins(self) -> None:
        self._current()
        task = asyncio.create_task(capture_sdk_pins())
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda value: None if value.cancelled() else value.exception())
        try:
            async with asyncio.timeout(max(0, self._end - clock_us()) / 1_000_000):
                actual = await asyncio.shield(task)
            self._current()
            if actual != self._recipe.sdk_pins:
                raise ValueError("Qualification actual SDK sources/versions differ from approval")
        except BaseException as error:
            error.__dict__["_nexus_qualification_pending"] = self.pending_owners()
            raise

    def _denied(self) -> QualificationRunResult:
        return QualificationRunResult(
            provider_result=CompanyModelResult(
                request_id=self._request.request_id,
                status="denied",
                billing="not_issued",
                error_code="qualification_unissued",
            )
        )

    async def request_once(self) -> QualificationRunResult:
        if self._used:
            return self._denied()
        self._used = True  # No await between one-use check and consumption.
        self._current()
        await self._sdk_pins()
        endpoint = await self._resolver.resolve(self._recipe.target.endpoint_id)
        self._current()
        ServerEndpointBinding(
            endpoint.endpoint_id,
            endpoint.provider,
            endpoint.api_family,
            endpoint.base_url,
            endpoint.timeout_seconds,
        )
        row = self._recipe.target
        if (endpoint.endpoint_id, endpoint.provider, endpoint.api_family) != (
            row.endpoint_id,
            row.provider,
            row.api_family,
        ) or not endpoint.api_key.get_secret_value():
            raise ValueError("Qualification endpoint differs from its exact original target")
        start = await self._effects.begin(
            self._lease,
            self._identity,
            self._request.action_id,
            kind="model_requests",
            before_intent=self._check,
        )
        self._current()
        if not start.permit_external_call:
            return self._denied()  # An existing intent can never issue another request.
        result, first = await self._owned_exchange(endpoint, start.record)
        if first is None:
            return await self._finish(start.record, result)
        self._caller_interrupted = True
        try:
            outcome = await self._finish(start.record, result)
        except BaseException as secondary:
            first.__dict__["_nexus_qualification_result"] = QualificationRunResult(
                provider_result=result,
                caller_interrupted=True,
                recording_error="evidence_or_ledger_failed",
            )
            first.__dict__["_nexus_qualification_secondary"] = type(secondary).__name__
        else:
            first.__dict__["_nexus_qualification_result"] = outcome
        first.__dict__["_nexus_qualification_pending"] = self.pending_owners()
        raise first

    async def _owned_exchange(
        self,
        endpoint: ServerEndpoint,
        intent: EffectRecord,
    ) -> tuple[CompanyModelResult, asyncio.CancelledError | None]:
        # One actual SDK/context-close owner survives repeated caller cancellation.
        task = asyncio.create_task(self._exchange(endpoint, intent))
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda value: None if value.cancelled() else value.exception())
        first: asyncio.CancelledError | None = None
        while True:
            try:
                async with asyncio.timeout(max(0, self._end - clock_us()) / 1_000_000):
                    result = await asyncio.shield(task)
                return result, first or self._sdk_error
            except asyncio.CancelledError as error:
                self._aborted = True
                first = first or error
                if not task.cancelled():
                    continue
            except Exception:
                self._aborted = True
            # No fresh cleanup window, task cancellation, late adoption or second call.
            return CompanyModelResult(
                request_id=self._request.request_id,
                status="cancelled" if first else "failed",
                billing="unknown",
                error_code="qualification_sdk_unresolved",
            ), first

    async def _exchange(self, endpoint: ServerEndpoint, intent: EffectRecord) -> CompanyModelResult:
        row = self._recipe.target
        observer = WireObserver(row)
        try:
            if self._aborted:
                raise asyncio.CancelledError("Qualification caller stopped before SDK")
            async with sdk_model(row, endpoint, observer) as model:
                await self._sdk_pins()  # Actual source reads stay outside native transactions.
                if self._aborted:
                    raise asyncio.CancelledError("Qualification caller stopped before SDK")
                await self._check.revalidate_before_sdk()
                self._current()
                if self._aborted:
                    raise asyncio.CancelledError("Qualification caller stopped before SDK")
                async with asyncio.timeout(max(0, self._end - clock_us()) / 1_000_000):
                    response = await request_model(model, self._request)
                self._current()
            self._current()
            if observer.usage is None:
                raise ValueError("Qualification complete wire usage is unavailable")
            reconcile_cost(row.price, observer.usage, now=intent.created_at)
            if (
                observer.usage.input_tokens > self._recipe.financial_input_ceiling
                or observer.usage.output_tokens > self._request.bounds.max_output_tokens
            ):
                raise ValueError("Qualification observed usage exceeded the approved request")
            text, structured, proposals = outputs(
                response, self._request, endpoint.api_key.get_secret_value()
            )
            if proposals:
                raise ValueError("Qualification cannot return executable tool proposals")
            self._current()
            return CompanyModelResult(
                request_id=self._request.request_id,
                status="response",
                billing="known",
                usage=observer.usage,
                text=text,
                structured_json=structured,
            )
        except asyncio.CancelledError as original:
            self._sdk_error = original
            return CompanyModelResult(
                request_id=self._request.request_id,
                status="cancelled",
                billing="unknown",
                error_code="qualification_cancelled",
            )
        except Exception:
            known = observer.usage is not None and observer.error_code is None
            return CompanyModelResult(
                request_id=self._request.request_id,
                status="failed",
                billing="known" if known else "unknown",
                usage=observer.usage if known else None,
                error_code=observer.error_code or "qualification_request_failed",
            )

    async def _finish(
        self, intent: EffectRecord, result: CompanyModelResult
    ) -> QualificationRunResult:
        task = asyncio.create_task(self._record(intent, result))
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda value: None if value.cancelled() else value.exception())
        value: QualificationRunResult | None = None
        try:
            async with asyncio.timeout(max(0, self._end - clock_us()) / 1_000_000):
                value = await asyncio.shield(task)
            self._current()
            return value
        except asyncio.CancelledError as original:
            self._caller_interrupted = True
            original.__dict__["_nexus_qualification_pending"] = self.pending_owners()
            original.__dict__["_nexus_qualification_result"] = value or QualificationRunResult(
                provider_result=result,
                caller_interrupted=self._caller_interrupted,
                recording_error="evidence_or_ledger_failed",
            )
            raise
        except Exception:
            if value is not None:
                return value.model_copy(update={"recording_error": "original_end_expired"})
            return QualificationRunResult(
                provider_result=result,
                caller_interrupted=self._caller_interrupted,
                recording_error="original_end_expired",
            )

    async def _record(
        self, intent: EffectRecord, result: CompanyModelResult
    ) -> QualificationRunResult:
        reference, recorded, actual = None, None, None
        try:
            self._current()
            checked = await self._check.observation_time()
            self._current()
            evidence = QualificationEvidence(
                recipe=self._recipe,
                request=self._request,
                request_sha256=request_hash(self._request),
                intent=intent,
                provider_result=result,
                owner_id=self._identity.principal_id,
                checked_at=checked,
                caller_interrupted_at_capture=self._caller_interrupted,
            )
            reference = await self._store.save(evidence, end_us=self._end)
            saved = await self._store.load(reference, end_us=self._end)
            if saved != evidence:
                raise ValueError("Qualification protected readback differs")
            self._current()
            actual = (
                reconcile_cost(
                    self._recipe.target.price, result.usage, now=intent.created_at
                ).amount_usd
                if result.usage is not None
                else None
            )
            outcome: Literal["succeeded", "failed", "outcome_unknown"] = (
                "outcome_unknown"
                if result.billing == "unknown"
                else "succeeded"
                if result.status == "response" and not self._caller_interrupted
                else "failed"
            )
            receipt = ActionReceipt(
                company_id=self._request.company_id,
                receipt_id=uuid5(self._request.action_id, "qualification-receipt-v1"),
                action_id=self._request.action_id,
                task_id=self._request.task_id,
                trace_id=self._request.trace_id,
                proposal_hash=intent.proposal_hash,
                outcome=outcome,
                recorded_at=checked,
                artifacts=(reference,),
            )
            self._current()
            recorded = await self._effects.record_receipt(
                self._lease, self._identity, receipt, actual_usd=actual, blocked=outcome == "failed"
            )
            self._current()
            return QualificationRunResult(
                provider_result=result,
                evidence=reference,
                record=recorded,
                actual_usd=actual,
                caller_interrupted=self._caller_interrupted,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return QualificationRunResult(
                provider_result=result,
                evidence=reference,
                record=recorded,
                actual_usd=actual,
                caller_interrupted=self._caller_interrupted,
                recording_error="evidence_or_ledger_failed",
            )
