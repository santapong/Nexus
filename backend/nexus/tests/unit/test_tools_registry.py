"""Unit tests for tools registry."""

from __future__ import annotations

from nexus.db.models import AgentRole
from nexus.tools.adapter import tool_code_execute, tool_file_read, tool_file_write, tool_web_search
from nexus.tools.registry import get_tools_for_role, is_irreversible


def test_ceo_has_no_tools() -> None:
    """CEO agent should not have any tools."""
    tools = get_tools_for_role(AgentRole.CEO)
    assert tools == []


def test_engineer_has_all_tools() -> None:
    """Engineer should have web_search, file_read, code_execute, file_write."""
    tools = get_tools_for_role(AgentRole.ENGINEER)
    assert tool_web_search in tools
    assert tool_file_read in tools
    assert tool_code_execute in tools
    assert tool_file_write in tools


def test_qa_has_read_only_tools() -> None:
    """QA should only have read-only tools."""
    tools = get_tools_for_role(AgentRole.QA)
    assert tool_file_read in tools
    assert tool_web_search in tools
    assert tool_file_write not in tools
    assert tool_code_execute not in tools


def test_file_write_is_irreversible() -> None:
    """file_write should be marked as irreversible."""
    assert is_irreversible(tool_file_write) is True


def test_file_read_is_not_irreversible() -> None:
    """file_read should not be irreversible."""
    assert is_irreversible(tool_file_read) is False
