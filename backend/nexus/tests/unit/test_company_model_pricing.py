"""Monetary acceptance for an unmounted, explicit text-token billing contract."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from nexus.core.llm.company_pricing import (
    PriceCard,
    PricingDeniedError,
    TokenBounds,
    TokenUsage,
    quote_cost,
    reconcile_cost,
)

NOW = datetime(2026, 10, 13, 10, tzinfo=UTC)


def card(**updates: object) -> PriceCard:
    """Return synthetic prices, never a claim about a real provider."""
    data: dict[str, object] = {
        "version": "fixture-prices-1",
        "as_of": NOW.date(),
        "valid_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
        "source_reference": "fixture:synthetic-prices",
        "input_per_million": Decimal("2"),
        "output_per_million": Decimal("8"),
        "cached_input_per_million": Decimal("0.50"),
        "cache_semantics": "included_in_input",
        "reasoning_semantics": "included_in_output",
    }
    return PriceCard.model_validate(data | updates)


def test_reservation_does_not_assume_cache_hits_or_add_reasoning_twice() -> None:
    quote = quote_cost(card(), TokenBounds(input_tokens=1000, max_output_tokens=500), now=NOW)
    assert quote.amount_usd == Decimal("0.006000")
    assert quote.price_version == "fixture-prices-1"
    assert quote.basis == "upper_bound"


def test_normalized_cache_and_reasoning_usage_are_subsets_of_totals() -> None:
    usage = TokenUsage(
        input_tokens=1000, output_tokens=500, cached_input_tokens=400, reasoning_tokens=300
    )
    charge = reconcile_cost(card(), usage, now=NOW)
    assert charge.amount_usd == Decimal("0.005400")
    assert charge.basis == "reported_usage"


def test_reservation_uses_higher_cache_rate_if_configured_above_normal_input() -> None:
    quote = quote_cost(
        card(cached_input_per_million=Decimal("3")),
        TokenBounds(input_tokens=1000, max_output_tokens=0),
        now=NOW,
    )
    assert quote.amount_usd == Decimal("0.003000")


def test_upper_bound_rounds_up_to_journal_precision() -> None:
    quote = quote_cost(
        card(input_per_million=Decimal("0.00001")),
        TokenBounds(input_tokens=1, max_output_tokens=0),
        now=NOW,
    )
    assert quote.amount_usd == Decimal("0.000001")


def test_zero_explicit_price_is_allowed_without_an_unknown_price_default() -> None:
    quote = quote_cost(
        card(
            input_per_million=Decimal("0"),
            output_per_million=Decimal("0"),
            cached_input_per_million=Decimal("0"),
        ),
        TokenBounds(input_tokens=50, max_output_tokens=10),
        now=NOW,
    )
    assert quote.amount_usd == Decimal("0.000000")


@pytest.mark.parametrize(
    "updates",
    [
        {"billing_mode": "unsupported"},
        {"reasoning_semantics": "unsupported"},
        {"valid_until": NOW},
        {"valid_from": NOW + timedelta(hours=1)},
        {"as_of": (NOW + timedelta(days=1)).date()},
    ],
)
def test_unsupported_or_noncurrent_prices_deny_paid_quote(updates: dict[str, object]) -> None:
    with pytest.raises(PricingDeniedError):
        quote_cost(card(**updates), TokenBounds(input_tokens=1, max_output_tokens=1), now=NOW)


def test_unknown_pricing_cannot_return_zero_quote() -> None:
    with pytest.raises(PricingDeniedError, match="unknown"):
        quote_cost(None, TokenBounds(input_tokens=1, max_output_tokens=1), now=NOW)


@pytest.mark.parametrize(
    "updates",
    [
        {"currency": "EUR"},
        {"input_per_million": Decimal("NaN")},
        {"output_per_million": Decimal("Infinity")},
        {"input_per_million": Decimal("-1")},
        {"output_per_million": 0.1},
        {"valid_until": NOW - timedelta(days=2)},
        {"valid_from": NOW.replace(tzinfo=None)},
        {"cache_semantics": "none"},
        {"unexpected_rate": Decimal("1")},
    ],
)
def test_malformed_price_contract_is_rejected(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        card(**updates)


@pytest.mark.parametrize(
    "data",
    [
        {"input_tokens": -1, "max_output_tokens": 1},
        {"input_tokens": True, "max_output_tokens": 1},
        {"input_tokens": 1.5, "max_output_tokens": 1},
        {"input_tokens": 1, "max_output_tokens": 1, "unit": "audio_tokens"},
        {"input_tokens": 1, "max_output_tokens": 1, "output_cap_semantics": "visible_only"},
        {"input_tokens": 1, "max_output_tokens": 1, "max_reasoning_tokens": None},
    ],
)
def test_token_bounds_require_complete_inclusive_text_limits(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TokenBounds.model_validate(data)


@pytest.mark.parametrize(
    "updates",
    [
        {"cached_input_tokens": 101},
        {"reasoning_tokens": 51},
        {"cache_write_tokens": 1},
        {"input_audio_tokens": 1},
        {"usage_complete": False},
    ],
)
def test_ambiguous_or_unsupported_usage_cannot_be_reconciled(updates: dict[str, object]) -> None:
    with pytest.raises((ValidationError, PricingDeniedError)):
        usage = TokenUsage.model_validate({"input_tokens": 100, "output_tokens": 50} | updates)
        reconcile_cost(card(), usage, now=NOW)


def test_disabled_cache_or_reasoning_semantics_reject_nonzero_breakdowns() -> None:
    plain = card(cache_semantics="none", cached_input_per_million=None, reasoning_semantics="none")
    for usage in (
        TokenUsage(input_tokens=10, output_tokens=5, cached_input_tokens=1),
        TokenUsage(input_tokens=10, output_tokens=5, reasoning_tokens=1),
    ):
        with pytest.raises(PricingDeniedError):
            reconcile_cost(plain, usage, now=NOW)


def test_pricing_and_quote_wire_roundtrips_preserve_decimal_and_schema_version() -> None:
    prices = card()
    assert PriceCard.model_validate_json(prices.model_dump_json()) == prices
    quote = quote_cost(prices, TokenBounds(input_tokens=10, max_output_tokens=5), now=NOW)
    assert quote.model_validate_json(quote.model_dump_json()) == quote
    assert quote.schema_version == "nexus.company.models.v1"


def test_price_bound_above_journal_money_range_is_denied() -> None:
    with pytest.raises(PricingDeniedError, match="journal"):
        quote_cost(
            card(input_per_million=Decimal("999999999999")),
            TokenBounds(input_tokens=1_000_000_000, max_output_tokens=0),
            now=NOW,
        )


def test_quote_revalidates_copy_bypass_and_rejects_naive_time() -> None:
    invalid = card().model_copy(update={"input_per_million": Decimal("-1")})
    with pytest.raises(PricingDeniedError):
        quote_cost(invalid, TokenBounds(input_tokens=10, max_output_tokens=5), now=NOW)
    with pytest.raises(PricingDeniedError):
        quote_cost(
            card(), TokenBounds(input_tokens=10, max_output_tokens=5), now=NOW.replace(tzinfo=None)
        )
