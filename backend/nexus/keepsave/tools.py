"""KeepSave tool functions for Nexus agents.

These are Pydantic AI tools that let Nexus agents interact with KeepSave
for secret management, API key rotation, environment promotion, and
MCP gateway calls — all with human approval for irreversible operations.

Tool classification:
  - READ-ONLY: list/get secrets, view audit log, preview promotions
  - IRREVERSIBLE: create/update secrets, promote environments, rotate API keys
    (these require Nexus-side human approval via guards.py, AND
     KeepSave-side approval for PROD promotions)
"""

from __future__ import annotations

import json

import structlog

from nexus.keepsave.client import get_keepsave_client

logger = structlog.get_logger()


# ─── READ-ONLY tools (no Nexus approval needed) ─────────────────────────────


async def tool_keepsave_list_secrets(environment: str = "") -> str:
    """List all secrets stored in KeepSave for the current NEXUS project.

    Use this to see what API keys and configuration values are available.
    Returns secret names and metadata only — values are NOT exposed.

    Args:
        environment: Environment to query (alpha, uat, prod). Defaults to current.

    Returns:
        Formatted list of secret names, descriptions, and last-updated timestamps.
    """
    try:
        client = get_keepsave_client()
        env = environment if environment else None
        secrets = await client.list_secrets(env)
        if not secrets:
            return "No secrets found in KeepSave for this environment."
        lines = [f"Secrets in {environment or client.environment}:"]
        for s in secrets:
            desc = s.get("description", "")
            updated = s.get("updated_at", s.get("created_at", "unknown"))
            lines.append(f"  - {s['key']} (id: {s.get('id', 'n/a')}, updated: {updated})")
            if desc:
                lines.append(f"    Description: {desc}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("keepsave_list_secrets_failed", error=str(exc))
        return f"Failed to list secrets: {exc}"


async def tool_keepsave_get_secret_info(secret_key: str, environment: str = "") -> str:
    """Get metadata about a specific secret in KeepSave (NOT the value).

    Returns the secret's ID, version count, description, and timestamps.
    Does NOT return the actual secret value for security reasons.

    Args:
        secret_key: The name of the secret (e.g. ANTHROPIC_API_KEY).
        environment: Environment to query. Defaults to current.

    Returns:
        Secret metadata including ID, version, and timestamps.
    """
    try:
        client = get_keepsave_client()
        env = environment if environment else None
        secret = await client.get_secret(secret_key, env)
        if "error" in secret:
            return secret["error"]
        # Return metadata only — never the value
        return (
            f"Secret: {secret.get('key', secret_key)}\n"
            f"  ID: {secret.get('id', 'n/a')}\n"
            f"  Environment: {environment or client.environment}\n"
            f"  Version: {secret.get('version', 'n/a')}\n"
            f"  Description: {secret.get('description', 'n/a')}\n"
            f"  Created: {secret.get('created_at', 'n/a')}\n"
            f"  Updated: {secret.get('updated_at', 'n/a')}"
        )
    except Exception as exc:
        logger.error("keepsave_get_secret_info_failed", error=str(exc))
        return f"Failed to get secret info: {exc}"


async def tool_keepsave_get_secret_versions(secret_key: str, environment: str = "") -> str:
    """Get version history for a secret in KeepSave.

    Useful for tracking when a secret was last rotated and by whom.

    Args:
        secret_key: The name of the secret (e.g. ANTHROPIC_API_KEY).
        environment: Environment to query. Defaults to current.

    Returns:
        List of versions with timestamps and authorship.
    """
    try:
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
    except Exception as exc:
        logger.error("keepsave_get_versions_failed", error=str(exc))
        return f"Failed to get versions: {exc}"


async def tool_keepsave_preview_promotion(
    source_environment: str,
    target_environment: str,
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
        client = get_keepsave_client()
        diff = await client.promote_diff(source_environment, target_environment)
        return f"Promotion preview ({source_environment} → {target_environment}):\n{json.dumps(diff, indent=2)}"
    except Exception as exc:
        logger.error("keepsave_preview_promotion_failed", error=str(exc))
        return f"Failed to preview promotion: {exc}"


async def tool_keepsave_list_promotions() -> str:
    """List recent promotion history for the NEXUS project in KeepSave.

    Returns:
        List of past promotions with status, source/target env, and timestamps.
    """
    try:
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
    except Exception as exc:
        logger.error("keepsave_list_promotions_failed", error=str(exc))
        return f"Failed to list promotions: {exc}"


async def tool_keepsave_audit_log(limit: int = 20) -> str:
    """View the KeepSave audit log for the NEXUS project.

    Shows who accessed or modified secrets, when, and what action was taken.

    Args:
        limit: Maximum number of audit entries to return (default 20).

    Returns:
        Recent audit log entries.
    """
    try:
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
    except Exception as exc:
        logger.error("keepsave_audit_log_failed", error=str(exc))
        return f"Failed to get audit log: {exc}"


async def tool_keepsave_mcp_list_tools() -> str:
    """List all available tools hosted on KeepSave's MCP Server Hub.

    Discovers tools from all installed MCP servers, including external
    services like MedQCNN. Secrets are auto-injected by the gateway.

    Returns:
        List of available MCP tools with descriptions and server info.
    """
    try:
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
    except Exception as exc:
        logger.error("keepsave_mcp_list_tools_failed", error=str(exc))
        return f"Failed to list MCP tools: {exc}"


# ─── IRREVERSIBLE tools (require Nexus human approval) ──────────────────────
# These are marked in KEEPSAVE_IRREVERSIBLE_TOOLS in registry.py.
# Approval is enforced by the agent guard chain, not in these functions.
# Additionally, KeepSave enforces its own approval for PROD promotions.


async def tool_keepsave_update_secret(
    secret_key: str,
    new_value: str,
    environment: str = "",
    reason: str = "",
) -> str:
    """Update (rotate) a secret value in KeepSave. REQUIRES HUMAN APPROVAL.

    Creates a new version of the secret. The old version is preserved
    in KeepSave's version history for rollback.

    Use this when you need to rotate an API key, update a database URL,
    or change any sensitive configuration value.

    IMPORTANT: After updating a secret, NEXUS must be restarted to pick
    up the new value, OR the next startup will load it automatically.

    Args:
        secret_key: Name of the secret to update (e.g. ANTHROPIC_API_KEY).
        new_value: The new secret value.
        environment: Environment to update. Defaults to current.
        reason: Why this secret is being updated (logged in audit trail).

    Returns:
        Confirmation with the new version number.
    """
    try:
        client = get_keepsave_client()
        env = environment if environment else None
        # First, find the secret ID
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
            reason=reason,
        )
        version = result.get("version", "unknown")
        return (
            f"Secret '{secret_key}' updated successfully.\n"
            f"  New version: {version}\n"
            f"  Environment: {environment or client.environment}\n"
            f"  Reason: {reason}\n"
            f"  Note: Restart NEXUS to load the new value."
        )
    except Exception as exc:
        logger.error("keepsave_update_secret_failed", error=str(exc))
        return f"Failed to update secret: {exc}"


async def tool_keepsave_create_secret(
    secret_key: str,
    value: str,
    environment: str = "",
    description: str = "",
) -> str:
    """Create a new secret in KeepSave. REQUIRES HUMAN APPROVAL.

    Stores a new encrypted secret in the KeepSave vault for the NEXUS project.

    Args:
        secret_key: Name for the new secret (e.g. NEW_SERVICE_API_KEY).
        value: The secret value to store.
        environment: Environment to create in. Defaults to current.
        description: Description of what this secret is for.

    Returns:
        Confirmation with the new secret's ID.
    """
    try:
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
        )
        return (
            f"Secret '{secret_key}' created successfully.\n"
            f"  ID: {result.get('id', 'n/a')}\n"
            f"  Environment: {environment or client.environment}\n"
            f"  Description: {description}"
        )
    except Exception as exc:
        logger.error("keepsave_create_secret_failed", error=str(exc))
        return f"Failed to create secret: {exc}"


