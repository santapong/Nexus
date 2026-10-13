"""Actual offline PydanticAI request capture; no remote clients or golden fixture reads."""

from __future__ import annotations

import hashlib
from typing import Literal, Self

from pydantic import model_validator
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from nexus.company.brain.base import SHA256, ValueContract
from nexus.company.brain.context import AssembledContext


class SDKCapture(ValueContract):
    provider: Literal["pydanticai.function.offline.v1"] = "pydanticai.function.offline.v1"
    request_json: str
    request_sha256: SHA256
    system_text: str
    input_text: str
    captured_request_count: Literal[1] = 1
    response_text: str
    response_messages_json: str
    response_sha256: SHA256

    @model_validator(mode="after")
    def exact_actual_message(self) -> Self:
        messages = ModelMessagesTypeAdapter.validate_json(self.request_json)
        if self.request_sha256 != hashlib.sha256(self.request_json.encode()).hexdigest():
            raise ValueError("SDK message hash mismatch")
        if any(not isinstance(message, ModelRequest) for message in messages):
            raise ValueError("Capture must contain only the actual pre-response SDK request")
        if any(
            not isinstance(part, (SystemPromptPart, UserPromptPart))
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        ):
            raise ValueError("Read-only fixture capture cannot contain tool/history payloads")
        systems = tuple(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, SystemPromptPart)
        )
        users = tuple(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        if systems != (self.system_text,) or users != (self.input_text,):
            raise ValueError("SDK message parts disagree with the captured Brain text")
        responses = ModelMessagesTypeAdapter.validate_json(self.response_messages_json)
        texts = tuple(
            part.content
            for message in responses
            if isinstance(message, ModelResponse)
            for part in message.parts
            if isinstance(part, TextPart)
        )
        if (
            texts != (self.response_text,)
            or self.response_sha256
            != hashlib.sha256(self.response_messages_json.encode()).hexdigest()
        ):
            raise ValueError("SDK output does not match its exact captured response")
        return self


async def capture_context(
    context: AssembledContext, *, response_text: str = "offline capture acknowledged"
) -> SDKCapture:
    """Drive the real pinned Agent request path and retain its actual serialized messages."""
    requests: list[list[ModelMessage]] = []

    async def capture(messages: list[ModelMessage], _: AgentInfo) -> ModelResponse:
        requests.append(list(messages))
        return ModelResponse(parts=[TextPart(response_text)])

    agent = Agent(FunctionModel(capture), system_prompt=context.system_text)
    result = await agent.run(context.input_text)
    if len(requests) != 1:
        raise AssertionError("Offline context must issue exactly one captured SDK request")
    raw = ModelMessagesTypeAdapter.dump_json(requests[0])
    wire = raw.decode()
    # Compare decoded actual parts, not an inclusion-manifest approximation.
    systems = tuple(
        part.content
        for message in requests[0]
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, SystemPromptPart)
    )
    users = tuple(
        part.content
        for message in requests[0]
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    )
    if systems != (context.system_text,) or users != (context.input_text,):
        raise AssertionError("SDK request differs from the revalidated rendered Brain context")
    return SDKCapture(
        request_json=wire,
        request_sha256=hashlib.sha256(raw).hexdigest(),
        system_text=context.system_text,
        input_text=context.input_text,
        response_text=result.output,
        response_messages_json=ModelMessagesTypeAdapter.dump_json(result.all_messages()).decode(),
        response_sha256=hashlib.sha256(
            ModelMessagesTypeAdapter.dump_json(result.all_messages())
        ).hexdigest(),
    )
