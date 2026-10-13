"""Server estimator evidence and immutable exact approval binding for one model request."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import Field, JsonValue, field_validator

from nexus.company.contracts.base import Name
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, request_hash
from nexus.core.llm.company_pricing import ModelContract, Score, Tokens
from nexus.core.llm.company_registry import ModelRegistry, Profile


class ModelInputRecipe(ModelContract):
    """Explicit trusted estimator/profile recipe; no production estimator is supplied here."""

    recipe_id: Name
    revision: Name
    profile: Profile
    minimum_score: Score
    evaluation_suite_version: Name
    conformance_reference: Name

    @field_validator("minimum_score", mode="before")
    @classmethod
    def exact_score(cls, value: object) -> object:
        """Reject ambiguous quality thresholds."""
        if isinstance(value, (float, bool)):
            raise ValueError("Recipe quality threshold must be an exact decimal")
        return value


class InputEstimate(ModelContract):
    """Independent full SDK request upper bound, bound to the exact request and recipe."""

    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_id: Name
    registry_revision: Name
    recipe_id: Name
    recipe_revision: Name
    input_text_tokens: Tokens
    system_text_tokens: Tokens
    tool_schema_tokens: Tokens
    output_schema_tokens: Tokens
    sdk_overhead_tokens: Tokens

    @property
    def total_tokens(self) -> int:
        """Include every declared source of input tokens, including SDK framing."""
        return sum(
            (
                self.input_text_tokens,
                self.system_text_tokens,
                self.tool_schema_tokens,
                self.output_schema_tokens,
                self.sdk_overhead_tokens,
            )
        )


class InputEstimator(Protocol):
    """Fast bounded pure server service; no provider/network I/O under the company mutex."""

    def estimate(
        self, call: CompanyModelRequest, registry: ModelRegistry, recipe: ModelInputRecipe
    ) -> InputEstimate:
        """Produce a conservative bound including system, tools, schema and SDK overhead."""
        ...


def model_action_parameters(
    call: CompanyModelRequest, recipe: ModelInputRecipe
) -> dict[str, JsonValue]:
    """Create the exact owner-approved model action parameters from trusted composition."""
    recipe = ModelInputRecipe.model_validate(recipe.model_dump())
    canonical = json.dumps(recipe.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return {
        "request_hash": request_hash(call),
        "request_id": str(call.request_id),
        "attempt_id": str(call.attempt_id),
        "registry_id": call.registry_id,
        "registry_revision": call.registry_revision,
        "price_version": call.price_version,
        "input_recipe_id": recipe.recipe_id,
        "input_recipe_revision": recipe.revision,
        "input_recipe_hash": hashlib.sha256(canonical.encode()).hexdigest(),
    }


def require_input_estimate(
    call: CompanyModelRequest, estimate: InputEstimate, recipe: ModelInputRecipe
) -> None:
    """Caller bounds are insufficient without independently bound complete estimation."""
    estimate = InputEstimate.model_validate(estimate.model_dump())
    if (
        (
            estimate.request_hash,
            estimate.registry_id,
            estimate.registry_revision,
            estimate.recipe_id,
            estimate.recipe_revision,
        )
        != (
            request_hash(call),
            call.registry_id,
            call.registry_revision,
            recipe.recipe_id,
            recipe.revision,
        )
        or estimate.input_text_tokens == 0
        or estimate.sdk_overhead_tokens == 0
        or (call.system_text and estimate.system_text_tokens == 0)
        or (call.tools and estimate.tool_schema_tokens == 0)
        or (call.output_schema and estimate.output_schema_tokens == 0)
        or estimate.total_tokens > call.bounds.input_tokens
    ):
        raise ValueError("Request has no complete independently bound input estimate")