async def tool_keepsave_promote_environment(
    source_environment: str,
    target_environment: str,
    notes: str = "",
) -> str:
    """Promote secrets from one environment to another. REQUIRES HUMAN APPROVAL.

    Copies all secrets from the source environment to the target.
    For promotions to PROD, KeepSave also requires its own approval
    (dual approval: Nexus + KeepSave).

    Promotion order is enforced: alpha -> uat -> prod.
    Cannot skip environments or promote backwards.

    Args:
        source_environment: Source env (alpha or uat).
        target_environment: Target env (uat or prod).
        notes: Reason for the promotion (recorded in audit trail).

    Returns:
        Promotion result or pending approval status.
    """
    try:
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
        )

        if status == "pending":
            return (
                f"Promotion {source_environment} → {target_environment} "
                f"requires KeepSave-side approval.\n"
                f"  Promotion ID: {promotion_id}\n"
                f"  Status: PENDING — waiting for KeepSave admin to approve.\n"
                f"  Notes: {notes}\n"
                f"  Action: An admin must approve this in the KeepSave dashboard "
                f"or via POST /promotions/{promotion_id}/approve"
            )

        return (
            f"Promotion {source_environment} → {target_environment} completed.\n"
            f"  Promotion ID: {promotion_id}\n"
            f"  Status: {status}\n"
            f"  Notes: {notes}"
        )
    except Exception as exc:
        logger.error("keepsave_promote_failed", error=str(exc))
        return f"Failed to promote: {exc}"


async def tool_keepsave_mcp_call(
    tool_name: str,
    arguments: str = "{}",
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
