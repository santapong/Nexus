"""Per-role tool access map. Enforced at agent construction time.

Each agent role has a list of tools it is allowed to use.
Tools in IRREVERSIBLE_TOOLS require human approval before execution.
KeepSave tools provide secret management and MCP gateway access.

Security layers (defense in depth):
  1. This file (registry.py) — controls which TOOLS each role has
  2. rbac.py — controls which SECRETS and OPERATIONS each role can touch
  3. guards.py — requires human approval for irreversible operations
  4. KeepSave-side — promotion approval for PROD changes
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nexus.db.models import AgentRole
from nexus.integrations.keepsave.tools import (
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
    tool_analyze_image,
    tool_code_execute,
    tool_create_plan,
    tool_design_api,
    tool_design_database,
    tool_design_system,
    tool_file_read,
    tool_file_write,
    tool_git_push,
    tool_hire_external_agent,
    tool_memory_read,
    tool_sandbox_execute,
    tool_sandbox_project,
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
    "tool_sandbox_project",  # Costs money + network access
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

# KeepSave write tools — CEO gets full access, Engineer gets limited
# Fine-grained secret scoping enforced by rbac.py (Layer 2)
_KEEPSAVE_CEO_WRITE_TOOLS: list[Callable[..., Any]] = [
    tool_keepsave_update_secret,
    tool_keepsave_create_secret,
    tool_keepsave_promote_environment,  # CEO: can promote to uat + prod
    tool_keepsave_mcp_call,
]

_KEEPSAVE_ENGINEER_WRITE_TOOLS: list[Callable[..., Any]] = [
    tool_keepsave_update_secret,  # RBAC limits to LLM keys + cost only
    tool_keepsave_promote_environment,  # RBAC limits to uat only (not prod)
    tool_keepsave_mcp_call,
]

# Per-role tool access map — matches CLAUDE.md §8 + KeepSave integration
# Layer 1: controls which tools each role can CALL
# Layer 2 (rbac.py): controls which secrets/operations within those tools
TOOL_REGISTRY: dict[AgentRole, list[Callable[..., Any]]] = {
    AgentRole.CEO: [
        tool_hire_external_agent,
        # Planning & design tools
        tool_create_plan,
        tool_design_system,
        tool_design_database,
        tool_design_api,
        # CEO: full KeepSave access (read + write all scopes)
        *_KEEPSAVE_READ_TOOLS,
        *_KEEPSAVE_CEO_WRITE_TOOLS,
    ],
    AgentRole.ENGINEER: [
        tool_web_search,
        tool_file_read,
        tool_code_execute,
        tool_file_write,
        tool_git_push,
        tool_hire_external_agent,
        tool_analyze_image,
        # Sandbox tools (E2B Firecracker microVM isolation)
        tool_sandbox_execute,   # Read-only: execute code snippets
        tool_sandbox_project,   # Irreversible: clone repos + run commands
        # Planning & design tools
        tool_create_plan,
        tool_design_system,
        tool_design_database,
        tool_design_api,
        # Engineer: read all visible scopes + write LLM keys/cost only (RBAC enforced)
        *_KEEPSAVE_READ_TOOLS,
        *_KEEPSAVE_ENGINEER_WRITE_TOOLS,
    ],
    AgentRole.ANALYST: [
        tool_web_search,
        tool_web_fetch,
        tool_file_read,
        tool_file_write,
        tool_hire_external_agent,
        tool_analyze_image,
        # Planning tool only (no design tools)
        tool_create_plan,
        # Analyst: read-only secrets + MCP gateway (no secret writes)
        *_KEEPSAVE_READ_TOOLS,
        tool_keepsave_mcp_call,
    ],
    AgentRole.WRITER: [
        tool_web_search,
        tool_file_read,
        tool_file_write,
        tool_send_email,
        tool_hire_external_agent,
        # Writer: no KeepSave access
    ],
    AgentRole.DIRECTOR: [
        tool_web_search,
        tool_file_read,
        # Director: read-only KeepSave for visibility
        *_KEEPSAVE_READ_TOOLS,
    ],
    AgentRole.QA: [
        tool_file_read,
        tool_web_search,
        tool_hire_external_agent,
        # QA: read-only KeepSave for verification
        *_KEEPSAVE_READ_TOOLS,
    ],
    AgentRole.PROMPT_CREATOR: [
        tool_web_search,
        tool_file_read,
        tool_memory_read,
        # Prompt Creator: no KeepSave access
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
