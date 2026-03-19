"""KeepSave RBAC — per-role secret access policies.

Controls WHICH secrets each agent role can read or modify,
and WHICH KeepSave operations each role can perform.

This is the second layer of defense:
  Layer 1: registry.py — controls which TOOLS each role has
  Layer 2: rbac.py (this) — controls which SECRETS each role can touch
  Layer 3: guards.py — requires human approval for irreversible ops
  Layer 4: KeepSave-side — promotion approval for PROD

Example:
  Engineer has tool_keepsave_update_secret → but RBAC only allows
  updating LLM API keys and cost settings — NOT JWT_SECRET_KEY or
  DATABASE_URL (those are CEO-only).
"""

from __future__ import annotations

from enum import StrEnum

import structlog

from nexus.db.models import AgentRole

logger = structlog.get_logger()


class SecretScope(StrEnum):
    """Categories of secrets for RBAC scoping."""

    LLM_KEYS = "llm_keys"                # ANTHROPIC_API_KEY, GOOGLE_API_KEY, etc.
    INFRASTRUCTURE = "infrastructure"      # DATABASE_URL, REDIS_URL, KAFKA_*
    AUTH = "auth"                          # JWT_SECRET_KEY, A2A_INBOUND_TOKEN
    COST_CONTROLS = "cost_controls"        # DAILY_SPEND_LIMIT_USD, TOKEN_BUDGET
    EXTERNAL_SERVICES = "external"         # TEMPORAL_HOST, LANGFUSE_*, KEEPSAVE_*
    MCP = "mcp"                            # MCP gateway operations
    PROMOTION = "promotion"                # Environment promotion operations


class KeepSaveOperation(StrEnum):
    """Types of KeepSave operations for RBAC."""

    READ_SECRET = "read_secret"
    WRITE_SECRET = "write_secret"
    CREATE_SECRET = "create_secret"
    PROMOTE = "promote"
    VIEW_AUDIT = "view_audit"
    MCP_CALL = "mcp_call"
    MCP_LIST = "mcp_list"


# ── Secret-to-scope mapping ────────────────────────────────────────────────

# Maps secret key patterns to their scope category.
# Patterns are matched as prefixes (e.g. "ANTHROPIC" matches "ANTHROPIC_API_KEY").
_SECRET_SCOPE_MAP: dict[str, SecretScope] = {
    "ANTHROPIC_API_KEY": SecretScope.LLM_KEYS,
    "GOOGLE_API_KEY": SecretScope.LLM_KEYS,
    "OPENAI_API_KEY": SecretScope.LLM_KEYS,
    "GROQ_API_KEY": SecretScope.LLM_KEYS,
    "MISTRAL_API_KEY": SecretScope.LLM_KEYS,
    "OLLAMA_": SecretScope.LLM_KEYS,
    "DATABASE_URL": SecretScope.INFRASTRUCTURE,
    "REDIS_URL": SecretScope.INFRASTRUCTURE,
    "KAFKA_": SecretScope.INFRASTRUCTURE,
    "JWT_SECRET_KEY": SecretScope.AUTH,
    "JWT_ALGORITHM": SecretScope.AUTH,
    "A2A_INBOUND_TOKEN": SecretScope.AUTH,
    "DAILY_SPEND_LIMIT_USD": SecretScope.COST_CONTROLS,
    "DEFAULT_TOKEN_BUDGET": SecretScope.COST_CONTROLS,
    "TEMPORAL_": SecretScope.EXTERNAL_SERVICES,
    "LANGFUSE_": SecretScope.EXTERNAL_SERVICES,
    "KEEPSAVE_": SecretScope.EXTERNAL_SERVICES,
}


def _classify_secret(secret_key: str) -> SecretScope | None:
    """Determine which scope a secret belongs to."""
    upper_key = secret_key.upper()
    for pattern, scope in _SECRET_SCOPE_MAP.items():
        if upper_key == pattern or upper_key.startswith(pattern):
            return scope
    return None


# ── Per-role RBAC policies ──────────────────────────────────────────────────

# Which secret scopes each role can READ (view metadata, list, versions)
_ROLE_READ_SCOPES: dict[AgentRole, set[SecretScope]] = {
    AgentRole.CEO: {
        SecretScope.LLM_KEYS,
        SecretScope.INFRASTRUCTURE,
        SecretScope.AUTH,
        SecretScope.COST_CONTROLS,
        SecretScope.EXTERNAL_SERVICES,
    },
    AgentRole.ENGINEER: {
        SecretScope.LLM_KEYS,
        SecretScope.COST_CONTROLS,
        SecretScope.EXTERNAL_SERVICES,
    },
    AgentRole.ANALYST: {
        SecretScope.LLM_KEYS,
        SecretScope.COST_CONTROLS,
    },
    AgentRole.QA: {
        SecretScope.LLM_KEYS,
        SecretScope.COST_CONTROLS,
    },
    AgentRole.WRITER: set(),
    AgentRole.PROMPT_CREATOR: set(),
}

# Which secret scopes each role can WRITE (update, create)
_ROLE_WRITE_SCOPES: dict[AgentRole, set[SecretScope]] = {
    AgentRole.CEO: {
        SecretScope.LLM_KEYS,
        SecretScope.AUTH,
        SecretScope.COST_CONTROLS,
        SecretScope.INFRASTRUCTURE,
        SecretScope.EXTERNAL_SERVICES,
    },
    AgentRole.ENGINEER: {
        SecretScope.LLM_KEYS,
        SecretScope.COST_CONTROLS,
    },
    # All other roles: no write access to secrets
    AgentRole.ANALYST: set(),
    AgentRole.QA: set(),
    AgentRole.WRITER: set(),
    AgentRole.PROMPT_CREATOR: set(),
}

