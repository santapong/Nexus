"""KeepSave tool functions for Nexus agents.

These are Pydantic AI tools that let Nexus agents interact with KeepSave
for secret management, API key rotation, environment promotion, and
MCP gateway calls — all with human approval for irreversible operations.

Security layers (enforced in order):
  1. registry.py — controls which tools each role has access to
  2. rbac.py — controls which SECRETS and OPERATIONS each role can touch
  3. guards.py — requires human approval for irreversible operations
  4. KeepSave-side — promotion approval for PROD changes

Tool functions receive `_agent_role` from the agent runtime context.
If no role is provided (e.g. in tests), RBAC is skipped with a warning.
"""

from __future__ import annotations

import json

import structlog

from nexus.db.models import AgentRole
from nexus.integrations.keepsave.client import get_keepsave_client
from nexus.integrations.keepsave.rbac import (
    KeepSaveAccessDeniedError,
    KeepSaveOperation,
    check_operation,
    check_promote_target,
    check_secret_read,
    check_secret_write,
    filter_secrets_for_role,
)

logger = structlog.get_logger()


def _get_role(agent_role: str) -> AgentRole | None:
    """Parse agent role string, return None if invalid or empty."""
    if not agent_role:
        return None
    try:
        return AgentRole(agent_role.lower())
    except ValueError:
        return None


# ─── READ-ONLY tools (no Nexus approval needed) ─────────────────────────────


async def tool_keepsave_list_secrets(
    environment: str = "",
    _agent_role: str = "",
) -> str:
    """List all secrets stored in KeepSave for the current NEXUS project.

    Use this to see what API keys and configuration values are available.
    Returns secret names and metadata only — values are NOT exposed.
    Results are filtered based on your agent role's access level.

    Args:
        environment: Environment to query (alpha, uat, prod). Defaults to current.

    Returns:
        Formatted list of secret names, descriptions, and last-updated timestamps.
    """
    try:
        role = _get_role(_agent_role)
        if role:
            check_operation(role, KeepSaveOperation.READ_SECRET)

        client = get_keepsave_client()
        env = environment if environment else None
        secrets = await client.list_secrets(env)
        if not secrets:
            return "No secrets found in KeepSave for this environment."

        # RBAC: filter to only secrets this role can see
        if role:
            secrets = filter_secrets_for_role(role, secrets)
            if not secrets:
                return f"No secrets visible for your role ({role}) in this environment."

        lines = [f"Secrets in {environment or client.environment} (filtered for {role or 'all'}):"]
        for s in secrets:
            desc = s.get("description", "")
            updated = s.get("updated_at", s.get("created_at", "unknown"))
            lines.append(f"  - {s['key']} (id: {s.get('id', 'n/a')}, updated: {updated})")
            if desc:
                lines.append(f"    Description: {desc}")
        return "\n".join(lines)
    except KeepSaveAccessDeniedError as exc:
        return f"RBAC denied: {exc}"
    except Exception as exc:
        logger.error("keepsave_list_secrets_failed", error=str(exc))
        return f"Failed to list secrets: {exc}"


async def tool_keepsave_get_secret_info(
    secret_key: str,
    environment: str = "",
    _agent_role: str = "",
) -> str:
    """Get metadata about a specific secret in KeepSave (NOT the value).

    Returns the secret's ID, version count, description, and timestamps.
    Does NOT return the actual secret value for security reasons.
    Access is controlled by your agent role's RBAC scope.

    Args:
        secret_key: The name of the secret (e.g. ANTHROPIC_API_KEY).
        environment: Environment to query. Defaults to current.

    Returns:
        Secret metadata including ID, version, and timestamps.
    """
    try:
        role = _get_role(_agent_role)
        if role:
            check_operation(role, KeepSaveOperation.READ_SECRET)
            check_secret_read(role, secret_key)

        client = get_keepsave_client()
        env = environment if environment else None
        secret = await client.get_secret(secret_key, env)
        if "error" in secret:
            return secret["error"]
        return (
            f"Secret: {secret.get('key', secret_key)}\n"
            f"  ID: {secret.get('id', 'n/a')}\n"
            f"  Environment: {environment or client.environment}\n"
            f"  Version: {secret.get('version', 'n/a')}\n"
            f"  Description: {secret.get('description', 'n/a')}\n"
            f"  Created: {secret.get('created_at', 'n/a')}\n"
            f"  Updated: {secret.get('updated_at', 'n/a')}"
        )
    except KeepSaveAccessDeniedError as exc:
        return f"RBAC denied: {exc}"
    except Exception as exc:
        logger.error("keepsave_get_secret_info_failed", error=str(exc))
        return f"Failed to get secret info: {exc}"


