"""Unit tests for ModelFactory fallback chain (BACKLOG-019).

Tests cover:
- Fallback list parsing
- Single model → no FallbackModel wrapper
- Empty fallback string → no wrapper
- Test model prefix → no wrapper
- Failed fallback resolve → skipped gracefully
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nexus.integrations.llm.factory import ModelFactory, _parse_fallback_list


class TestParseFallbackList:
    """Tests for _parse_fallback_list() helper."""

    def test_single_fallback(self) -> None:
        """Single model name is returned as one-element list."""
        result = _parse_fallback_list("groq:llama-3.3-70b-versatile")
        assert result == ["groq:llama-3.3-70b-versatile"]

    def test_multiple_fallbacks(self) -> None:
        """Comma-separated models are split and stripped."""
        result = _parse_fallback_list("gemini-2.0-flash , groq:llama-3.3-70b-versatile")
        assert result == ["gemini-2.0-flash", "groq:llama-3.3-70b-versatile"]

    def test_empty_string_returns_empty_list(self) -> None:
        """Empty string returns empty list — disables fallback."""
        result = _parse_fallback_list("")
        assert result == []

    def test_only_whitespace_returns_empty_list(self) -> None:
        """Whitespace-only entries are filtered out."""
        result = _parse_fallback_list(",  , ")
        assert result == []

    def test_trailing_comma_ignored(self) -> None:
        """Trailing comma does not create a phantom empty entry."""
        result = _parse_fallback_list("groq:llama-3.3-70b-versatile,")
        assert result == ["groq:llama-3.3-70b-versatile"]


class TestModelFactoryFallbacks:
    """Tests for ModelFactory.get_model_with_fallbacks()."""

    def test_test_model_prefix_returns_no_wrapper(self) -> None:
        """test: prefix bypasses FallbackModel wrapping entirely."""
        from pydantic_ai.models.test import TestModel

        from nexus.db.models import AgentRole

        with (
            patch("nexus.llm.factory._AGENT_MODEL_MAP", {AgentRole.ENGINEER: "test:model"}),
            patch(
                "nexus.llm.factory._AGENT_FALLBACK_MAP",
                {AgentRole.ENGINEER: "groq:llama-3.3-70b-versatile"},
            ),
        ):
            result = ModelFactory.get_model_with_fallbacks(AgentRole.ENGINEER)
            assert isinstance(result, TestModel)

    def test_no_fallbacks_configured_returns_primary_directly(self) -> None:
        """Empty fallback string returns primary model without wrapping."""
        from pydantic_ai.models.test import TestModel

        from nexus.db.models import AgentRole

        with (
            patch("nexus.llm.factory._AGENT_MODEL_MAP", {AgentRole.ENGINEER: "test:model"}),
            patch("nexus.llm.factory._AGENT_FALLBACK_MAP", {AgentRole.ENGINEER: ""}),
        ):
            result = ModelFactory.get_model_with_fallbacks(AgentRole.ENGINEER)
            assert isinstance(result, TestModel)

    def test_invalid_fallback_skipped_gracefully(self) -> None:
        """If a fallback model fails to resolve, it is skipped with a warning."""
        from pydantic_ai.models.test import TestModel

        from nexus.db.models import AgentRole

        # Primary is test model (no API call), fallback is an unknown provider
        with (
            patch("nexus.llm.factory._AGENT_MODEL_MAP", {AgentRole.ENGINEER: "test:model"}),
            patch(
                "nexus.llm.factory._AGENT_FALLBACK_MAP",
                {AgentRole.ENGINEER: "unknown-provider:xyz"},
            ),
        ):
            # Should not raise - just skips and returns the primary
            result = ModelFactory.get_model_with_fallbacks(AgentRole.ENGINEER)
            assert isinstance(result, TestModel)

    def test_two_valid_models_builds_fallback_model(self) -> None:
        """Primary + 1 valid fallback produces a FallbackModel wrapper."""
        from nexus.db.models import AgentRole

        mock_primary = MagicMock()
        mock_fallback = MagicMock()
        mock_fb_instance = MagicMock()

        with (
            patch("nexus.llm.factory._AGENT_MODEL_MAP", {AgentRole.CEO: "claude-sonnet"}),
            patch(
                "nexus.llm.factory._AGENT_FALLBACK_MAP",
                {AgentRole.CEO: "groq:llama-3.3-70b-versatile"},
            ),
            patch("nexus.llm.factory.resolve_model") as mock_resolve,
            patch(
                "pydantic_ai.models.fallback.FallbackModel",
                return_value=mock_fb_instance,
            ) as mock_fb_cls,
        ):
            mock_resolve.side_effect = [mock_primary, mock_fallback]
            result = ModelFactory.get_model_with_fallbacks(AgentRole.CEO)
            mock_fb_cls.assert_called_once_with(mock_primary, mock_fallback)
            assert result is mock_fb_instance

    def test_get_model_by_name_works(self) -> None:
        """get_model_by_name() resolves a test model without error."""
        from pydantic_ai.models.test import TestModel

        result = ModelFactory.get_model_by_name("test:model")
        assert isinstance(result, TestModel)