# Which operations each role can perform
_ROLE_OPERATIONS: dict[AgentRole, set[KeepSaveOperation]] = {
    AgentRole.CEO: {
        KeepSaveOperation.READ_SECRET,
        KeepSaveOperation.WRITE_SECRET,
        KeepSaveOperation.CREATE_SECRET,
        KeepSaveOperation.PROMOTE,
        KeepSaveOperation.VIEW_AUDIT,
        KeepSaveOperation.MCP_CALL,
        KeepSaveOperation.MCP_LIST,
    },
    AgentRole.ENGINEER: {
        KeepSaveOperation.READ_SECRET,
        KeepSaveOperation.WRITE_SECRET,
        KeepSaveOperation.VIEW_AUDIT,
        KeepSaveOperation.MCP_CALL,
        KeepSaveOperation.MCP_LIST,
    },
    AgentRole.ANALYST: {
        KeepSaveOperation.READ_SECRET,
        KeepSaveOperation.VIEW_AUDIT,
        KeepSaveOperation.MCP_CALL,
        KeepSaveOperation.MCP_LIST,
    },
    AgentRole.QA: {
        KeepSaveOperation.READ_SECRET,
        KeepSaveOperation.VIEW_AUDIT,
        KeepSaveOperation.MCP_LIST,
    },
    AgentRole.WRITER: set(),
    AgentRole.PROMPT_CREATOR: set(),
}

# Which environments each role can promote TO
_ROLE_PROMOTE_TARGETS: dict[AgentRole, set[str]] = {
    AgentRole.CEO: {"uat", "prod"},
    AgentRole.ENGINEER: {"uat"},
    # All others: no promotion rights
    AgentRole.ANALYST: set(),
    AgentRole.QA: set(),
    AgentRole.WRITER: set(),
    AgentRole.PROMPT_CREATOR: set(),
}


# ── RBAC enforcement functions ──────────────────────────────────────────────


class KeepSaveAccessDeniedError(Exception):
    """Raised when an agent role lacks permission for a KeepSave operation."""

    def __init__(self, role: AgentRole, operation: str, detail: str = "") -> None:
        self.role = role
        self.operation = operation
        self.detail = detail
        msg = f"Access denied: {role} cannot {operation}"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


def check_operation(role: AgentRole, operation: KeepSaveOperation) -> None:
    """Check if a role is allowed to perform a KeepSave operation.

    Raises:
        KeepSaveAccessDeniedError: If the role lacks permission.
    """
    allowed = _ROLE_OPERATIONS.get(role, set())
    if operation not in allowed:
        logger.warning(
            "keepsave_rbac_denied",
            role=role,
            operation=operation,
        )
        raise KeepSaveAccessDeniedError(role, operation)


def check_secret_read(role: AgentRole, secret_key: str) -> None:
    """Check if a role can read a specific secret's metadata.

    Raises:
        KeepSaveAccessDeniedError: If the role lacks read access to this secret's scope.
    """
    scope = _classify_secret(secret_key)
    if scope is None:
        # Unclassified secrets: only CEO can access
        if role != AgentRole.CEO:
            raise KeepSaveAccessDeniedError(
                role, f"read secret '{secret_key}'", "unclassified secret — CEO only"
            )
        return

    allowed = _ROLE_READ_SCOPES.get(role, set())
    if scope not in allowed:
        raise KeepSaveAccessDeniedError(
            role, f"read secret '{secret_key}'", f"scope '{scope}' not in read permissions"
        )


def check_secret_write(role: AgentRole, secret_key: str) -> None:
    """Check if a role can modify a specific secret.

    Raises:
        KeepSaveAccessDeniedError: If the role lacks write access to this secret's scope.
    """
    scope = _classify_secret(secret_key)
    if scope is None:
        if role != AgentRole.CEO:
            raise KeepSaveAccessDeniedError(
                role, f"write secret '{secret_key}'", "unclassified secret — CEO only"
            )
        return

    allowed = _ROLE_WRITE_SCOPES.get(role, set())
    if scope not in allowed:
        raise KeepSaveAccessDeniedError(
            role, f"write secret '{secret_key}'", f"scope '{scope}' not in write permissions"
        )


def check_promote_target(role: AgentRole, target_environment: str) -> None:
    """Check if a role can promote to a target environment.

    Raises:
        KeepSaveAccessDeniedError: If the role cannot promote to this environment.
    """
    allowed = _ROLE_PROMOTE_TARGETS.get(role, set())
    if target_environment.lower() not in allowed:
        raise KeepSaveAccessDeniedError(
            role, f"promote to {target_environment}", "target environment not allowed"
        )


def filter_secrets_for_role(
    role: AgentRole,
    secrets: list[dict],
) -> list[dict]:
    """Filter a list of secrets to only those the role can see.

    Used by tool_keepsave_list_secrets to hide secrets outside the role's scope.
    """
    result = []
    for secret in secrets:
        key = secret.get("key", "")
        scope = _classify_secret(key)
        allowed = _ROLE_READ_SCOPES.get(role, set())
        if scope is None:
            # Unclassified: CEO only
            if role == AgentRole.CEO:
                result.append(secret)
        elif scope in allowed:
            result.append(secret)
    return result
