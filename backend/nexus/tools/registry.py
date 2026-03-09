"""Per-role tool access map. Enforced at agent construction time.

Each agent role has a list of tools it is allowed to use.
Tools in IRREVERSIBLE_TOOLS require human approval before execution.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nexus.db.models import AgentRole
from nexus.tools.adapter import (
    tool_code_execute,
    tool_file_read,
    tool_file_write,
    tool_git_push,
    tool_memory_read,
    tool_send_email,
    tool_web_fetch,
    tool_web_search,
)

# Tools that require human approval before execution
IRREVERSIBLE_TOOLS: set[str] = {
    "tool_file_write",
    "tool_git_push",
    "tool_send_email",
}

# Per-role tool access map — matches CLAUDE.md §8
TOOL_REGISTRY: dict[AgentRole, list[Callable[..., Any]]] = {
    AgentRole.CEO: [],
    AgentRole.ENGINEER: [
        tool_web_search, tool_file_read, tool_code_execute,
        tool_file_write, tool_git_push,
    ],
    AgentRole.ANALYST: [
        tool_web_search, tool_web_fetch, tool_file_read, tool_file_write,
    ],
    AgentRole.WRITER: [
        tool_web_search, tool_file_read, tool_file_write, tool_send_email,
    ],
    AgentRole.QA: [tool_file_read, tool_web_search],
    AgentRole.PROMPT_CREATOR: [tool_web_search, tool_file_read, tool_memory_read],
}


def get_tools_for_role(role: AgentRole) -> list[Callable[..., Any]]:
    """Get the list of tools allowed for a given agent role.

    Args:
        role: The agent's role.

    Returns:
        List of tool callables for this role.
    """
    return TOOL_REGISTRY.get(role, [])


def is_irreversible(tool_fn: Callable[..., Any]) -> bool:
    """Check if a tool function is irreversible (requires approval).

    Args:
        tool_fn: The tool function to check.

    Returns:
        True if the tool requires human approval.
    """
    return tool_fn.__name__ in IRREVERSIBLE_TOOLS
