from __future__ import annotations

from decimal import Decimal


def test_settings_loads_defaults() -> None:
    """Settings loads with sensible defaults."""
    from nexus.settings import settings

    assert settings.daily_spend_limit_usd == Decimal("5.00")
    assert settings.default_token_budget_per_task == 50_000
    assert settings.app_env == "development"
    assert settings.is_development is True
