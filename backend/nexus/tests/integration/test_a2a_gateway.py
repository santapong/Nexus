"""Integration tests for the A2A Gateway.

Tests agent card, authentication, task submission, and access control.
"""
from __future__ import annotations

from nexus.gateway.auth import (
    register_token,
    seed_dev_token,
    validate_token,
)
from nexus.gateway.schemas import AgentCard, A2ATaskRequest


class TestA2AAuthentication:
    """Tests for A2A bearer token validation."""

    def test_valid_token_accepted(self) -> None:
        """Registered token is accepted."""
        raw_token = "test-token-1234"
        register_token(raw_token, name="test")

        is_valid, error = validate_token(raw_token)
        assert is_valid is True
        assert error == ""

    def test_invalid_token_rejected(self) -> None:
        """Unregistered token is rejected."""
        is_valid, error = validate_token("nonexistent-token")
        assert is_valid is False
        assert "Invalid" in error

    def test_empty_token_rejected(self) -> None:
        """Empty token is rejected."""
        is_valid, error = validate_token("")
        assert is_valid is False
        assert "Missing" in error

    def test_expired_token_rejected(self) -> None:
        """Expired token is rejected."""
        register_token(
            "expired-token",
            name="expired",
            expires_at=1.0,  # Already expired
        )
        is_valid, error = validate_token("expired-token")
        assert is_valid is False
        assert "expired" in error.lower()

    def test_skill_access_control(self) -> None:
        """Token with limited skills can't access other skills."""
        register_token(
            "limited-token",
            name="limited",
            allowed_skills=["research"],
        )
        # Allowed skill
        is_valid, _ = validate_token("limited-token", skill_id="research")
        assert is_valid is True

        # Disallowed skill
        is_valid, error = validate_token("limited-token", skill_id="code")
        assert is_valid is False
        assert "skill" in error.lower()

    def test_wildcard_skill_access(self) -> None:
        """Token with wildcard can access all skills."""
        register_token(
            "wildcard-token",
            name="wildcard",
            allowed_skills=["*"],
        )
        is_valid, _ = validate_token("wildcard-token", skill_id="code")
        assert is_valid is True
        is_valid, _ = validate_token("wildcard-token", skill_id="research")
        assert is_valid is True

    def test_dev_token_seeder(self) -> None:
        """Dev token seeder creates a valid token."""
        raw = seed_dev_token()
        is_valid, _ = validate_token(raw)
        assert is_valid is True


class TestAgentCard:
    """Tests for the Agent Card schema."""

    def test_agent_card_has_skills(self) -> None:
        """Agent Card contains the default skills."""
        card = AgentCard()
        assert len(card.skills) >= 4
        skill_ids = [s.id for s in card.skills]
        assert "research" in skill_ids
        assert "write" in skill_ids
        assert "code" in skill_ids
        assert "general" in skill_ids

    def test_agent_card_has_auth_info(self) -> None:
        """Agent Card contains authentication info."""
        card = AgentCard()
        assert card.auth["type"] == "bearer"

    def test_agent_card_version(self) -> None:
        """Agent Card has version info."""
        card = AgentCard()
        assert card.version == "0.2.0"


class TestA2ATaskRequest:
    """Tests for task request validation."""

    def test_default_skill_is_general(self) -> None:
        """Default skill_id is 'general'."""
        req = A2ATaskRequest()
        assert req.skill_id == "general"

    def test_custom_input(self) -> None:
        """Custom input is accepted."""
        req = A2ATaskRequest(
            skill_id="research",
            input={"topic": "quantum computing", "depth": "detailed"},
            metadata={"caller": "external-agent"},
        )
        assert req.input["topic"] == "quantum computing"
        assert req.metadata["caller"] == "external-agent"
