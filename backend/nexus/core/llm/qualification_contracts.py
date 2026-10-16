"""Separate public SDK qualification descriptions; none establish model eligibility."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import stat
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from nexus.company.management.base import Name
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import GoalRevisionRef
from nexus.core.llm.company_adapter_contracts import (
    BoundText,
    CompanyModelRequest,
    JsonSchemaDocument,
    request_hash,
)
from nexus.core.llm.company_input_bounds import model_input_ceiling, model_output_ceiling
from nexus.core.llm.company_pricing import ModelContract, TokenBounds
from nexus.core.llm.company_registry import ModelRegistration
from nexus.harness.journal_contracts import LedgerScope

WORKFLOW = "company.model-qualification.v1"
VERSION = "v1"
QUEUE = "nexus.model-qualification"
APPLICATION = "nexus-model-qualification"
PROFILE = "qualification-only.v1"
TOOL = "model.qualify.v1"
SDK_MODULES = (
    "nexus.core.llm.company_adapter_sdk",
    "nexus.core.llm.company_wire_usage",
    "nexus.core.llm.company_input_bounds",
    "pydantic_ai.models.google",
    "pydantic_ai.models.openai",
    "pydantic_ai.providers.google",
    "pydantic_ai.providers.openai",
    "google.genai.models",
    "google.genai._extra_utils",
    "openai._base_client",
)
SDK_DISTRIBUTIONS = ("pydantic-ai-slim", "google-genai", "openai")


class SdkVersion(ModelContract):
    distribution: Name
    version: Name


class SdkSource(ModelContract):
    module: Name
    byte_length: int = Field(gt=0, le=2_000_000, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SdkPins(ModelContract):
    versions: tuple[SdkVersion, ...]
    files: tuple[SdkSource, ...]

    @model_validator(mode="after")
    def complete(self) -> Self:
        if (
            tuple(v.distribution for v in self.versions) != SDK_DISTRIBUTIONS
            or tuple(v.module for v in self.files) != SDK_MODULES
        ):
            raise ValueError("Qualification needs the exact complete SDK source/version set")
        return self


def _sdk_snapshot() -> SdkPins:
    files = []
    for module in SDK_MODULES:
        spec = importlib.util.find_spec(module)
        if spec is None or spec.origin is None:
            raise ValueError("Qualification SDK source is unavailable")
        path = Path(spec.origin)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            raw = stream.read(2_000_001)
            after = os.fstat(stream.fileno())
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (
            not stat.S_ISREG(before.st_mode)
            or not 0 < len(raw) <= 2_000_000
            or any(getattr(before, key) != getattr(after, key) for key in fields)
            or any(
                getattr(after, key) != getattr(path.stat(follow_symlinks=False), key)
                for key in fields
            )
        ):
            raise ValueError("Qualification SDK source changed while reading")
        files.append(
            SdkSource(module=module, byte_length=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        )
    return SdkPins(
        versions=tuple(
            SdkVersion(distribution=name, version=importlib.metadata.version(name))
            for name in SDK_DISTRIBUTIONS
        ),
        files=tuple(files),
    )


async def capture_sdk_pins() -> SdkPins:
    """Read actual installed source/version bytes outside the company transaction."""
    return await asyncio.to_thread(_sdk_snapshot)


class QualificationRecipe(ModelContract):
    purpose: Literal["public-sdk-conformance-only-v1"] = "public-sdk-conformance-only-v1"
    goal: GoalRevisionRef
    recipe_id: Name
    revision: Name
    case_id: Name
    target: ModelRegistration
    registry_revision: Name
    qualification_target_sha256s: tuple[str, ...] = Field(min_length=1, max_length=32)
    input_text: BoundText
    system_text: BoundText | None = None
    output_schema: JsonSchemaDocument | None = None
    request_output_cap: int = Field(gt=0, le=4096, strict=True)
    financial_input_ceiling: int = Field(gt=0, le=1_000_000_000, strict=True)
    financial_output_ceiling: int = Field(gt=0, le=1_000_000_000, strict=True)
    source_reference: Name
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    valid_until: AwareDatetime
    sdk_pins: SdkPins

    @model_validator(mode="after")
    def unqualified_public_target(self) -> Self:
        row = self.target
        target_set_hash(self.registry_revision, self.qualification_target_sha256s)
        if (
            row.enabled
            or row.health.status != "unknown"
            or row.evaluations
            or row.allowed_data != frozenset({"public"})
            or not {"text"} <= row.capabilities
            or (self.output_schema is not None and "structured_output" not in row.capabilities)
            or row.price is None
            or canonical_sha256(row) not in self.qualification_target_sha256s
            or self.financial_input_ceiling != model_input_ceiling(row)
            or row.max_output_tokens != model_output_ceiling(row)
            or self.financial_output_ceiling != model_output_ceiling(row)
            or self.request_output_cap > row.max_output_tokens
            or self.valid_until > row.price.valid_until
            or len(self.input_text.encode()) + len((self.system_text or "").encode()) > 8192
        ):
            raise ValueError(
                "Qualification requires an unqualified public target and full financial ceilings"
            )
        return self


def target_set_hash(registry_revision: str, hashes: tuple[str, ...]) -> str:
    if (
        type(registry_revision) is not str
        or not registry_revision
        or len(registry_revision) > 128
        or type(hashes) is not tuple
        or not 1 <= len(hashes) <= 32
        or tuple(sorted(set(hashes))) != hashes
        or any(
            type(value) is not str
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
            for value in hashes
        )
    ):
        raise ValueError("Qualification needs its complete sorted unique target set")
    raw = json.dumps(
        ("qualification-target-set-v1", registry_revision, hashes),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def recipe_hash(recipe: QualificationRecipe) -> str:
    return canonical_sha256(recipe)


def qualification_request(
    recipe: QualificationRecipe, scope: LedgerScope, *, action_id: UUID, request_id: UUID
) -> CompanyModelRequest:
    if not isinstance(action_id, UUID) or not isinstance(request_id, UUID):
        raise ValueError("Qualification request identifiers must be actual UUIDs")
    recipe = QualificationRecipe.model_validate_json(recipe.model_dump_json(by_alias=True))
    if recipe.goal.company_id != scope.company_id:
        raise ValueError("Qualification goal company differs")
    assert recipe.target.price is not None
    return CompanyModelRequest(
        company_id=scope.company_id,
        task_id=scope.task_id,
        trace_id=scope.trace_id,
        actor_id=scope.principal_id,
        action_id=action_id,
        attempt_id=action_id,
        request_id=request_id,
        registry_id=recipe.target.registry_id,
        registry_revision=recipe.registry_revision,
        price_version=recipe.target.price.version,
        data_classification="public",
        input_text=recipe.input_text,
        system_text=recipe.system_text,
        output_schema=recipe.output_schema,
        tools=(),
        bounds=TokenBounds(
            input_tokens=recipe.financial_input_ceiling,
            max_output_tokens=recipe.request_output_cap,
            input_bound_kind="model_input_ceiling_v1",
        ),
    )


def qualification_parameters(
    recipe: QualificationRecipe, request: CompanyModelRequest
) -> dict[str, JsonValue]:
    return {
        "purpose": recipe.purpose,
        "recipe_sha256": recipe_hash(recipe),
        "request_sha256": request_hash(request),
        "target_sha256": canonical_sha256(recipe.target),
        "goal_sha256": canonical_sha256(recipe.goal),
        "source_sha256": recipe.source_sha256,
        "sdk_sha256": canonical_sha256(recipe.sdk_pins),
        "financial_input_ceiling": recipe.financial_input_ceiling,
        "financial_output_ceiling": recipe.financial_output_ceiling,
        "request_output_cap": recipe.request_output_cap,
    }


def financial_bounds(recipe: QualificationRecipe) -> TokenBounds:
    return TokenBounds(
        input_tokens=recipe.financial_input_ceiling,
        max_output_tokens=recipe.financial_output_ceiling,
        input_bound_kind="model_input_ceiling_v1",
    )
