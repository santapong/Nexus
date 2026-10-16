"""Pure full-input cost reservation from reviewed limits and constructor source snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.metadata import distribution, version
from pathlib import Path

from nexus.company.management.canonical import canonical_sha256
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, request_hash
from nexus.core.llm.company_input_bounds import model_input_ceiling, require_model_input_bounds
from nexus.core.llm.company_registry import ModelRegistry
from nexus.harness.model_authorizer_contracts import (
    InputEstimate,
    ModelInputRecipe,
    WholeRequestInputCeiling,
    require_input_estimate,
)

_VERSIONS = (
    ("pydantic-ai-slim", "2.54.0"),
    ("openai", "3.29.0"),
    ("google-genai", "2.30.1"),
    ("httpx2", "2.13.1"),
    ("pydantic", "2.13.4"),
)
# Exact reviewed source bytes, not a claim of live model quality. These include
# native schema/system framing and the single-response Google continuation guard.
_SOURCES = (
    (
        "pydantic-ai-slim",
        "pydantic_ai/models/openai.py",
        "ee96b2e5e8e2d38843383dd6c13db680840eb1af74714e441c94797a4ba2087f",
    ),
    (
        "pydantic-ai-slim",
        "pydantic_ai/models/google.py",
        "51da8c6dbe19b29a35e19589671b8da55a1317378b60014e00593dc56ba06ff9",
    ),
    (
        "google-genai",
        "google/genai/models.py",
        "7d402369aa6c8907f140ffd632cca7127519e1f59e33752cc83660497aa558b4",
    ),
)
_ADAPTER_SHA = "ba3838636baf93dde7485c3ffa67c51b2a6f65925adb50554b95f11ff12bf375"
RECIPE_ID = "company-full-context-input"
RECIPE_REVISION = "v1"


def _source_hash(path: Path, expected: str) -> str:
    with path.open("rb") as stream:
        payload = stream.read(400_001)
    actual = hashlib.sha256(payload).hexdigest()
    if len(payload) > 400_000 or actual != expected:
        raise ValueError("Input estimator SDK source differs from reviewed framing")
    return actual


def input_conformance_reference() -> str:
    """Observe bounded fixed source/version pins during server construction, never estimation.

    No SDK client, tokenizer, provider request or environment key lookup occurs.
    A different source deployment requires a new reviewed recipe, not automatic
    adoption of its observed hash. The reference attests source identity only.
    """
    versions = tuple((name, version(name)) for name, _ in _VERSIONS)
    if versions != _VERSIONS:
        raise ValueError("Input estimator SDK versions differ from reviewed pins")
    sources = tuple(
        (
            name,
            relative,
            _source_hash(Path(str(distribution(name).locate_file(relative))), expected),
        )
        for name, relative, expected in _SOURCES
    )
    adapter = Path(__file__).resolve().parents[1] / "core/llm/company_adapter_sdk.py"
    encoded = json.dumps(
        {
            "method": "model_input_ceiling_v1",
            "versions": versions,
            "sources": sources,
            "adapter": _source_hash(adapter, _ADAPTER_SHA),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "company-input-ceiling-v1:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True, init=False)
class FullContextInputEstimator:
    """Trusted pure estimate; constructor IO pins the exact server composition once.

    A full input reservation is conservative under the reviewed provider input
    ceiling/flat-token billing contract. It does not prove prompt fit, availability,
    health, evaluation, live billing conformance or authority to issue a request.
    """

    _registry_sha256: str
    _recipe_sha256: str
    _conformance: str

    def __init__(self, registry: ModelRegistry, recipe: ModelInputRecipe) -> None:
        registry = ModelRegistry.model_validate_json(registry.model_dump_json())
        recipe = ModelInputRecipe.model_validate_json(recipe.model_dump_json())
        conformance = input_conformance_reference()
        if (recipe.recipe_id, recipe.revision, recipe.conformance_reference) != (
            RECIPE_ID,
            RECIPE_REVISION,
            conformance,
        ):
            raise ValueError("Input estimator recipe has no matching reviewed SDK composition")
        object.__setattr__(self, "_registry_sha256", canonical_sha256(registry))
        object.__setattr__(self, "_recipe_sha256", canonical_sha256(recipe))
        object.__setattr__(self, "_conformance", conformance)

    def estimate(
        self, call: CompanyModelRequest, registry: ModelRegistry, recipe: ModelInputRecipe
    ) -> InputEstimate:
        """Check exact immutable values and reserve the full accepted input ceiling, without IO."""
        call = CompanyModelRequest.model_validate_json(call.model_dump_json(by_alias=True))
        registry = ModelRegistry.model_validate_json(registry.model_dump_json())
        recipe = ModelInputRecipe.model_validate_json(recipe.model_dump_json())
        if (
            canonical_sha256(registry) != self._registry_sha256
            or canonical_sha256(recipe) != self._recipe_sha256
            or (call.company_id, call.registry_revision, call.price_version)
            != (registry.company_id, registry.revision, registry.pricebook_version)
            or call.tools
            or call.bounds.input_bound_kind != "model_input_ceiling_v1"
        ):
            raise ValueError("Input estimate differs from its server registry/recipe/request shape")
        row = next((row for row in registry.models if row.registry_id == call.registry_id), None)
        if row is None or call.data_classification not in row.allowed_data:
            raise ValueError("Input estimate model/data policy is absent from its exact registry")
        require_model_input_bounds(row, call.bounds)
        result = InputEstimate(
            request_hash=request_hash(call),
            registry_id=call.registry_id,
            registry_revision=registry.revision,
            recipe_id=recipe.recipe_id,
            recipe_revision=recipe.revision,
            input_text_tokens=0,
            system_text_tokens=0,
            tool_schema_tokens=0,
            output_schema_tokens=0,
            sdk_overhead_tokens=0,
            whole_request=WholeRequestInputCeiling(
                tokens=model_input_ceiling(row),
                registry_sha256=self._registry_sha256,
                model_sha256=canonical_sha256(row),
                recipe_sha256=self._recipe_sha256,
                conformance_reference=self._conformance,
            ),
        )
        require_input_estimate(call, result, recipe)
        return result
