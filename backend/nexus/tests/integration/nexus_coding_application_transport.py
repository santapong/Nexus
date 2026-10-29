"""Explicit synthetic eligibility/prices and actual pinned SDK MockTransport only."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    ExitStack,
    asynccontextmanager,
)
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid5

import httpx2
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model

from nexus.company.brain.base import ValueContract
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_content import CodeChangeContent, validate_code_change
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.planning_content import PlanningContent, PlanningTask
from nexus.core.llm import company_adapters
from nexus.core.llm.company_adapter_contracts import (
    CompanyModelRequest,
    JsonSchemaDocument,
    ServerEndpoint,
)
from nexus.core.llm.company_endpoints import SettingsEndpointResolver
from nexus.core.llm.company_input_bounds import model_input_ceiling
from nexus.core.llm.company_pricing import CostQuote, TokenBounds, quote_cost
from nexus.core.llm.company_registry import ModelRegistration, ModelRegistry, Profile
from nexus.core.llm.company_routing import ModelPolicy, route_models
from nexus.core.llm.company_wire_usage import WireObserver
from nexus.execution.coding_context import CODING_REQUEST_CAPABILITIES
from nexus.execution.coding_owner_reads import CodingInputReview
from nexus.execution.planning_owner_reads import PlanningInputReview
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer
from nexus.harness.model_authorizer_contracts import InputEstimate, ModelInputRecipe
from nexus.harness.model_input_estimator import (
    RECIPE_ID,
    RECIPE_REVISION,
    FullContextInputEstimator,
    input_conformance_reference,
)
from nexus.tests.unit.test_company_provider_conformance import response

PROFILE: dict[str, Profile] = {
    "planner": "reasoning",
    "coder": "engineering",
    "strategy": "reasoning",
    "presentation": "routine",
    "support": "routine",
}


def recipe(profile: Profile) -> ModelInputRecipe:
    """Actual full-input source estimator, with explicit synthetic quality metadata."""
    return ModelInputRecipe(
        recipe_id=RECIPE_ID,
        revision=RECIPE_REVISION,
        profile=profile,
        minimum_score=Decimal("0.8"),
        evaluation_suite_version="synthetic-nexus-component",
        conformance_reference=input_conformance_reference(),
    )


def priced_catalog(catalog: PlanAdmissionCatalog) -> PlanAdmissionCatalog:
    """NEW catalog only: freeze all five observations before r1; never widen held fixtures."""
    now = datetime.now(UTC)
    models = []
    for original in catalog.models.models:
        assert original.price is not None
        data = original.model_dump()
        data.update(
            max_output_tokens=8192,
            health=original.health.model_copy(
                update={"checked_at": now, "expires_at": now + timedelta(hours=1)}
            ),
            evaluations=tuple(
                row.model_copy(update={"evaluated_at": now, "expires_at": now + timedelta(hours=1)})
                for row in original.evaluations
            ),
            price=original.price.model_copy(
                update={
                    "as_of": now.date(),
                    "valid_from": now,
                    "valid_until": now + timedelta(hours=1),
                    "source_reference": "synthetic:NOT-VENDOR-PRICE:nexus-c-application-v1",
                    "input_per_million": Decimal("0.01"),
                    "output_per_million": Decimal("0.02"),
                    "cached_input_per_million": None,
                    "cache_semantics": "none",
                }
            ),
        )
        models.append(type(original).model_validate(data))
    registry = ModelRegistry.model_validate(catalog.models.model_dump() | {"models": tuple(models)})
    digest = canonical_sha256(registry)
    admission = catalog.nexus_coding_admission
    assert admission is not None
    return PlanAdmissionCatalog.model_validate(
        catalog.model_dump()
        | {
            "models": registry,
            "native_profiles": tuple(
                row.model_copy(update={"registry_sha256": digest})
                for row in catalog.native_profiles
            ),
            "notification_profiles": tuple(
                row.model_copy(update={"registry_sha256": digest})
                for row in catalog.notification_profiles
            ),
            "nexus_coding_admission": admission.model_copy(update={"registry_sha256": digest}),
        }
    )


class UpfrontReservation(ValueContract):
    """Descriptive original maximum input proof, never action/hold/SDK permission."""

    role: str
    registry_id: str
    bounds: TokenBounds
    estimate: InputEstimate
    quote: CostQuote


def upfront_quotes(catalog: PlanAdmissionCatalog) -> tuple[UpfrontReservation, ...]:
    """Real full-estimator and ordinary eligibility/price quotes for ALL five before r1.

    The financial ceiling is independent of the later prompt text; this synthetic
    preparation call issues no permit. Actual pending requests are independently
    assembled and estimated again through production under current native facts.
    """
    admission = catalog.nexus_coding_admission
    assert admission is not None
    schema = JsonSchemaDocument(
        schema_json='{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":false}'
    )
    quotes = []
    for slot in admission.slots[:5]:
        row = next(
            row for row in catalog.models.models if slot.tool.resource == "model:" + row.registry_id
        )
        bound = slot.child.binding
        selected = recipe(PROFILE[slot.role])
        output = 8192 if slot.role == "planner" else 1024
        call = CompanyModelRequest(
            company_id=admission.company_id,
            task_id=bound.task_id,
            trace_id=bound.trace_id,
            actor_id=bound.actor_id,
            action_id=uuid5(bound.run_id, "upfront-quote-only"),
            attempt_id=uuid5(bound.run_id, "upfront-quote-only"),
            request_id=uuid5(bound.run_id, "upfront-request-only"),
            registry_id=row.registry_id,
            registry_revision=catalog.models.revision,
            price_version=catalog.models.pricebook_version,
            data_classification="internal",
            bounds=TokenBounds(
                input_tokens=model_input_ceiling(row),
                max_output_tokens=output,
                input_bound_kind="model_input_ceiling_v1",
            ),
            input_text="Financial full-input reservation only; no model or execution authority.",
            output_schema=schema,
        )
        estimate = FullContextInputEstimator(catalog.models, selected).estimate(
            call, catalog.models, selected
        )
        assert estimate.whole_request and estimate.total_tokens == model_input_ceiling(row)
        routed = route_models(
            catalog.models,
            ModelPolicy(
                company_id=admission.company_id,
                task_id=bound.task_id,
                trace_id=bound.trace_id,
                policy_version="nexus-c-application-v1",
                pricebook_version=catalog.models.pricebook_version,
                profile=selected.profile,
                allowed_models=frozenset({row.registry_id}),
                allowed_providers=frozenset({row.provider}),
                allowed_api_families=frozenset({row.api_family}),
                data_classification="internal",
                required_capabilities=(
                    CODING_REQUEST_CAPABILITIES if slot.role == "coder" else frozenset()
                ),
                minimum_score=selected.minimum_score,
                evaluation_suite_version=selected.evaluation_suite_version,
                available_usd=slot.child.allocation_usd,
                token_bounds=call.bounds,
                max_fallbacks=0,
                remaining_model_requests=1,
            ),
            now=datetime.now(UTC),
            model_observations=catalog.model_observations,
        ).primary
        assert routed.quote == quote_cost(row.price, call.bounds, now=datetime.now(UTC))
        assert routed.quote.amount_usd <= slot.child.allocation_usd == Decimal("0.1")
        quotes.append(
            UpfrontReservation(
                role=slot.role,
                registry_id=row.registry_id,
                bounds=call.bounds,
                estimate=estimate,
                quote=routed.quote,
            )
        )
    assert (
        sum((row.quote.amount_usd for row in quotes), Decimal(0))
        <= admission.procedure.allocation_usd
    )
    return tuple(quotes)


def planning_output(admission: NexusCodingAdmission, review: PlanningInputReview) -> str:
    evidence = review.prepared.context.manifest.inclusions[0].handle.evidence_id
    return PlanningContent(
        tasks=tuple(
            PlanningTask(
                key=slot.role,
                title="Nexus " + slot.role + " remains subject to native gates",
                description="Review the committed Nexus evidence in this fixed bounded role.",
                acceptance=slot.work.acceptance,
                depends_on=tuple(
                    other.role
                    for other in admission.slots[1:]
                    if other.work.task_id in slot.work.depends_on
                ),
                evidence_ids=(evidence,),
            )
            for slot in admission.slots[1:]
        ),
        questions=("Local SDKMock protocol data does not qualify model quality or a builder.",),
    ).model_dump_json()


def coding_output(review: CodingInputReview, original: bytes) -> str:
    """Real patch syntax/application against the exact committed existing file only."""
    path = review.prepared.binding.allowed_write_paths[0]
    first = original.decode().splitlines(keepends=True)[0]
    assert first.endswith("\n")
    patch_text = (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1,2 @@\n {first}+\n"
    )
    content = CodeChangeContent(
        patch=patch_text,
        explanation="Nexus SDKMock acceptance inserts a blank line after the committed heading.",
        questions=("This protocol-only patch still requires independent E/EV execution.",),
        evidence_ids=tuple(
            ref.evidence_id for row in review.prepared.sources for ref in row.evidence
        ),
    )
    validate_code_change(
        content,
        review.prepared.binding,
        manifest=review.prepared.context.manifest,
        originals={path: original},
    )
    return content.model_dump_json()


@dataclass
class Transport:
    """Only exact official pinned endpoint SDK requests, one POST, no network fallback."""

    provider: str
    content: str
    schema_comment: str
    posts: list[str] = field(default_factory=list)
    lookups: int = 0

    @staticmethod
    def _timing(stage: str) -> None:
        """Emit only stage and monotonic time; never include a request or credential."""
        sys.stderr.write(f"NEXUS_C_TIMING={stage}:{time.monotonic_ns() // 1000}\n")
        sys.stderr.flush()

    def wire(self, request: httpx2.Request) -> httpx2.Response:
        self._timing("transport_enter")
        assert request.method == "POST" and not self.posts
        assert request.url.host == (
            "api.openai.com" if self.provider == "openai" else "generativelanguage.googleapis.com"
        )

        def comments(value: object) -> list[str]:
            if isinstance(value, dict):
                return ([value["$comment"]] if "$comment" in value else []) + [
                    item for nested in value.values() for item in comments(nested)
                ]
            if isinstance(value, list):
                return [item for nested in value for item in comments(nested)]
            return []

        assert self.schema_comment in comments(json.loads(request.content))
        self.posts.append(hashlib.sha256(request.content).hexdigest())
        self._timing("transport_validated")
        body = response(self.provider)
        if self.provider == "openai":
            body["model"] = "gpt-5.4-mini-2026-03-17"
            body["output"] = [
                {
                    "id": "nexus-application",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": self.content, "annotations": []}],
                }
            ]
        else:
            body["modelVersion"] = "gemini-3.5-flash-lite"
            body["candidates"] = [
                {
                    "content": {"role": "model", "parts": [{"text": self.content}]},
                    "finishReason": "STOP",
                }
            ]
        return httpx2.Response(200, json=body)

    def install(self) -> AbstractContextManager[object]:
        """Keep real server resolution/key lookup; inject only offline SDK transport."""
        original = SettingsEndpointResolver.resolve
        adapter_module = cast(Any, company_adapters)
        original_sdk = cast(
            Callable[
                [ModelRegistration, ServerEndpoint, WireObserver],
                AbstractAsyncContextManager[Model],
            ],
            adapter_module.sdk_model,
        )
        original_request = cast(
            Callable[[Model, CompanyModelRequest], Awaitable[ModelResponse]],
            adapter_module.request_model,
        )
        original_pre_sdk = PersistentModelCallAuthorizer.revalidate_before_sdk

        @asynccontextmanager
        async def traced_sdk(
            row: ModelRegistration, endpoint: ServerEndpoint, observer: WireObserver
        ) -> AsyncIterator[Model]:
            self._timing("sdk_context_enter")
            try:
                async with original_sdk(row, endpoint, observer) as model:
                    self._timing("sdk_context_ready")
                    yield model
            finally:
                self._timing("sdk_context_exit")

        async def traced_pre_sdk(
            gate: PersistentModelCallAuthorizer,
            request: CompanyModelRequest,
            quote: CostQuote,
            eligibility_sha256: str | None,
        ) -> datetime:
            self._timing("pre_sdk_enter")
            try:
                return await original_pre_sdk(gate, request, quote, eligibility_sha256)
            finally:
                self._timing("pre_sdk_exit")

        async def traced_request(model: Model, request: CompanyModelRequest) -> ModelResponse:
            self._timing("model_request_enter")
            try:
                return await original_request(model, request)
            finally:
                self._timing("model_request_exit")

        async def resolve(resolver: SettingsEndpointResolver, endpoint_id: str) -> ServerEndpoint:
            endpoint = await original(resolver, endpoint_id)
            assert endpoint.provider == self.provider
            self.lookups += 1
            assert self.lookups == 1
            return replace(endpoint, transport=httpx2.MockTransport(self.wire))

        stack = ExitStack()
        stack.enter_context(patch.object(SettingsEndpointResolver, "resolve", resolve))
        stack.enter_context(patch.object(company_adapters, "sdk_model", traced_sdk))
        stack.enter_context(patch.object(company_adapters, "request_model", traced_request))
        stack.enter_context(
            patch.object(PersistentModelCallAuthorizer, "revalidate_before_sdk", traced_pre_sdk)
        )
        return stack
