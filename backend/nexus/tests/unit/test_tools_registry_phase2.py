"""Unit tests pinning the per-role tool registry.

This test is intentionally strict: any future drift in
``nexus.tools.registry.TOOL_REGISTRY`` must fail this test. Adding or
removing a tool from a role requires updating both the registry AND the
expected set here — that's the whole point. We do NOT want silent grants
of irreversible tools (file_write, git_push, send_email,
hire_external_agent, sandbox_project, keepsave write tools) to roles
that didn't previously have them.

If you're updating this test, also double-check that ``IRREVERSIBLE_TOOLS``
still covers everything that needs human approval.
"""

from __future__ import annotations

from nexus.db.models import AgentRole
from nexus.tools.adapter import (
    tool_file_read,
    tool_file_write,
    tool_git_push,
    tool_hire_external_agent,
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


def test_ceo_tools() -> None:
    """CEO has no direct execution tools — it delegates — but it does have
    planning/design helpers, workspace storage, and full KeepSave access."""
    tools = get_tools_for_role(AgentRole.CEO)
    tool_names = {t.__name__ for t in tools}
    assert tool_names == {
        "tool_hire_external_agent",
        # Planning & design tools
        "tool_create_plan",
        "tool_design_system",
        "tool_design_database",
        "tool_design_api",
        # Workspace storage tools
        "tool_workspace_list",
        "tool_workspace_read",
        "tool_workspace_write",
        "tool_workspace_search",
        # KeepSave: read-only (7 tools)
        "tool_keepsave_list_secrets",
        "tool_keepsave_get_secret_info",
        "tool_keepsave_get_secret_versions",
        "tool_keepsave_preview_promotion",
        "tool_keepsave_list_promotions",
        "tool_keepsave_audit_log",
        "tool_keepsave_mcp_list_tools",
        # KeepSave: CEO write tools (4)
        "tool_keepsave_update_secret",
        "tool_keepsave_create_secret",
        "tool_keepsave_promote_environment",
        "tool_keepsave_mcp_call",
    }


def test_engineer_tools() -> None:
    """Engineer has code, file, search, git, sandbox, planning, and
    limited KeepSave write tools."""
    tools = get_tools_for_role(AgentRole.ENGINEER)
    tool_names = {t.__name__ for t in tools}
    assert tool_names == {
        "tool_web_search",
        "tool_file_read",
        "tool_code_execute",
        "tool_file_write",
        "tool_git_push",
        "tool_hire_external_agent",
        "tool_analyze_image",
        # Sandbox
        "tool_sandbox_execute",
        "tool_sandbox_project",
        # Planning & design
        "tool_create_plan",
        "tool_design_system",
        "tool_design_database",
        "tool_design_api",
        # Workspace storage
        "tool_workspace_list",
        "tool_workspace_read",
        "tool_workspace_write",
        "tool_workspace_search",
        # KeepSave: read-only (7)
        "tool_keepsave_list_secrets",
        "tool_keepsave_get_secret_info",
        "tool_keepsave_get_secret_versions",
        "tool_keepsave_preview_promotion",
        "tool_keepsave_list_promotions",
        "tool_keepsave_audit_log",
        "tool_keepsave_mcp_list_tools",
        # KeepSave: Engineer write (3 — RBAC narrows further)
        "tool_keepsave_update_secret",
        "tool_keepsave_promote_environment",
        "tool_keepsave_mcp_call",
    }


def test_analyst_tools() -> None:
    """Analyst has search, fetch, file read/write, planning, image, and
    read-only KeepSave + MCP gateway."""
    tools = get_tools_for_role(AgentRole.ANALYST)
    tool_names = {t.__name__ for t in tools}
    assert tool_names == {
        "tool_web_search",
        "tool_web_fetch",
        "tool_file_read",
        "tool_file_write",
        "tool_hire_external_agent",
        "tool_analyze_image",
        "tool_create_plan",
        # Workspace storage
        "tool_workspace_list",
        "tool_workspace_read",
        "tool_workspace_write",
        "tool_workspace_search",
        # KeepSave: read-only + MCP gateway
        "tool_keepsave_list_secrets",
        "tool_keepsave_get_secret_info",
        "tool_keepsave_get_secret_versions",
        "tool_keepsave_preview_promotion",
        "tool_keepsave_list_promotions",
        "tool_keepsave_audit_log",
        "tool_keepsave_mcp_list_tools",
        "tool_keepsave_mcp_call",
    }


def test_writer_tools() -> None:
    """Writer has search, file read/write, email, hire, and workspace tools
    — no KeepSave access."""
    tools = get_tools_for_role(AgentRole.WRITER)
    tool_names = {t.__name__ for t in tools}
    assert tool_names == {
        "tool_web_search",
        "tool_file_read",
        "tool_file_write",
        "tool_send_email",
        "tool_hire_external_agent",
        # Workspace storage
        "tool_workspace_list",
        "tool_workspace_read",
        "tool_workspace_write",
        "tool_workspace_search",
    }


def test_director_tools() -> None:
    """Director has read-only inspection tools — web search, file read,
    workspace read, and read-only KeepSave for visibility."""
    tools = get_tools_for_role(AgentRole.DIRECTOR)
    tool_names = {t.__name__ for t in tools}
    assert tool_names == {
        "tool_web_search",
        "tool_file_read",
        # Workspace storage (read-only)
        "tool_workspace_list",
        "tool_workspace_read",
        "tool_workspace_search",
        # KeepSave: read-only
        "tool_keepsave_list_secrets",
        "tool_keepsave_get_secret_info",
        "tool_keepsave_get_secret_versions",
        "tool_keepsave_preview_promotion",
        "tool_keepsave_list_promotions",
        "tool_keepsave_audit_log",
        "tool_keepsave_mcp_list_tools",
    }


def test_qa_tools() -> None:
    """QA has read-only tools + hire, workspace read, and KeepSave verification."""
    tools = get_tools_for_role(AgentRole.QA)
    tool_names = {t.__name__ for t in tools}
    assert tool_names == {
        "tool_file_read",
        "tool_web_search",
        "tool_hire_external_agent",
        # Workspace storage (read-only)
        "tool_workspace_list",
        "tool_workspace_read",
        "tool_workspace_search",
        # KeepSave: read-only
        "tool_keepsave_list_secrets",
        "tool_keepsave_get_secret_info",
        "tool_keepsave_get_secret_versions",
        "tool_keepsave_preview_promotion",
        "tool_keepsave_list_promotions",
        "tool_keepsave_audit_log",
        "tool_keepsave_mcp_list_tools",
    }


def test_prompt_creator_tools() -> None:
    """Prompt Creator has search, file read, memory read, and workspace read
    — no KeepSave access (and notably no irreversible tools)."""
    tools = get_tools_for_role(AgentRole.PROMPT_CREATOR)
    tool_names = {t.__name__ for t in tools}
    assert tool_names == {
        "tool_web_search",
        "tool_file_read",
        "tool_memory_read",
        # Workspace storage (read-only)
        "tool_workspace_list",
        "tool_workspace_read",
        "tool_workspace_search",
    }


def test_irreversible_tools_set() -> None:
    """The IRREVERSIBLE_TOOLS set must cover every tool that mutates state
    outside NEXUS (filesystem, git, email, external agents, sandbox projects,
    workspace storage, KeepSave writes / promotions / MCP gateway).

    Any future addition must be reflected here so the approval guard chain
    actually covers it."""
    assert {
        "tool_file_write",
        "tool_git_push",
        "tool_send_email",
        "tool_hire_external_agent",
        "tool_sandbox_project",
        "tool_workspace_write",
        "tool_keepsave_update_secret",
        "tool_keepsave_create_secret",
        "tool_keepsave_promote_environment",
        "tool_keepsave_mcp_call",
    } == IRREVERSIBLE_TOOLS


def test_is_irreversible_check() -> None:
    """is_irreversible() must return True for every irreversible tool and
    False for every read-only tool."""
    # Irreversible
    assert is_irreversible(tool_file_write) is True
    assert is_irreversible(tool_git_push) is True
    assert is_irreversible(tool_send_email) is True
    assert is_irreversible(tool_hire_external_agent) is True
    # Read-only
    assert is_irreversible(tool_web_search) is False
    assert is_irreversible(tool_file_read) is False
    assert is_irreversible(tool_web_fetch) is False
    assert is_irreversible(tool_memory_read) is False
