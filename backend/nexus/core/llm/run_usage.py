"""Typed SDK usage extraction; unavailable billing cannot be reported as free."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.usage import RunUsage


class UsageUnavailableError(ValueError):
    """Model usage is missing or malformed; accounting requires reconciliation."""


class RunTokenUsage(BaseModel):
    """Observed nonnegative token counts, including valid observed zero counts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)

    @property
    def total_tokens(self) -> int:
        """Return the measured input/output total without estimates or defaults."""
        return self.input_tokens + self.output_tokens


def extract_run_tokens(result: object) -> RunTokenUsage:
    """Read SDK2 usage properties or explicitly validated SDK1 callable results.

    Never replace missing counts with zero. Legacy callable compatibility is
    retained for older SDK results and existing old-API test doubles. A new
    property's malformed input/output fields cannot fall back to old aliases.
    """
    try:
        accessor = getattr(result, "usage", None)
        # SDK1's transitional RunUsage property is callable only to emit a
        # deprecation warning. Read its fields directly rather than invoking it.
        if callable(accessor) and not isinstance(accessor, RunUsage):
            usage = accessor()
            legacy = True
        else:
            usage = accessor
            legacy = False
    except Exception as exc:
        raise UsageUnavailableError("Model usage could not be read") from exc
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if legacy and (type(input_tokens) is not int or type(output_tokens) is not int):
        input_tokens = getattr(usage, "request_tokens", None)
        output_tokens = getattr(usage, "response_tokens", None)
    try:
        return RunTokenUsage.model_validate(
            {"input_tokens": input_tokens, "output_tokens": output_tokens}
        )
    except ValidationError as exc:
        raise UsageUnavailableError(
            "Model usage is unknown or invalid; reconciliation required"
        ) from exc
