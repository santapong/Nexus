"""Dated actual pinned offline SDK conformance; no private inputs/provider/company call permit."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings

from nexus.company.management.canonical import canonical_sha256
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, JsonSchemaDocument
from nexus.core.llm.company_adapter_sdk import outputs, request_model
from nexus.core.llm.company_pricing import TokenBounds
from nexus.tests.local_stockflow_packet import ROOT, write_private
from nexus.tests.stockflow_packet_contracts import PreparedState


class OfflineOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["offline_fixture_only"]
    sequence: int = Field(ge=1, le=1, strict=True)


class ObservedTestModel(TestModel):
    requests: int = 0
    sent: list[ModelMessage]
    reply: ModelResponse | None = None

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        self.requests += 1
        self.sent = messages
        self.reply = await super().request(messages, model_settings, model_request_parameters)
        return self.reply


async def qualify() -> None:
    state = PreparedState.model_validate_json(
        await asyncio.to_thread((ROOT / "native-state.json").read_bytes)
    )
    registration = state.catalog.models.models[0]
    assert registration.provider == registration.api_family == "test"
    schema = JsonSchemaDocument(schema_json=json.dumps(OfflineOutput.model_json_schema()))
    call = CompanyModelRequest(
        company_id=state.spec.job.company_id,
        task_id=uuid4(),
        trace_id=uuid4(),
        actor_id=uuid4(),
        action_id=uuid4(),
        attempt_id=uuid4(),
        request_id=uuid4(),
        registry_id=registration.registry_id,
        registry_revision=state.catalog.models.revision,
        price_version=state.catalog.models.pricebook_version,
        data_classification="internal",
        bounds=TokenBounds(input_tokens=512, max_output_tokens=64),
        input_text="Generate one offline fixture object; no business or delivery statement.",
        output_schema=schema,
    )
    call = call.model_copy(update={"output_schema": None})
    sdk = ObservedTestModel(
        call_tools=[],
        model_name=registration.model_id,
        custom_output_text="Synthetic Nexus readiness draft; offline test only.",
    )
    versions = {
        name: importlib.metadata.version(name) for name in ("pydantic-ai-slim", "pydantic", "dbos")
    }
    async with asyncio.timeout(10):
        response = await request_model(sdk, call)
    _text, structured, proposals = outputs(response, call, "never-real-conformance-marker")
    if _text is None or not 0 < len(_text) <= 2000 or structured is not None:
        raise ValueError("Routine plain-string interface changed")
    sent = ModelMessagesTypeAdapter.dump_json(sdk.sent)
    reply = ModelMessagesTypeAdapter.dump_json([response])
    criteria = {
        "exact_provider_model": sdk.system == registration.provider
        and response.model_name == registration.model_id,
        "one_actual_request": sdk.requests == 1,
        "no_tools_or_proposals": not proposals
        and sdk.last_model_request_parameters is not None
        and not sdk.last_model_request_parameters.function_tools,
        "routine_text_schema_actual_output": isinstance(_text, str) and len(_text) <= 2000,
        "actual_usage_present": response.usage.input_tokens > 0
        and response.usage.output_tokens > 0,
        "schema_parameter_identity": sdk.last_model_request_parameters is not None
        and sdk.last_model_request_parameters.output_object is None
        and sdk.last_model_request_parameters.output_mode == "text",
    }
    if not all(criteria.values()):
        raise ValueError("Offline same-binding SDK qualification failed")
    observed = datetime.now(UTC)
    artifact = {
        "observation_revision": "builder-offline-model-refresh-20261014-v1",
        "company_id": str(state.spec.job.company_id),
        "original_registry_revision": state.catalog.models.revision,
        "registry_id": registration.registry_id,
        "registration_sha256": canonical_sha256(registration),
        "original_model_registration": registration.model_dump(mode="json"),
        "profile": "routine",
        "observed_at": observed.isoformat(),
        "model": "TestModel",
        "provider": registration.provider,
        "model_id": registration.model_id,
        "endpoint_id": registration.endpoint_id,
        "api_family": registration.api_family,
        "versions": versions,
        "actual_request_sha256": hashlib.sha256(sent).hexdigest(),
        "actual_response_sha256": hashlib.sha256(reply).hexdigest(),
        "actual_request_messages": json.loads(sent),
        "actual_response_messages": json.loads(reply),
        "output_schema": {"type": "string"},
        "output_schema_sha256": hashlib.sha256(b'{"type":"string"}').hexdigest(),
        "requests": sdk.requests,
        "tool_proposals": len(proposals),
        "criteria": criteria,
        "criteria_passed": sum(criteria.values()),
        "criteria_total": len(criteria),
        "score": "1",
        "usage": response.usage.__dict__,
        "decoded_output": _text,
        "limitations": [
            "offline_TestModel_conformance_only",
            "no_live_model_quality",
            "no_company_execution_or_spend_authority",
        ],
    }
    await asyncio.to_thread(
        write_private,
        ROOT / "model-requalification-sdk.json",
        json.dumps(artifact, indent=2).encode(),
    )


if __name__ == "__main__":
    asyncio.run(qualify())
