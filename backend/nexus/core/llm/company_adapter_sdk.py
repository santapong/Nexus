"""Exact SDK model construction and bounded output mapping, with no tool execution."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from google.genai.types import HttpRetryOptions
from openai import AsyncOpenAI
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.output import OutputObjectDefinition
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import ToolDefinition

from nexus.core.llm.company_adapter_contracts import (
    CompanyModelRequest,
    ServerEndpoint,
    ToolProposal,
)
from nexus.core.llm.company_registry import ModelRegistration
from nexus.core.llm.company_wire_usage import WireObserver


def _require_single_google_response(response: httpx2.Response) -> None:
    """Fail before the pinned SDK can follow its automatic continuation loop."""
    if not 200 <= response.status_code < 300:
        return
    body = response.json()  # WireObserver already read and bounded the complete body.
    if not isinstance(body, dict) or not isinstance(body.get("candidates", []), list):
        raise ValueError("Google response shape is unavailable")
    for candidate in body.get("candidates", []):
        if (
            not isinstance(candidate, dict)
            or any(
                candidate.get(key) == "CONTINUATION" for key in ("finishReason", "finish_reason")
            )
            or any(
                candidate.get(key) not in (None, "")
                for key in ("continuationToken", "continuation_token")
            )
        ):
            raise ValueError("Google continuation requires a separate governed request")


def parameters(request: CompanyModelRequest) -> ModelRequestParameters:
    """Thaw validated canonical JSON only at the third-party SDK schema boundary."""
    # The SDK accepts arbitrary JSON Schema; the canonical document was validated.
    tools = [
        ToolDefinition(
            name=t.name,
            description=t.description,
            strict=True,
            parameters_json_schema=json.loads(t.parameters.document),
        )
        for t in request.tools
    ]
    output = (
        OutputObjectDefinition(
            json_schema=json.loads(request.output_schema.document),
            name="company_output",
            strict=True,
        )
        if request.output_schema
        else None
    )
    return ModelRequestParameters(
        function_tools=tools, output_mode="native" if output else "text", output_object=output
    )


@asynccontextmanager
async def sdk_model(
    row: ModelRegistration, endpoint: ServerEndpoint, observer: WireObserver
) -> AsyncIterator[Model]:
    """Yield one explicit API model with provider retries disabled and no environment fallback."""

    async def observe(response: httpx2.Response) -> None:
        await observer.observe(response)
        if row.provider == "google":
            _require_single_google_response(response)

    async with httpx2.AsyncClient(
        transport=endpoint.transport,
        timeout=endpoint.timeout_seconds,
        event_hooks={"response": [observe]},
    ) as http:
        profile: ModelProfile = {
            "supports_tools": "tools" in row.capabilities,
            "supports_json_schema_output": "structured_output" in row.capabilities,
        }
        if row.provider == "openai":
            client = AsyncOpenAI(
                api_key=endpoint.api_key.get_secret_value(),
                base_url=endpoint.base_url,
                max_retries=0,
                http_client=http,
            )
            try:
                yield OpenAIResponsesModel(
                    row.model_id, provider=OpenAIProvider(openai_client=client), profile=profile
                )
            finally:
                await client.close()
        else:
            provider = GoogleProvider(
                api_key=endpoint.api_key.get_secret_value(),
                base_url=endpoint.base_url,
                http_client=http,
                retry_options=HttpRetryOptions(attempts=1),
            )
            try:
                yield GoogleModel(row.model_id, provider=provider, profile=profile)
            finally:
                await provider.client.aio.aclose()
                await asyncio.to_thread(provider.client.close)


async def request_model(model: Model, request: CompanyModelRequest) -> ModelResponse:
    """Issue exactly one non-streaming Model.request; no Agent.run or retry prompt loop."""
    parts = [UserPromptPart(content=request.input_text)]
    messages: list[ModelMessage] = (
        [ModelRequest(parts=[SystemPromptPart(content=request.system_text)])]
        if request.system_text
        else []
    )
    messages.append(ModelRequest(parts=parts))
    return await model.request(
        messages, {"max_tokens": request.bounds.max_output_tokens}, parameters(request)
    )


def outputs(
    response: ModelResponse, request: CompanyModelRequest, secret: str
) -> tuple[str | None, str | None, tuple[ToolProposal, ...]]:
    """Return visible output/proposals only, never hidden reasoning text or credentials."""
    texts: list[str] = []
    proposals: list[ToolProposal] = []
    tools = {tool.name: tool for tool in request.tools}
    for part in response.parts:
        if isinstance(part, TextPart):
            texts.append(part.content)
        elif isinstance(part, ToolCallPart):
            if part.tool_name not in tools:
                raise ValueError("model suggested an unregistered tool")
            args = part.args if isinstance(part.args, str) else json.dumps(part.args)
            encoded = tools[part.tool_name].parameters.validate_output(args)
            proposals.append(
                ToolProposal(name=part.tool_name, call_id=part.tool_call_id, arguments_json=encoded)
            )
        elif not isinstance(part, ThinkingPart):
            raise ValueError("unsupported provider response part")
    text = "".join(texts) or None
    if (
        (text is not None and (len(text.encode()) > 100_000 or secret in text))
        or any(secret in p.arguments_json or secret in (p.call_id or "") for p in proposals)
        or len(proposals) > 20
    ):
        raise ValueError("model output exceeds allowance or contains credential material")
    structured = (
        request.output_schema.validate_output(text or "") if request.output_schema else None
    )
    if response.finish_reason not in {None, "stop", "tool_call"} or (not text and not proposals):
        raise ValueError("provider response is incomplete or empty")
    return text, structured, tuple(proposals)
