"""Immutable call/output contracts and trusted runtime dependencies, without client permits."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated, Literal, NoReturn, Protocol, Self, cast
from uuid import UUID

import httpx2
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import Field, SecretStr, StringConstraints, field_validator, model_validator
from referencing import Registry
from referencing.exceptions import NoSuchResource

from nexus.company.contracts.base import Name
from nexus.core.llm.company_pricing import CostQuote, ModelContract, TokenBounds, TokenUsage
from nexus.core.llm.company_registry import DataClassification
from nexus.harness.journal_contracts import LedgerScope

BoundText = Annotated[str, StringConstraints(min_length=1, max_length=100_000)]
BoundJson = Annotated[str, StringConstraints(min_length=1, max_length=65_536)]
ToolName = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]


def _no_retrieval(uri: str) -> NoReturn:
    raise NoSuchResource(uri)


class _RegistryFactory(Protocol):
    def __call__(self, *, retrieve: Callable[[str], NoReturn]) -> Registry: ...


# referencing uses attrs-generated constructors not exposed by its static stub.
_REGISTRY = cast(_RegistryFactory, Registry)


def _reject_constant(_: str) -> NoReturn:
    raise ValueError("non-finite constants are not JSON")


def _load_bounded(text: str) -> object:
    if len(text.encode()) > 65_536:
        raise ValueError("JSON byte allowance exceeded")
    depth, quoted, escaped = 0, False, False
    for character in text:
        if escaped:
            escaped = False
        elif quoted and character == "\\":
            escaped = True
        elif character == '"':
            quoted = not quoted
        elif not quoted and character in "[{":
            depth += 1
            if depth > 20:
                raise ValueError("JSON depth allowance exceeded before decoding")
        elif not quoted and character in "]}":
            depth -= 1
    return json.loads(text, parse_constant=_reject_constant)


def _check_references(root: object) -> None:
    pending: list[tuple[object, frozenset[str]]] = [(root, frozenset())]
    nodes = 0
    while pending:
        node, ancestry = pending.pop()
        nodes += 1
        if nodes > 2000:
            raise ValueError("expanded schema reference allowance exceeded")
        if isinstance(node, dict):
            for key, reference in node.items():
                if key in {"$ref", "$dynamicRef"}:
                    if not isinstance(reference, str) or reference in ancestry:
                        raise ValueError("cyclic schema references are unsupported")
                    target = root
                    try:
                        for part in reference[2:].split("/"):
                            part = part.replace("~1", "/").replace("~0", "~")
                            if not isinstance(target, dict):
                                raise KeyError(part)
                            target = target[part]
                    except (KeyError, TypeError) as exc:
                        raise ValueError("local schema reference is unavailable") from exc
                    pending.append((target, ancestry | {reference}))
            pending.extend((child, ancestry) for child in node.values())
        elif isinstance(node, list):
            pending.extend((child, ancestry) for child in node)


def _bound_json(
    value: object, *, schema: bool = False, depth: int = 0, counter: list[int] | None = None
) -> None:
    counter = counter if counter is not None else [0]
    counter[0] += 1
    if depth > 20 or counter[0] > 2000:
        raise ValueError("JSON structure exceeds bounded depth/node allowance")
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                schema
                and key in {"$ref", "$dynamicRef", "$id"}
                and (not isinstance(item, str) or not item.startswith("#/"))
            ):
                raise ValueError("only local JSON-pointer schema references are permitted")
            _bound_json(item, schema=schema, depth=depth + 1, counter=counter)
    elif isinstance(value, list):
        for item in value:
            _bound_json(item, schema=schema, depth=depth + 1, counter=counter)


class JsonSchemaDocument(ModelContract):
    """Bounded canonical schema text cannot mutate after authority hashing."""

    document: BoundJson = Field(alias="schema_json")

    @field_validator("document")
    @classmethod
    def validate_schema(cls, text: str) -> str:
        """Reject external retrieval and invalid schema before any billable request."""
        value = _load_bounded(text)
        if not isinstance(value, dict) or value.get("type") != "object":
            raise ValueError("company output/tool schemas must describe an object")
        _bound_json(value, schema=True)
        _check_references(value)
        try:
            Draft202012Validator.check_schema(value)
        except SchemaError as exc:
            raise ValueError("invalid company JSON schema") from exc
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def validate_output(self, text: str) -> str:
        """Check bounded JSON shape only; domain Pydantic validation remains required."""
        value = _load_bounded(text)
        _bound_json(value)
        Draft202012Validator(
            json.loads(self.document), registry=_REGISTRY(retrieve=_no_retrieval)
        ).validate(value)
        return json.dumps(value, sort_keys=True, separators=(",", ":"))


class ModelTool(ModelContract):
    """Function schema only; this is never an executable tool or hosted tool."""

    name: ToolName
    description: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    parameters: JsonSchemaDocument


class CompanyModelRequest(ModelContract):
    """One bounded server-authored SDK request, not a whole multi-call agent run."""

    company_id: UUID
    task_id: UUID
    trace_id: UUID
    actor_id: UUID
    action_id: UUID
    attempt_id: UUID
    request_id: UUID
    registry_id: Name
    registry_revision: Name
    price_version: Name
    data_classification: DataClassification
    bounds: TokenBounds
    input_text: BoundText
    system_text: BoundText | None = None
    tools: tuple[ModelTool, ...] = Field(default=(), max_length=20)
    output_schema: JsonSchemaDocument | None = None

    @model_validator(mode="after")
    def require_distinct_tools_and_positive_output(self) -> Self:
        """Prevent duplicate function bindings and unbounded/empty generation allowance."""
        if self.bounds.max_output_tokens < 1 or len({t.name for t in self.tools}) != len(
            self.tools
        ):
            raise ValueError("generation needs a positive cap and distinct tools")
        if (
            self.bounds.input_tokens < 1
            or len(self.input_text.encode()) + len((self.system_text or "").encode()) > 100_000
        ):
            raise ValueError("text input needs a positive bound and byte allowance")
        if self.tools and self.output_schema is not None:
            raise ValueError(
                "native output and function proposals need separately evaluated requests"
            )
        return self


def request_hash(request: CompanyModelRequest) -> str:
    """Bind authority to exact immutable inputs, schema versions and bounds."""
    payload = json.dumps(
        request.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class AuthorizedModelAttempt:
    """Trusted claim result, never a serialized/client supplied authorization permit."""

    scope: LedgerScope
    action_id: UUID
    attempt_id: UUID
    request_id: UUID
    request_hash: str
    registry_id: str
    registry_revision: str
    price_version: str
    reserved_usd: Decimal

    def require_request(self, request: CompanyModelRequest, quote: CostQuote) -> None:
        """Reject a claim for another request/scope/price or insufficient reservation."""
        expected = (
            request.company_id,
            request.task_id,
            request.trace_id,
            request.actor_id,
            request.action_id,
            request.attempt_id,
            request.request_id,
            request_hash(request),
            request.registry_id,
            request.registry_revision,
            request.price_version,
        )
        actual = (
            self.scope.company_id,
            self.scope.task_id,
            self.scope.trace_id,
            self.scope.principal_id,
            self.action_id,
            self.attempt_id,
            self.request_id,
            self.request_hash,
            self.registry_id,
            self.registry_revision,
            self.price_version,
        )
        if (
            actual != expected
            or not self.reserved_usd.is_finite()
            or self.reserved_usd < quote.amount_usd
        ):
            raise ValueError("trusted model claim does not bind this request/reservation")


class ModelCallAuthorizer(Protocol):
    """Root runtime must implement durable one-time counter/authority/reservation consumption."""

    async def claim(self, request: CompanyModelRequest, quote: CostQuote) -> AuthorizedModelAttempt:
        """Consume one exact logical request before wire I/O; failures/cancel still count."""
        ...


@dataclass(frozen=True, slots=True)
class ServerEndpoint:
    """Operator-resolved runtime config; absent from every request/result contract."""

    endpoint_id: str
    provider: str
    api_family: str
    base_url: str = field(repr=False)
    api_key: SecretStr = field(repr=False)
    transport: httpx2.AsyncBaseTransport | None = field(default=None, repr=False)
    timeout_seconds: float = 30


class EndpointResolver(Protocol):
    """Load only named server configurations; request bodies contain no URL/key fields."""

    async def resolve(self, endpoint_id: str) -> ServerEndpoint:
        """Resolve a configured catalog symbol outside checkpoint/serialized payloads."""
        ...


class ToolProposal(ModelContract):
    """Validated model suggestion; execution needs a separate governed tool boundary."""

    name: ToolName
    call_id: Name | None
    arguments_json: BoundJson


class CompanyModelResult(ModelContract):
    """Model response validity is distinct from known or uncertain billable usage."""

    request_id: UUID
    status: Literal["response", "failed", "denied", "cancelled"]
    billing: Literal["known", "unknown", "not_issued"]
    usage: TokenUsage | None = None
    text: BoundText | None = None
    structured_json: BoundJson | None = None
    tool_calls: tuple[ToolProposal, ...] = Field(default=(), max_length=20)
    error_code: Name | None = None

    @model_validator(mode="after")
    def require_honest_billing(self) -> Self:
        """Missing wire usage can never be represented as a known zero charge."""
        if (self.billing == "known") != (self.usage is not None):
            raise ValueError("known billing requires complete validated wire usage")
        if self.status == "response" and self.billing != "known":
            raise ValueError("an accepted response requires supported known usage")
        return self


class ModelRequestCancelledError(asyncio.CancelledError):
    """Preserve cancellation and the typed unknown-billing outcome for the runtime."""

    def __init__(self, result: CompanyModelResult) -> None:
        self.result = result
        super().__init__("Company model request cancelled; billing remains unresolved")
