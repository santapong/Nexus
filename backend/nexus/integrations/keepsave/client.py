"""Async HTTP client for the KeepSave API.

Wraps KeepSave's REST endpoints for secret management, promotion,
API key operations, and MCP gateway calls. All methods are async
and propagate task_id/trace_id for observability.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

# KeepSave connection — loaded from environment (bootstrap values only)
_KEEPSAVE_URL = os.environ.get("KEEPSAVE_URL", "http://localhost:8080")
_KEEPSAVE_API_KEY = os.environ.get("KEEPSAVE_API_KEY", "")
_KEEPSAVE_PROJECT_ID = os.environ.get("KEEPSAVE_PROJECT_ID", "")
_NEXUS_ENV = os.environ.get("NEXUS_ENV", "alpha")


class KeepSaveClient:
    """Async client for KeepSave API operations.

    Uses httpx.AsyncClient for non-blocking HTTP calls.
    All secret-modifying operations return structured results
    suitable for LLM tool output.
    """

    def __init__(
        self,
        base_url: str = _KEEPSAVE_URL,
        api_key: str = _KEEPSAVE_API_KEY,
        project_id: str = _KEEPSAVE_PROJECT_ID,
        environment: str = _NEXUS_ENV,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.project_id = project_id
        self.environment = environment
        self._headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """Make an authenticated request to KeepSave."""
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                self._url(path),
                headers=self._headers,
                json=json,
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()

    # ── Secret Management ─────────────────────────────────────────────

    async def list_secrets(self, environment: str | None = None) -> list[dict[str, Any]]:
        """List all secrets for the project in the given environment."""
        env = environment or self.environment
        result = await self._request(
            "GET",
            f"/api/v1/projects/{self.project_id}/secrets",
            params={"environment": env},
        )
        return result if isinstance(result, list) else result.get("secrets", [])

    async def get_secret(self, secret_key: str, environment: str | None = None) -> dict[str, Any]:
        """Get a specific secret by key name."""
        env = environment or self.environment
        secrets = await self.list_secrets(env)
        for secret in secrets:
            if secret.get("key") == secret_key:
                return secret
        return {"error": f"Secret '{secret_key}' not found in {env}"}

    async def create_secret(
        self,
        key: str,
        value: str,
        environment: str | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a new secret in the vault."""
        env = environment or self.environment
        return await self._request(
            "POST",
            f"/api/v1/projects/{self.project_id}/secrets",
            json={
                "key": key,
                "value": value,
                "environment": env,
                "description": description,
            },
        )

    async def update_secret(
        self,
        secret_id: str,
        value: str,
    ) -> dict[str, Any]:
        """Update an existing secret's value (creates a new version)."""
        return await self._request(
            "PUT",
            f"/api/v1/projects/{self.project_id}/secrets/{secret_id}",
            json={"value": value},
        )

    async def get_secret_versions(self, secret_id: str) -> list[dict[str, Any]]:
        """Get version history for a secret."""
        result = await self._request(
            "GET",
            f"/api/v1/projects/{self.project_id}/secrets/{secret_id}/versions",
        )
        return result if isinstance(result, list) else result.get("versions", [])

    # ── Environment Promotion ─────────────────────────────────────────

    async def promote_diff(
        self,
        source_environment: str,
        target_environment: str,
    ) -> dict[str, Any]:
        """Preview what would change in a promotion (dry run)."""
        return await self._request(
            "POST",
            f"/api/v1/projects/{self.project_id}/promote/diff",
            json={
                "source_environment": source_environment,
                "target_environment": target_environment,
            },
        )

    async def promote(
        self,
        source_environment: str,
        target_environment: str,
        *,
        notes: str = "",
        override_policy: str = "skip",
    ) -> dict[str, Any]:
        """Execute environment promotion (may require KeepSave-side approval for PROD)."""
        return await self._request(
            "POST",
            f"/api/v1/projects/{self.project_id}/promote",
            json={
                "source_environment": source_environment,
                "target_environment": target_environment,
                "notes": notes,
                "override_policy": override_policy,
            },
        )

    async def list_promotions(self) -> list[dict[str, Any]]:
        """List promotion history for the project."""
        result = await self._request(
            "GET",
            f"/api/v1/projects/{self.project_id}/promotions",
        )
        return result if isinstance(result, list) else result.get("promotions", [])

    async def approve_promotion(self, promotion_id: str) -> dict[str, Any]:
        """Approve a pending promotion request."""
        return await self._request(
            "POST",
            f"/api/v1/projects/{self.project_id}/promotions/{promotion_id}/approve",
        )

    async def reject_promotion(self, promotion_id: str) -> dict[str, Any]:
        """Reject a pending promotion request."""
        return await self._request(
            "POST",
            f"/api/v1/projects/{self.project_id}/promotions/{promotion_id}/reject",
        )

    async def rollback_promotion(self, promotion_id: str) -> dict[str, Any]:
        """Rollback a completed promotion."""
        return await self._request(
            "POST",
            f"/api/v1/projects/{self.project_id}/promotions/{promotion_id}/rollback",
        )

    # ── MCP Gateway ──────────────────────────────────────────────────

    async def mcp_call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call a tool via KeepSave's MCP Gateway (automatic secret injection)."""
        result = await self._request(
            "POST",
            "/api/v1/mcp/gateway",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            },
            timeout=60.0,
        )
        if result.get("error"):
            return {"error": result["error"].get("message", str(result["error"]))}
        return result.get("result", result)

    async def mcp_list_tools(self) -> list[dict[str, Any]]:
        """List all available tools across installed MCP servers."""
        result = await self._request("GET", "/api/v1/mcp/gateway/tools")
        inner = result.get("result", result)
        return inner.get("tools", []) if isinstance(inner, dict) else []

    # ── Audit Log ────────────────────────────────────────────────────

    async def get_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent audit log entries for the project."""
        result = await self._request(
            "GET",
            f"/api/v1/projects/{self.project_id}/audit-log",
            params={"limit": str(limit)},
        )
        return result if isinstance(result, list) else result.get("entries", [])


# Singleton instance — lazily initialized
_client: KeepSaveClient | None = None


def get_keepsave_client() -> KeepSaveClient:
    """Get or create the singleton KeepSave client."""
    global _client
    if _client is None:
        _client = KeepSaveClient()
    return _client