async def tool_keepsave_get_secret_versions(
    secret_key: str,
    environment: str = "",
    _agent_role: str = "",
) -> str:
    """Get version history for a secret in KeepSave.

    Useful for tracking when a secret was last rotated and by whom.

    Args:
        secret_key: The name of the secret (e.g. ANTHROPIC_API_KEY).
        environment: Environment to query. Defaults to current.

    Returns:
        List of versions with timestamps and authorship.
    """
    try:
        role = _get_role(_agent_role)
        if role:
            check_operation(role, KeepSaveOperation.READ_SECRET)
            check_secret_read(role, secret_key)

        client = get_keepsave_client()
        env = environment if environment else None
        secret = await client.get_secret(secret_key, env)
        if "error" in secret:
            return secret["error"]
        secret_id = secret.get("id")
        if not secret_id:
            return f"Could not find ID for secret '{secret_key}'"
        versions = await client.get_secret_versions(secret_id)
        if not versions:
            return f"No version history found for '{secret_key}'."
        lines = [f"Version history for {secret_key}:"]
        for v in versions:
            lines.append(
                f"  v{v.get('version', '?')} — "
                f"created: {v.get('created_at', 'unknown')}"
            )
        return "\n".join(lines)
    except KeepSaveAccessDeniedError as exc:
        return f"RBAC denied: {exc}"
    except Exception as exc:
        logger.error("keepsave_get_versions_failed", error=str(exc))
        return f"Failed to get versions: {exc}"


async def tool_keepsave_preview_promotion(
    source_environment: str,
    target_environment: str,
    _agent_role: str = "",
) -> str:
    """Preview what would change if secrets are promoted between environments.

    This is a dry run — no changes are applied. Shows which secrets would
    be added, updated, or remain unchanged in the target environment.

    Args:
        source_environment: Source env (e.g. alpha, uat).
        target_environment: Target env (e.g. uat, prod).

    Returns:
        Diff showing what would change in the target environment.
    """
    try:
        role = _get_role(_agent_role)
        if role:
            check_operation(role, KeepSaveOperation.READ_SECRET)

        client = get_keepsave_client()
        diff = await client.promote_diff(source_environment, target_environment)
        preview = json.dumps(diff, indent=2)
        return f"Promotion preview ({source_environment} → {target_environment}):\n{preview}"
    except KeepSaveAccessDeniedError as exc:
        return f"RBAC denied: {exc}"
    except Exception as exc:
        logger.error("keepsave_preview_promotion_failed", error=str(exc))
        return f"Failed to preview promotion: {exc}"


async def tool_keepsave_list_promotions(_agent_role: str = "") -> str:
    """List recent promotion history for the NEXUS project in KeepSave.

    Returns:
        List of past promotions with status, source/target env, and timestamps.
    """
    try:
        role = _get_role(_agent_role)
        if role:
            check_operation(role, KeepSaveOperation.READ_SECRET)

        client = get_keepsave_client()
        promotions = await client.list_promotions()
        if not promotions:
            return "No promotion history found."
        lines = ["Promotion history:"]
        for p in promotions:
            lines.append(
                f"  - {p.get('source_environment')} → {p.get('target_environment')} "
                f"[{p.get('status', 'unknown')}] "
                f"by {p.get('requested_by', 'unknown')} "
                f"at {p.get('created_at', 'unknown')}"
            )
        return "\n".join(lines)
    except KeepSaveAccessDeniedError as exc:
        return f"RBAC denied: {exc}"
    except Exception as exc:
        logger.error("keepsave_list_promotions_failed", error=str(exc))
        return f"Failed to list promotions: {exc}"


async def tool_keepsave_audit_log(limit: int = 20, _agent_role: str = "") -> str:
    """View the KeepSave audit log for the NEXUS project.

    Shows who accessed or modified secrets, when, and what action was taken.

    Args:
        limit: Maximum number of audit entries to return (default 20).

    Returns:
        Recent audit log entries.
    """
    try:
        role = _get_role(_agent_role)
        if role:
            check_operation(role, KeepSaveOperation.VIEW_AUDIT)

        client = get_keepsave_client()
        entries = await client.get_audit_log(limit=limit)
        if not entries:
            return "No audit log entries found."
        lines = ["KeepSave audit log (recent):"]
        for e in entries:
            lines.append(
                f"  [{e.get('created_at', '?')}] "
                f"{e.get('action', '?')} on {e.get('resource_type', '?')} "
                f"by user {e.get('user_id', 'unknown')}"
            )
        return "\n".join(lines)
    except KeepSaveAccessDeniedError as exc:
        return f"RBAC denied: {exc}"
    except Exception as exc:
        logger.error("keepsave_audit_log_failed", error=str(exc))
        return f"Failed to get audit log: {exc}"


