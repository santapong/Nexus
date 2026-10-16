"""Reviewed whole-input financial ceilings; these do not certify prompt fit or eligibility."""

from nexus.core.llm.company_pricing import TokenBounds
from nexus.core.llm.company_registry import ModelRegistration

# Official model specifications reviewed 2026-10-16. Unknown aliases do not inherit limits.
# https://developers.openai.com/api/docs/models/gpt-5.4-mini
# https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
_LIMITS = {
    ("openai", "openai_responses", "gpt-5.4-mini-2026-03-17"): (400_000, 128_000),
    ("google", "google_generate_content", "gemini-3.5-flash-lite"): (1_048_576, 65_536),
}


def _reviewed_limits(row: ModelRegistration) -> tuple[int, int]:
    limits = _LIMITS.get((row.provider, row.api_family, row.model_id))
    if (
        limits is None
        or row.context_window != limits[0]
        or not 0 < row.max_output_tokens <= limits[1]
    ):
        raise ValueError("Model has no reviewed complete input ceiling")
    return limits


def model_input_ceiling(row: ModelRegistration) -> int:
    """Require the reviewed exact tuple/input limit; a local output policy may narrow."""
    return _reviewed_limits(row)[0]


def model_output_ceiling(row: ModelRegistration) -> int:
    """Return the advertised total output ceiling, not an operator's smaller policy cap."""
    return _reviewed_limits(row)[1]


def require_model_input_bounds(row: ModelRegistration, bounds: TokenBounds) -> None:
    """Preserve legacy combined fit; admit explicit full-ceiling cost reservations only.

    A provider may reject a request that cannot fit with its requested output. The
    financial mode reserves every input token the model can accept and the full
    output cap; it makes no local tokenization or successful context-fit promise.
    Health, evaluation, current prices, data policy and durable allowance remain
    separate mandatory gates. This pure helper creates no execution permission.
    """
    bounds = TokenBounds.model_validate(bounds.model_dump())
    if bounds.input_bound_kind is None:
        if (
            bounds.input_tokens + bounds.max_output_tokens > row.context_window
            or bounds.max_output_tokens > row.max_output_tokens
        ):
            raise ValueError("Model request exceeds context/output limits")
    elif (
        bounds.input_tokens != model_input_ceiling(row)
        or not 0 < bounds.max_output_tokens <= row.max_output_tokens
    ):
        raise ValueError("Whole-input reservation must use the reviewed exact ceiling")
