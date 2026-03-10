"""Unit tests for the cost estimator module."""
from __future__ import annotations

import pytest

from nexus.llm.cost_estimator import (
    CostEstimate,
    SubtaskEstimate,
    _estimate_cost_for_tokens,
    _get_model_for_role,
    estimate_task_cost,
)


class TestGetModelForRole:
    """Tests for _get_model_for_role mapping."""

    def test_known_roles_return_correct_model(self) -> None:
        """Known agent roles should map to their default models."""
        assert _get_model_for_role("ceo") == "claude-sonnet-4-20250514"
        assert _get_model_for_role("analyst") == "gemini-1.5-pro"
        assert _get_model_for_role("writer") == "claude-haiku-4-5-20251001"
        assert _get_model_for_role("qa") == "claude-haiku-4-5-20251001"

    def test_unknown_role_returns_default(self) -> None:
        """Unknown roles should fall back to claude-sonnet."""
        assert _get_model_for_role("unknown") == "claude-sonnet-4-20250514"


class TestEstimateCostForTokens:
    """Tests for _estimate_cost_for_tokens calculation."""

    def test_known_model_returns_cost(self) -> None:
        """Known model should return a non-zero cost estimate."""
        cost = _estimate_cost_for_tokens("claude-sonnet-4-20250514", 10000)
        assert cost > 0
        # 10000 tokens: 6000 input * $3/M + 4000 output * $15/M = $0.078
        expected = (6000 * 3.0 + 4000 * 15.0) / 1_000_000
        assert abs(cost - expected) < 0.0001

    def test_unknown_model_returns_zero(self) -> None:
        """Unknown model should return 0.0."""
        cost = _estimate_cost_for_tokens("nonexistent-model", 10000)
        assert cost == 0.0

    def test_zero_tokens_returns_zero(self) -> None:
        """Zero tokens should return zero cost."""
        cost = _estimate_cost_for_tokens("claude-sonnet-4-20250514", 0)
        assert cost == 0.0

    def test_local_model_returns_zero(self) -> None:
        """Local Ollama models should return zero cost."""
        cost = _estimate_cost_for_tokens("ollama:llama3", 50000)
        assert cost == 0.0


class TestEstimateTaskCost:
    """Tests for estimate_task_cost async function."""

    @pytest.mark.asyncio
    async def test_single_subtask_plan(self) -> None:
        """Single subtask should produce a valid cost estimate."""
        plan = [{"role": "engineer", "instruction": "Build a REST API"}]
        result = await estimate_task_cost(plan)

        assert isinstance(result, CostEstimate)
        assert result.subtask_count == 1
        assert len(result.subtasks) == 1
        assert result.total_estimated_tokens > 0
        assert result.total_estimated_cost_usd > 0
        assert result.confidence == "low"  # no session = no history

    @pytest.mark.asyncio
    async def test_multi_subtask_plan(self) -> None:
        """Multiple subtasks should produce aggregate estimates."""
        plan = [
            {"role": "analyst", "instruction": "Research competitors"},
            {"role": "writer", "instruction": "Write summary"},
            {"role": "engineer", "instruction": "Build dashboard"},
        ]
        result = await estimate_task_cost(plan)

        assert result.subtask_count == 3
        assert len(result.subtasks) == 3
        assert result.total_estimated_tokens == sum(s.estimated_tokens for s in result.subtasks)
        assert result.confidence == "low"

    @pytest.mark.asyncio
    async def test_empty_plan(self) -> None:
        """Empty plan should return zero estimates."""
        result = await estimate_task_cost([])

        assert result.subtask_count == 0
        assert result.total_estimated_tokens == 0
        assert result.total_estimated_cost_usd == 0.0
        assert result.confidence == "low"

    @pytest.mark.asyncio
    async def test_subtask_estimate_model(self) -> None:
        """SubtaskEstimate should carry correct model for each role."""
        plan = [{"role": "analyst", "instruction": "Analyze data"}]
        result = await estimate_task_cost(plan)

        assert result.subtasks[0].role == "analyst"
        assert result.subtasks[0].model_name == "gemini-1.5-pro"
        assert isinstance(result.subtasks[0], SubtaskEstimate)
