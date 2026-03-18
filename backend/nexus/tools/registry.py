"""Per-role tool access map. Enforced at agent construction time.

Each agent role has a list of tools it is allowed to use.
Tools in IRREVERSIBLE_TOOLS require human approval before execution.
KeepSave tools provide secret management and MCP gateway access.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nexus.db.models import AgentRole
from nexus.keepsave.tools import (
    tool_keepsave_audit_log,
    tool_keepsave_create_secret,
    tool_keepsave_get_secret_info,
    tool_keepsave_get_secret_versions,
    tool_keepsave_list_promotions,
    tool_keepsave_list_secrets,
    tool_keepsave_mcp_call,
    tool_keepsave_mcp_list_tools,
    tool_keepsave_preview_promotion,
    tool_keepsave_promote_environment,
    tool_keepsave_update_secret,
)
from nexus.tools.adapter import (
    tool_code_execute,
    tool_file_read,
    tool_file_write,
    tool_git_push,
    tool_hire_external_agent,
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
    "tool_hire_external_agent",
    # KeepSave irreversible tools — modify secrets or trigger promotions
    "tool_keepsave_update_secret",
    "tool_keepsave_create_secret",
    "tool_keepsave_promote_environment",
    "tool_keepsave_mcp_call",
}

# KeepSave read-only tools — available to roles that need visibility
_KEEPSAVE_READ_TOOLS: list[Callable[..., Any]] = [
    tool_keepsave_list_secrets,
    tool_keepsave_get_secret_info,
    tool_keepsave_get_secret_versions,
    tool_keepsave_preview_promotion,
    tool_keepsave_list_promotions,
    tool_keepsave_audit_log,
    tool_keepsave_mcp_list_tools,
]

# KeepSave write tools — only CEO and Engineer can modify secrets
_KEEPSAVE_WRITE_TOOLS: list[Callable[..., Any]] = [
    tool_keepsave_update_secret,
    tool_keepsave_create_secret,
    tool_keepsave_promote_environment,
    tool_keepsave_mcp_call,
]

# Per-role tool access map — matches CLAUDE.md §8 + KeepSave integration
TOOL_REGISTRY: dict[AgentRole, list[Callable[..., Any]]] = {
    AgentRole.CEO: [
        tool_hire_external_agent,
        # CEO can view secrets and trigger promotions (with approval)
        *_KEEPSAVE_READ_TOOLS,
        *_KEEPSAVE_WRITE_TOOLS,
    ],
    AgentRole.ENGINEER: [
        tool_web_search,
        tool_file_read,
        tool_code_execute,
        tool_file_write,
        tool_git_push,
        tool_hire_external_agent,
        # Engineer can view secrets, update them (with approval), and call MCP tools
        *_KEEPSAVE_READ_TOOLS,
        *_KEEPSAVE_WRITE_TOOLS,
    ],
    AgentRole.ANALYST: [
        tool_web_search,
        tool_web_fetch,
        tool_file_read,
        tool_file_write,
        tool_hire_external_agent,
        # Analyst can view secrets and call MCP tools (with approval)
        *_KEEPSAVE_READ_TOOLS,
        tool_keepsave_mcp_call,
    ],
    AgentRole.WRITER: [
        tool_web_search,
        tool_file_read,
        tool_file_write,
        tool_send_email,
        tool_hire_external_agent,
    ],
    AgentRole.QA: [
        tool_file_read,
        tool_web_search,
        tool_hire_external_agent,
        # QA can view secrets for verification (read-only)
        *_KEEPSAVE_READ_TOOLS,
    ],
    AgentRole.PROMPT_CREATOR: [
        tool_web_search,
        tool_file_read,
        tool_memory_read,
    ],
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
