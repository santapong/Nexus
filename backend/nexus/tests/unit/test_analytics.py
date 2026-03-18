"""Unit tests for the Analytics API response models."""

from __future__ import annotations

from nexus.api.analytics import (
    AgentPerformanceMetric,
    CostBreakdownResponse,
    CostByModel,
    CostByRole,
    DeadLetterResponse,
    DeadLetterStats,
    PerformanceResponse,
    _parse_period,
)


class TestAnalyticsModels:
    """Tests for analytics Pydantic response models."""

    def test_agent_performance_metric_serialization(self) -> None:
        """AgentPerformanceMetric should serialize all fields correctly."""
        metric = AgentPerformanceMetric(
            role="engineer",
            name="Engineer Agent",
            total_tasks=100,
            completed=85,
            failed=10,
            success_rate=85.0,
            avg_tokens=3500.0,
            avg_duration_seconds=12.5,
            total_cost_usd=0.123456,
        )
        assert metric.role == "engineer"
        assert metric.total_tasks == 100
        assert metric.success_rate == 85.0
        assert metric.avg_duration_seconds == 12.5

    def test_agent_performance_metric_null_duration(self) -> None:
        """AgentPerformanceMetric should handle null duration for agents with no completed tasks."""
        metric = AgentPerformanceMetric(
            role="qa",
            name="QA Agent",
            total_tasks=0,
            completed=0,
            failed=0,
            success_rate=0.0,
            avg_tokens=0.0,
            avg_duration_seconds=None,
            total_cost_usd=0.0,
        )
        assert metric.avg_duration_seconds is None

    def test_performance_response_aggregates(self) -> None:
        """PerformanceResponse should carry aggregate metrics."""
        resp = PerformanceResponse(
            period="30d",
            agents=[],
            total_tasks=50,
            overall_success_rate=92.0,
            total_cost_usd=1.5,
        )
        assert resp.period == "30d"
        assert resp.total_tasks == 50
        assert resp.overall_success_rate == 92.0

    def test_cost_by_model_serialization(self) -> None:
        """CostByModel should carry token and cost breakdowns."""
        model = CostByModel(
            model_name="claude-sonnet-4-20250514",
            total_calls=42,
            total_input_tokens=150000,
            total_output_tokens=50000,
            total_cost_usd=0.7,
        )
        assert model.model_name == "claude-sonnet-4-20250514"
        assert model.total_input_tokens == 150000

    def test_cost_breakdown_response(self) -> None:
        """CostBreakdownResponse should carry per-model and per-role data."""
        resp = CostBreakdownResponse(
            period="7d",
            by_model=[
                CostByModel(
                    model_name="gpt-4o",
                    total_calls=10,
                    total_input_tokens=10000,
                    total_output_tokens=5000,
                    total_cost_usd=0.05,
                )
            ],
            by_role=[CostByRole(role="engineer", total_calls=10, total_cost_usd=0.05)],
            total_cost_usd=0.05,
            daily_average_usd=0.007143,
        )
        assert len(resp.by_model) == 1
        assert len(resp.by_role) == 1
        assert resp.daily_average_usd == 0.007143

    def test_dead_letter_response(self) -> None:
        """DeadLetterResponse should serialize topic-level stats."""
        resp = DeadLetterResponse(
            total_dead_letters=3,
            by_topic=[
                DeadLetterStats(topic="task.queue.dead_letter", count=2),
                DeadLetterStats(topic="agent.commands.dead_letter", count=1),
            ],
        )
        assert resp.total_dead_letters == 3
        assert len(resp.by_topic) == 2


class TestParsePeriod:
    """Tests for the _parse_period helper."""

    def test_7d_returns_cutoff(self) -> None:
        """7d should return a datetime ~7 days ago."""
        result = _parse_period("7d")
        assert result is not None

    def test_30d_returns_cutoff(self) -> None:
        """30d should return a datetime ~30 days ago."""
        result = _parse_period("30d")
        assert result is not None

    def test_90d_returns_cutoff(self) -> None:
        """90d should return a datetime ~90 days ago."""
        result = _parse_period("90d")
        assert result is not None

    def test_all_returns_none(self) -> None:
        """'all' period should return None (no cutoff)."""
        result = _parse_period("all")
        assert result is None

    def test_unknown_period_returns_none(self) -> None:
        """Unknown period strings should return None (no cutoff)."""
        result = _parse_period("1y")
        assert result is None