async def tool_keepsave_mcp_list_tools(_agent_role: str = "") -> str:
    """List all available tools hosted on KeepSave's MCP Server Hub.

    Discovers tools from all installed MCP servers, including external
    services like MedQCNN. Secrets are auto-injected by the gateway.

    Returns:
        List of available MCP tools with descriptions and server info.
    """
    try:
        role = _get_role(_agent_role)
        if role:
            check_operation(role, KeepSaveOperation.MCP_LIST)

        client = get_keepsave_client()
        tools = await client.mcp_list_tools()
        if not tools:
            return "No MCP tools available on KeepSave gateway."
        lines = ["Available MCP tools via KeepSave gateway:"]
        for t in tools:
            lines.append(
                f"  - {t.get('name', '?')}: {t.get('description', 'no description')}"
                f"  (server: {t.get('server_name', '?')})"
            )
        return "\n".join(lines)
    except KeepSaveAccessDeniedError as exc:
        return f"RBAC denied: {exc}"
    except Exception as exc:
        logger.error("keepsave_mcp_list_tools_failed", error=str(exc))
        return f"Failed to list MCP tools: {exc}"


# ─── IRREVERSIBLE tools (require Nexus human approval) ──────────────────────
# These are marked in IRREVERSIBLE_TOOLS in registry.py.
# Approval is enforced by the agent guard chain, not in these functions.
# RBAC is enforced HERE, before the KeepSave API call.
# Additionally, KeepSave enforces its own approval for PROD promotions.


async def tool_keepsave_update_secret(
    secret_key: str,
    new_value: str,
    environment: str = "",
    reason: str = "",
    _agent_role: str = "",
) -> str:
    """Update (rotate) a secret value in KeepSave. REQUIRES HUMAN APPROVAL.

    Creates a new version of the secret. The old version is preserved
    in KeepSave's version history for rollback.

    Use this when you need to rotate an API key, update a database URL,
    or change any sensitive configuration value.

    Access is restricted by your role:
      - CEO: can update all secrets
      - Engineer: can update LLM API keys and cost settings only

    Args:
        secret_key: Name of the secret to update (e.g. ANTHROPIC_API_KEY).
        new_value: The new secret value.
        environment: Environment to update. Defaults to current.
        reason: Why this secret is being updated (logged in audit trail).

    Returns:
        Confirmation with the new version number.
    """
    try:
        role = _get_role(_agent_role)
        if role:
            check_operation(role, KeepSaveOperation.WRITE_SECRET)
            check_secret_write(role, secret_key)

        client = get_keepsave_client()
        env = environment if environment else None
        secret = await client.get_secret(secret_key, env)
        if "error" in secret:
            return secret["error"]
        secret_id = secret.get("id")
        if not secret_id:
            return f"Could not find ID for secret '{secret_key}'"

        result = await client.update_secret(secret_id, new_value)
        logger.info(
            "keepsave_secret_updated",
            secret_key=secret_key,
            environment=environment or client.environment,
            agent_role=_agent_role,
            reason=reason,
        )
        version = result.get("version", "unknown")
        return (
            f"Secret '{secret_key}' updated successfully.\n"
            f"  New version: {version}\n"
            f"  Environment: {environment or client.environment}\n"
            f"  Updated by: {_agent_role or 'unknown'}\n"
            f"  Reason: {reason}\n"
            f"  Note: Restart NEXUS to load the new value."
        )
    except KeepSaveAccessDeniedError as exc:
        return f"RBAC denied: {exc}"
    except Exception as exc:
        logger.error("keepsave_update_secret_failed", error=str(exc))
        return f"Failed to update secret: {exc}"


async def tool_keepsave_create_secret(
    secret_key: str,
    value: str,
    environment: str = "",
    description: str = "",
    _agent_role: str = "",
) -> str:
    """Create a new secret in KeepSave. REQUIRES HUMAN APPROVAL.

    Stores a new encrypted secret in the KeepSave vault for the NEXUS project.
    Access is restricted by your role's write scope.

    Args:
        secret_key: Name for the new secret (e.g. NEW_SERVICE_API_KEY).
        value: The secret value to store.
        environment: Environment to create in. Defaults to current.
        description: Description of what this secret is for.

    Returns:
        Confirmation with the new secret's ID.
    """
    try:
        role = _get_role(_agent_role)
        if role:
            check_operation(role, KeepSaveOperation.CREATE_SECRET)
            check_secret_write(role, secret_key)

        client = get_keepsave_client()
        env = environment if environment else None
        result = await client.create_secret(
            key=secret_key,
            value=value,
            environment=env,
            description=description,
        )
        logger.info(
            "keepsave_secret_created",
            secret_key=secret_key,
            environment=environment or client.environment,
            agent_role=_agent_role,
        )
        return (
            f"Secret '{secret_key}' created successfully.\n"
            f"  ID: {result.get('id', 'n/a')}\n"
            f"  Environment: {environment or client.environment}\n"
            f"  Created by: {_agent_role or 'unknown'}\n"
            f"  Description: {description}"
        )
    except KeepSaveAccessDeniedError as exc:
        return f"RBAC denied: {exc}"
    except Exception as exc:
        logger.error("keepsave_create_secret_failed", error=str(exc))
        return f"Failed to create secret: {exc}"


