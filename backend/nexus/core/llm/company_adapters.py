"""One governed SDK request at a time; raw usage completeness precedes reconciliation."""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, datetime
from threading import Event
from typing import cast

import httpx2
import structlog

from nexus.company.management.model_observations import (
    ModelEligibilityObservation,
    effective_model_registration,
)
from nexus.core.llm.company_adapter_contracts import (
    CompanyModelRequest,
    CompanyModelResult,
    EndpointResolver,
    ModelCallAuthorizer,
    ModelRequestCancelledError,
    ServerEndpoint,
)
from nexus.core.llm.company_adapter_sdk import outputs, request_model, sdk_model
from nexus.core.llm.company_eligibility import (
    BeforeModelSdk,
    eligibility_provenance,
    validated_observations,
)
from nexus.core.llm.company_input_bounds import require_model_input_bounds
from nexus.core.llm.company_pricing import CostQuote, quote_cost, reconcile_cost
from nexus.core.llm.company_registry import ModelRegistration, ModelRegistry
from nexus.core.llm.company_wire_usage import WireObserver

logger = structlog.get_logger()


def _registration(
    registry: ModelRegistry,
    request: CompanyModelRequest,
    now: datetime,
    observations: tuple[ModelEligibilityObservation, ...] = (),
) -> ModelRegistration:
    if now.utcoffset() is None:
        raise ValueError("provider clock must be timezone-aware")
    if (registry.company_id, registry.revision, registry.pricebook_version) != (
        request.company_id,
        request.registry_revision,
        request.price_version,
    ):
        raise ValueError("request belongs to another catalog/company/price revision")
    row = next((row for row in registry.models if row.registry_id == request.registry_id), None)
    if row is None or not row.enabled or request.data_classification not in row.allowed_data:
        raise ValueError("model/data policy is unavailable")
    row = effective_model_registration(registry, observations, row)
    required = (
        {"text"}
        | ({"tools"} if request.tools else set())
        | ({"structured_output"} if request.output_schema else set())
    )
    require_model_input_bounds(row, request.bounds)
    if not required <= row.capabilities or (
        request.bounds.input_bound_kind is not None and request.tools
    ):
        raise ValueError("model request exceeds catalog capabilities/context/output")
    if (row.provider, row.api_family) not in {
        ("openai", "openai_responses"),
        ("google", "google_generate_content"),
    }:
        raise ValueError("unsupported explicit provider/API family")
    if row.health.status != "healthy" or not row.health.checked_at <= now < row.health.expires_at:
        raise ValueError("model health observation is unavailable")
    return row


