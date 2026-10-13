"""Explicit flat text-token prices and conservative journal-compatible quotations.

No prices are discovered or defaulted. Adapters must attest that their enforced
output cap and normalized usage include hidden reasoning/formatting tokens. This
module does not interpret provider payloads or prove an adapter's conformance.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_CEILING, Decimal, localcontext
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from nexus.company.contracts.base import USD, Name

Rate = Annotated[Decimal, Field(ge=0, max_digits=24, decimal_places=12, allow_inf_nan=False)]
Tokens = Annotated[int, Field(ge=0, le=1_000_000_000, strict=True)]
Score = Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]
_MILLION = Decimal("1000000")
_JOURNAL_UNIT = Decimal("0.000001")


class ModelContract(BaseModel):
    """Immutable versioned JSON boundary, including validated default values."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)
    schema_version: Literal["nexus.company.models.v1"] = "nexus.company.models.v1"


class PricingDeniedError(ValueError):
    """The request has no demonstrably bounded supported cost."""


class PriceCard(ModelContract):
    """Dated flat text rates; unsupported modes remain explicitly ineligible.

    Cache reads and reasoning are inclusive subsets of their respective totals.
    Cache writes/storage, tiered prices, audio/images and hosted tools need new
    evaluated contracts. A price source is a reference, not a fetched authority.
    """

    version: Name
    currency: Literal["USD"] = "USD"
    as_of: date
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    source_reference: Name
    billing_mode: Literal["flat_text_tokens", "unsupported"] = "flat_text_tokens"
    input_per_million: Rate
    output_per_million: Rate
    cached_input_per_million: Rate | None = None
    cache_semantics: Literal["none", "included_in_input"] = "none"
    reasoning_semantics: Literal["none", "included_in_output", "unsupported"] = "none"

    @field_validator(
        "input_per_million", "output_per_million", "cached_input_per_million", mode="before"
    )
    @classmethod
    def reject_inexact_rates(cls, value: object) -> object:
        """Allow Decimal/string wire rates; never accept lossy float rates."""
        if isinstance(value, (float, bool)):
            raise ValueError("rates must use exact Decimal or decimal strings")
        return value

    @model_validator(mode="after")
    def require_consistent_card(self) -> Self:
        """Bind the supported cache semantics to one explicit rate."""
        if self.valid_until <= self.valid_from:
            raise ValueError("price validity must be a positive interval")
        has_cache = self.cached_input_per_million is not None
        if has_cache != (self.cache_semantics == "included_in_input"):
            raise ValueError("cache semantics and cached input rate must agree")
        return self


class TokenBounds(ModelContract):
    """Per-call provider-enforced bounds, including all billed output tokens.

    input_tokens is an upper bound including framing, tools/schema and history.
    max_output_tokens covers visible, hidden reasoning and formatting together.
    Exact tokenization and cap enforcement belong to an evaluated adapter.
    """

    input_tokens: Tokens
    max_output_tokens: Tokens
    unit: Literal["text_tokens"] = "text_tokens"
    output_cap_semantics: Literal["total_including_reasoning"] = "total_including_reasoning"


class TokenUsage(ModelContract):
    """Complete normalized text usage; missing/unsupported charges retain a hold."""

    input_tokens: Tokens
    output_tokens: Tokens
    cached_input_tokens: Tokens = 0
    reasoning_tokens: Tokens = 0
    usage_complete: Literal[True] = True

    @model_validator(mode="after")
    def require_inclusive_breakdowns(self) -> Self:
        """Prevent double counting or discounting tokens outside reported totals."""
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached input tokens must be included in input total")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning tokens must be included in output total")
        return self


class CostQuote(ModelContract):
    """One conservative rounded amount bound to its exact dated price version."""

    price_version: Name
    currency: Literal["USD"] = "USD"
    amount_usd: USD
    basis: Literal["upper_bound", "reported_usage"]


def _current_price(price: PriceCard | None, now: datetime) -> PriceCard:
    if price is None:
        raise PricingDeniedError("unknown pricing")
    try:
        price = PriceCard.model_validate(price.model_dump())
    except ValueError as exc:
        raise PricingDeniedError("invalid price contract") from exc
    if now.utcoffset() is None:
        raise PricingDeniedError("quote time must be timezone-aware")
    if price.as_of > now.date() or not price.valid_from <= now < price.valid_until:
        raise PricingDeniedError("pricing is not current")
    if price.billing_mode != "flat_text_tokens" or price.reasoning_semantics == "unsupported":
        raise PricingDeniedError("unsupported billing semantics")
    return price


def _amount(
    input_tokens: int, input_rate: Decimal, output_tokens: int, output_rate: Decimal
) -> Decimal:
    # The accepted 24-digit rates and bounded token counts require >28 digits.
    with localcontext() as context:
        context.prec = 50
        total = (input_tokens * input_rate + output_tokens * output_rate) / _MILLION
        return total.quantize(_JOURNAL_UNIT, rounding=ROUND_CEILING)


def _quote(
    version: str, amount: Decimal, basis: Literal["upper_bound", "reported_usage"]
) -> CostQuote:
    try:
        return CostQuote(price_version=version, amount_usd=amount, basis=basis)
    except ValueError as exc:
        raise PricingDeniedError("amount exceeds journal monetary representation") from exc


def quote_cost(price: PriceCard | None, bounds: TokenBounds, *, now: datetime) -> CostQuote:
    """Quote one call at full bounded input/output without assuming cache hits."""
    current = _current_price(price, now)
    bounds = TokenBounds.model_validate(bounds.model_dump())
    input_rate = max(current.input_per_million, current.cached_input_per_million or Decimal(0))
    return _quote(
        current.version,
        _amount(
            bounds.input_tokens, input_rate, bounds.max_output_tokens, current.output_per_million
        ),
        "upper_bound",
    )


def reconcile_cost(price: PriceCard | None, usage: TokenUsage, *, now: datetime) -> CostQuote:
    """Calculate supported complete usage; do not refund absent billing details.

    now is the original billing instant bound to the retained price snapshot,
    rather than a later reconciliation wall clock after that card has expired.
    Provider invoices can still differ; the journal records verified real costs.
    """
    current = _current_price(price, now)
    usage = TokenUsage.model_validate(usage.model_dump())
    if usage.cached_input_tokens and current.cache_semantics != "included_in_input":
        raise PricingDeniedError("cache usage is unsupported")
    if usage.reasoning_tokens and current.reasoning_semantics != "included_in_output":
        raise PricingDeniedError("reasoning usage is unsupported")
    normal = usage.input_tokens - usage.cached_input_tokens
    with localcontext() as context:
        context.prec = 50
        cache_cost = usage.cached_input_tokens * (current.cached_input_per_million or Decimal(0))
        input_cost = normal * current.input_per_million + cache_cost
        total = (input_cost + usage.output_tokens * current.output_per_million) / _MILLION
        amount = total.quantize(_JOURNAL_UNIT, rounding=ROUND_CEILING)
    return _quote(current.version, amount, "reported_usage")
