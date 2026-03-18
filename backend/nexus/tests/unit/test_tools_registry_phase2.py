"""Unit tests for Phase 2 tool registry updates."""

from __future__ import annotations

from nexus.db.models import AgentRole
from nexus.tools.adapter import (
    tool_file_read,
    tool_file_write,
    tool_git_push,
    tool_memory_read,
    tool_send_email,
    tool_web_fetch,
    tool_web_search,
)
from nexus.tools.registry import (
    IRREVERSIBLE_TOOLS,
    get_tools_for_role,
    is_irreversible,
)


def test_engineer_tools() -> None:
    """Engineer should have code, file, search, and git tools."""
    tools = get_tools_for_role(AgentRole.ENGINEER)
    tool_names = {t.__name__ for t in tools}
    assert tool_names == {
        "tool_web_search",
        "tool_file_read",
        "tool_code_execute",
        "tool_file_write",
        "tool_git_push",
    }


def test_analyst_tools() -> None:
    """Analyst should have search, fetch, file read, and file write tools."""
    tools = get_tools_for_role(AgentRole.ANALYST)
    tool_names = {t.__name__ for t in tools}
    assert tool_names == {
        "tool_web_search",
        "tool_web_fetch",
        "tool_file_read",
        "tool_file_write",
    }


def test_writer_tools() -> None:
    """Writer should have search, file read, file write, and email tools."""
    tools = get_tools_for_role(AgentRole.WRITER)
    tool_names = {t.__name__ for t in tools}
    assert tool_names == {
        "tool_web_search",
        "tool_file_read",
        "tool_file_write",
        "tool_send_email",
    }


def test_qa_tools() -> None:
    """QA should only have read-only tools."""
    tools = get_tools_for_role(AgentRole.QA)
    tool_names = {t.__name__ for t in tools}
    assert tool_names == {"tool_file_read", "tool_web_search"}


def test_prompt_creator_tools() -> None:
    """Prompt Creator should have search, file read, and memory read."""
    tools = get_tools_for_role(AgentRole.PROMPT_CREATOR)
    tool_names = {t.__name__ for t in tools}
    assert tool_names == {
        "tool_web_search",
        "tool_file_read",
        "tool_memory_read",
    }


def test_ceo_has_no_tools() -> None:
    """CEO delegates — no direct tools."""
    tools = get_tools_for_role(AgentRole.CEO)
    assert tools == []


def test_irreversible_tools_set() -> None:
    """Irreversible tools should include file_write, git_push, send_email."""
    assert {"tool_file_write", "tool_git_push", "tool_send_email"} == IRREVERSIBLE_TOOLS


def test_is_irreversible_check() -> None:
    """is_irreversible should return True for irreversible tools."""
    assert is_irreversible(tool_file_write) is True
    assert is_irreversible(tool_git_push) is True
    assert is_irreversible(tool_send_email) is True
    assert is_irreversible(tool_web_search) is False
    assert is_irreversible(tool_file_read) is False
    assert is_irreversible(tool_web_fetch) is False
    assert is_irreversible(tool_memory_read) is False