class CompanyModelAdapters:
    """Require a trusted durable attempt claimant and operator-owned endpoint resolver.

    Root runtime must consume persistent attempt counters/authority/cost before
    returning a claim. Offline fixtures do not prove that gate or vendor billing.
    No request/result has a key, URL, SDK client or client authorization permit.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        resolver: EndpointResolver,
        authorizer: ModelCallAuthorizer,
        *,
        model_observations: tuple[ModelEligibilityObservation, ...] = (),
        before_sdk: BeforeModelSdk | None = None,
        operation_deadline: datetime | None = None,
        operation_end_us: int | None = None,
    ) -> None:
        if authorizer is None or resolver is None:
            raise ValueError("trusted server resolver and model authorizer are required")
        self._registry = ModelRegistry.model_validate_json(registry.model_dump_json())
        self._observations = validated_observations(self._registry, model_observations)
        if self._observations and before_sdk is None:
            raise ValueError("Observed model calls require a trusted pre-SDK current intent check")
        self._before_sdk = before_sdk
        self._resolver, self._authorizer = resolver, authorizer
        if operation_deadline is not None and operation_deadline.utcoffset() is None:
            raise ValueError("Original model operation deadline must be timezone-aware")
        self._operation_deadline = operation_deadline
        if operation_end_us is not None and (
            type(operation_end_us) is not int or operation_end_us <= time.monotonic_ns() // 1000
        ):
            raise ValueError("Original model operation needs a finite current end")
        self._operation_end_us = operation_end_us
        self._stopped = Event()
        self._owners: list[asyncio.Task[object]] = []

    def request_stop(self) -> None:
        """Deny future issuance; already-issued SDK/context cleanup remains owned."""
        self._stopped.set()

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        """Actual SDK/context-close tasks; finished late values confer no authority."""
        return tuple(task for task in self._owners if not task.done() or task.cancelled())

    async def request_once(
        self, request: CompanyModelRequest, *, now: datetime
    ) -> CompanyModelResult:
        """One model request only; failed/unknown usage must retain its existing cost hold."""
        request = CompanyModelRequest.model_validate_json(request.model_dump_json(by_alias=True))
        try:
            if self._stopped.is_set():
                raise ValueError("Model operation stopped before issuance")
            if (
                self._operation_end_us is not None
                and time.monotonic_ns() // 1000 >= self._operation_end_us
            ):
                raise ValueError("Original model operation expired before issuance")
            row = _registration(self._registry, request, now, self._observations)
            original = next(
                item for item in self._registry.models if item.registry_id == row.registry_id
            )
            provenance = eligibility_provenance(self._registry, self._observations, original)
            quote = quote_cost(row.price, request.bounds, now=now)
            endpoint = await self._endpoint(row)
            if self._stopped.is_set():
                raise ValueError("Model operation stopped before claim")
            if (
                self._operation_end_us is not None
                and time.monotonic_ns() // 1000 >= self._operation_end_us
            ):
                raise ValueError("Original model operation expired before claim")
            claim = await self._authorizer.claim(request, quote)
            claim.require_request(request, quote)
        except (ValueError, KeyError) as exc:
            logger.warning(
                "company_model_claim_denied",
                task_id=str(request.task_id),
                trace_id=str(request.trace_id),
                error_type=type(exc).__name__,
            )
            return CompanyModelResult(
                request_id=request.request_id,
                status="denied",
                billing="not_issued",
                error_code="authorization_or_configuration",
            )
        # Only this post-claim exchange is shielded. The latch is checked after
        # the real current pre-SDK gate, so a stopped chain cannot issue later.
        loop = asyncio.get_running_loop()
        anchor = loop.time()
        remaining = endpoint.timeout_seconds
        if self._operation_deadline is not None:
            remaining = min(
                remaining, (self._operation_deadline - datetime.now(UTC)).total_seconds()
            )
        if self._operation_end_us is not None:
            remaining = min(
                remaining, (self._operation_end_us - time.monotonic_ns() // 1000) / 1_000_000
            )
        if remaining <= 0:
            self.request_stop()
            return CompanyModelResult(
                request_id=request.request_id,
                status="failed",
                billing="unknown",
                error_code="original_model_operation_expired",
            )
        end = anchor + max(0, remaining)
        task = asyncio.create_task(
            _invoke(
                request,
                row,
                endpoint,
                now,
                quote=quote,
                before_sdk=self._before_sdk,
                eligibility_sha256=provenance.sha256 if provenance else None,
                stopped=self._stopped,
            )
        )
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        first: asyncio.CancelledError | None = None
        while True:
            try:
                async with asyncio.timeout_at(end):
                    result = await asyncio.shield(task)
                break
            except asyncio.CancelledError as error:
                self.request_stop()
                first = first or error
                if not task.cancelled():
                    continue
                result = _cancelled(request)
                break
            except TimeoutError:
                self.request_stop()
                result = (
                    _cancelled(request)
                    if first
                    else CompanyModelResult(
                        request_id=request.request_id,
                        status="failed",
                        billing="unknown",
                        error_code="sdk_resources_unresolved",
                    )
                )
                break
        if first is not None or result.status == "cancelled":
            cancelled = ModelRequestCancelledError(result)
            cancelled.__dict__["_nexus_model_first"] = first
            cancelled.__dict__["_nexus_model_pending"] = self.pending_owners()
            raise cancelled from None
        return result

    async def _endpoint(self, row: ModelRegistration) -> ServerEndpoint:
        endpoint = await self._resolver.resolve(row.endpoint_id)
        if (endpoint.endpoint_id, endpoint.provider, endpoint.api_family) != (
            row.endpoint_id,
            row.provider,
            row.api_family,
        ):
            raise ValueError("server endpoint binding disagrees with catalog")
        url = httpx2.URL(endpoint.base_url)
        if (
            url.scheme != "https"
            or url.userinfo
            or url.query
            or url.fragment
            or not endpoint.api_key.get_secret_value()
        ):
            raise ValueError("server provider config must be explicit and credential-safe")
        if not math.isfinite(endpoint.timeout_seconds) or not 0 < endpoint.timeout_seconds <= 120:
            raise ValueError("provider timeout must be finite and bounded")
        return endpoint


async def _invoke(
    request: CompanyModelRequest,
    row: ModelRegistration,
    endpoint: ServerEndpoint,
    now: datetime,
    *,
    quote: CostQuote,
    before_sdk: BeforeModelSdk | None = None,
    eligibility_sha256: str | None = None,
    stopped: Event,
) -> CompanyModelResult:
    observer = WireObserver(row)
    try:
        if stopped.is_set():
            return _cancelled(request)
        async with sdk_model(row, endpoint, observer) as model:
            if stopped.is_set():
                raise asyncio.CancelledError("Model stopped before current SDK check")
            if before_sdk is not None:
                now = await before_sdk(request, quote, eligibility_sha256)
            if stopped.is_set():
                raise asyncio.CancelledError("Model stopped before SDK issuance")
            response = await request_model(model, request)
        if stopped.is_set():
            return _cancelled(request, observer)
        if observer.usage is None:
            raise ValueError("validated wire usage is absent")
        reconcile_cost(row.price, observer.usage, now=now)
        if (
            observer.usage.output_tokens > request.bounds.max_output_tokens
            or observer.usage.input_tokens > request.bounds.input_tokens
        ):
            raise ValueError("reported usage exceeds the declared bounds")
        text, structured, tools = outputs(response, request, endpoint.api_key.get_secret_value())
        return CompanyModelResult(
            request_id=request.request_id,
            status="response",
            billing="known",
            usage=observer.usage,
            text=text,
            structured_json=structured,
            tool_calls=tools,
        )
    except asyncio.CancelledError:
        return _cancelled(request)
    except Exception as exc:
        return _failure(request, observer, exc)


def _cancelled(
    request: CompanyModelRequest, observer: WireObserver | None = None
) -> CompanyModelResult:
    known = observer is not None and observer.usage is not None and observer.error_code is None
    return CompanyModelResult(
        request_id=request.request_id,
        status="cancelled",
        billing="known" if known else "unknown",
        usage=observer.usage if known and observer else None,
        error_code="cancelled",
    )


def _failure(
    request: CompanyModelRequest, observer: WireObserver, exc: Exception
) -> CompanyModelResult:
    known = observer.usage is not None and observer.error_code is None
    logger.warning(
        "company_model_request_failed",
        task_id=str(request.task_id),
        trace_id=str(request.trace_id),
        error_type=type(exc).__name__,
        billing="known" if known else "unknown",
    )
    return CompanyModelResult(
        request_id=request.request_id,
        status="failed",
        billing="known" if known else "unknown",
        usage=observer.usage if known else None,
        error_code=observer.error_code
        or ("timeout" if isinstance(exc, httpx2.TimeoutException) else "request_or_output_failure"),
    )