async def tool_keepsave_promote_environment(
    source_environment: str,
    target_environment: str,
    notes: str = "",
    _agent_role: str = "",
) -> str:
    """Promote secrets from one environment to another. REQUIRES HUMAN APPROVAL.

    Copies all secrets from the source environment to the target.
    For promotions to PROD, KeepSave also requires its own approval
    (dual approval: Nexus + KeepSave).

    Access is restricted by role:
      - CEO: can promote to uat and prod
      - Engineer: can promote to uat only
      - All others: no promotion rights

    Args:
        source_environment: Source env (alpha or uat).
        target_environment: Target env (uat or prod).
        notes: Reason for the promotion (recorded in audit trail).

    Returns:
        Promotion result or pending approval status.
    """
    try:
        role = _get_role(_agent_role)
        if role:
            check_operation(role, KeepSaveOperation.PROMOTE)
            check_promote_target(role, target_environment)

        client = get_keepsave_client()
        result = await client.promote(
            source_environment=source_environment,
            target_environment=target_environment,
            notes=notes,
        )
        status = result.get("status", "unknown")
        promotion_id = result.get("id", "n/a")
        logger.info(
            "keepsave_promotion_requested",
            source=source_environment,
            target=target_environment,
            status=status,
            promotion_id=promotion_id,
            agent_role=_agent_role,
        )

        if status == "pending":
            return (
                f"Promotion {source_environment} → {target_environment} "
                f"requires KeepSave-side approval.\n"
                f"  Promotion ID: {promotion_id}\n"
                f"  Status: PENDING — waiting for KeepSave admin to approve.\n"
                f"  Requested by: {_agent_role or 'unknown'}\n"
                f"  Notes: {notes}\n"
                f"  Action: An admin must approve this in the KeepSave dashboard "
                f"or via POST /promotions/{promotion_id}/approve"
            )

        return (
            f"Promotion {source_environment} → {target_environment} completed.\n"
            f"  Promotion ID: {promotion_id}\n"
            f"  Status: {status}\n"
            f"  Requested by: {_agent_role or 'unknown'}\n"
            f"  Notes: {notes}"
        )
    except KeepSaveAccessDeniedError as exc:
        return f"RBAC denied: {exc}"
    except Exception as exc:
        logger.error("keepsave_promote_failed", error=str(exc))
        return f"Failed to promote: {exc}"


async def tool_keepsave_mcp_call(
    tool_name: str,
    arguments: str = "{}",
    _agent_role: str = "",
) -> str:
    """Call a tool on a KeepSave-hosted MCP server. REQUIRES HUMAN APPROVAL.

    Routes the call through KeepSave's MCP Gateway, which automatically
    injects the required secrets (API keys, credentials) into the tool's
    execution environment. You don't need to provide any secrets.

    Use tool_keepsave_mcp_list_tools() first to discover available tools.

    Args:
        tool_name: Name of the MCP tool to call (e.g. 'diagnose', 'analyze').
        arguments: JSON string of tool arguments.

    Returns:
        The tool's execution result.
    """
    try:
        role = _get_role(_agent_role)
        if role:
            check_operation(role, KeepSaveOperation.MCP_CALL)
    except KeepSaveAccessDeniedError as exc:
        return f"RBAC denied: {exc}"

    try:
        import json as json_mod

        args = json_mod.loads(arguments) if isinstance(arguments, str) else arguments
    except (json.JSONDecodeError, TypeError):
        return f"Invalid JSON arguments: {arguments}"

    try:
        client = get_keepsave_client()
        result = await client.mcp_call_tool(tool_name, args)
        if isinstance(result, dict) and "error" in result:
            return f"MCP tool error: {result['error']}"
        return json.dumps(result, indent=2) if isinstance(result, dict) else str(result)
    except Exception as exc:
        logger.error("keepsave_mcp_call_failed", tool_name=tool_name, error=str(exc))
        return f"MCP gateway call failed: {exc}"
