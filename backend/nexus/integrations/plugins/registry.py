"""Plugin system for custom MCP tool providers.

Users can register Python packages or HTTP endpoints as tool providers.
Each plugin defines a manifest with tool definitions, parameters, and
approval requirements. Supports hot-reload without restart.

Plugin types:
1. Python package plugins — imported and called directly
2. HTTP endpoint plugins — called via async HTTP client

Security guarantees:
- `requires_approval=True` tools are gated through ``require_approval()`` before
  the underlying callable / HTTP request runs. Bypass attempts (missing session)
  fail closed.
- Plugin manifests that declare ``requires_approval: false`` on tool names that
  look dangerous (delete/remove/drop/push/send/pay/charge/deploy/publish/destroy)
  are force-flipped to ``True`` with a WARNING log. The manifest author cannot
  opt a destructive tool out of human review by mislabelling it.
- HTTP plugin responses are size-, type-, and length-validated before reaching
  the caller (1MB hard cap, JSON/text-only, 50KB body truncation).
- ``reload_plugin()`` acquires a Redis lock in db:3 to prevent concurrent reloads
  racing each other and producing a half-initialised registry.
"""

from __future__ import annotations

import importlib
import inspect
import re
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import PluginRegistration
from nexus.tools.adapter import _sanitize_tool_output

logger = structlog.get_logger()

# Heuristic: any tool name that looks irreversible MUST require approval,
# regardless of what the manifest claims. This is a defence-in-depth check —
# the manifest cannot opt destructive tools out of human review by mislabelling
# them. Verbs covered: delete/remove/drop/push/send/pay/charge/deploy/publish/destroy.
_DANGEROUS_TOOL_NAME_RE = re.compile(
    r"(?i)(delete|remove|drop|push|send|pay|charge|deploy|publish|destroy)"
)

# HTTP plugin response limits — fail-closed values, not tuned for any specific plugin.
_HTTP_MAX_CONTENT_LENGTH = 1024 * 1024  # 1 MB hard cap on declared Content-Length
_HTTP_RESPONSE_TRUNCATE_BYTES = 50 * 1024  # 50 KB returned to caller
_HTTP_ALLOWED_CONTENT_TYPES = {"application/json", "text/plain"}

# Redis lock TTL for plugin reload. Long enough to cover an HTTP manifest fetch,
# short enough that a crashed reload doesn't permanently block the plugin.
_RELOAD_LOCK_TTL_SECONDS = 30


def _is_dangerous_tool_name(name: str) -> bool:
    """Return True if the tool name matches the irreversible-verb heuristic."""
    return bool(_DANGEROUS_TOOL_NAME_RE.search(name))


def _enforce_approval_for_dangerous_name(
    *, tool_name: str, declared_requires_approval: bool, plugin_id: str
) -> bool:
    """Force-flip ``requires_approval`` to True when the name looks destructive.

    If the manifest says a tool called ``delete_repo`` or ``send_email`` does NOT
    need approval, we override the manifest and log a WARNING. The override is
    one-way: dangerous-named + manifest-says-true stays true; dangerous-named +
    manifest-says-false becomes true.
    """
    if declared_requires_approval:
        return True
    if _is_dangerous_tool_name(tool_name):
        logger.warning(
            "plugin_dangerous_name_force_approval",
            tool=tool_name,
            plugin_id=plugin_id,
            reason="manifest declared requires_approval=False on irreversible-named tool",
        )
        return True
    return declared_requires_approval


class PluginManifest:
    """Describes a plugin's tools and their requirements.

    Attributes:
        name: Plugin display name.
        version: Plugin version string.
        description: What the plugin does.
        tools: List of tool definitions.
        requires_approval: Tools that need human approval.
    """

    def __init__(
        self,
        name: str,
        version: str,
        description: str,
        tools: list[dict[str, Any]],
        requires_approval: list[str] | None = None,
    ) -> None:
        self.name = name
        self.version = version
        self.description = description
        self.tools = tools
        self.requires_approval = requires_approval or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "tools": self.tools,
            "requires_approval": self.requires_approval,
        }


class PluginTool:
    """A tool provided by a plugin, ready for agent use.

    Wraps either a Python callable or an HTTP endpoint into a uniform
    interface that agents can call through the tool registry.
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        plugin_id: str,
        *,
        python_callable: Callable[..., Any] | None = None,
        http_endpoint: str | None = None,
        http_method: str = "POST",
        http_headers: dict[str, str] | None = None,
        requires_approval: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.plugin_id = plugin_id
        self.python_callable = python_callable
        self.http_endpoint = http_endpoint
        self.http_method = http_method
        self.http_headers = http_headers or {}
        self.requires_approval = requires_approval

    async def execute(self, **kwargs: Any) -> str:
        """Execute the plugin tool with the given arguments.

        Reserved kwargs (popped before being passed to the wrapped function):
            session: AsyncSession — required when ``self.requires_approval`` is True.
            agent_id: str — agent invoking the tool; recorded on the approval row.
            task_id: str — task this call belongs to; recorded on the approval row.

        If ``self.requires_approval`` is True and the caller did not supply
        ``session``/``agent_id``/``task_id``, the call is rejected (fail-closed) —
        we will not silently bypass the approval gate.

        Args:
            **kwargs: Tool arguments matching the parameter schema, plus the
                reserved approval-context kwargs above.

        Returns:
            Tool output as a string. Approval failures and tool errors are
            returned as ``"Plugin tool error: ..."`` strings rather than raised,
            matching the pattern in ``nexus.tools.adapter``.
        """
        # Pop approval-context kwargs so they never leak into the wrapped function.
        session: AsyncSession | None = kwargs.pop("session", None)
        agent_id: str | None = kwargs.pop("agent_id", None)
        task_id: str | None = kwargs.pop("task_id", None)

        try:
            if self.requires_approval:
                # Import inside the method to avoid a hard top-level dependency
                # cycle (tools.guards imports from db/audit which import settings).
                from nexus.tools.guards import IrreversibleAction, require_approval

                if session is None or agent_id is None or task_id is None:
                    logger.error(
                        "plugin_approval_context_missing",
                        tool=self.name,
                        plugin_id=self.plugin_id,
                        has_session=session is not None,
                        has_agent_id=agent_id is not None,
                        has_task_id=task_id is not None,
                    )
                    return (
                        "Plugin tool error: approval-gated tool invoked without "
                        "session/agent_id/task_id context; refusing to bypass approval"
                    )

                await require_approval(
                    session=session,
                    agent_id=agent_id,
                    action=IrreversibleAction(
                        action=f"plugin:{self.name}",
                        description=f"Plugin {self.plugin_id} → {self.name}",
                        task_id=task_id,
                    ),
                )

            if self.python_callable is not None:
                if inspect.iscoroutinefunction(self.python_callable):
                    result = await self.python_callable(**kwargs)
                else:
                    import asyncio

                    result = await asyncio.to_thread(self.python_callable, **kwargs)
            elif self.http_endpoint:
                result = await self._call_http(**kwargs)
            else:
                return "Error: Plugin tool has no callable or endpoint configured"

            output = str(result) if not isinstance(result, str) else result
            return _sanitize_tool_output(output)
        except Exception as exc:
            logger.error(
                "plugin_tool_error",
                tool=self.name,
                plugin_id=self.plugin_id,
                error=str(exc),
            )
            return f"Plugin tool error: {exc}"

    async def _call_http(self, **kwargs: Any) -> str:
        """Call an HTTP endpoint plugin tool.

        Validates the response before returning:
        - Reject if declared ``Content-Length`` exceeds 1 MB.
        - Reject if ``Content-Type`` is not in the allowlist
          (``application/json`` / ``text/plain``). Defends against an attacker-
          controlled plugin returning HTML/JS/binary blobs that downstream
          processing might mishandle.
        - Truncate the returned body to 50 KB so a single tool call cannot
          flood agent context.
        """
        async with httpx.AsyncClient() as client:
            response = await client.request(
                self.http_method,
                self.http_endpoint,  # type: ignore[arg-type]
                json=kwargs,
                headers=self.http_headers,
                timeout=60.0,
            )
            response.raise_for_status()

            # Content-Length check (declared size — actual body still truncated below).
            declared_length_raw = response.headers.get("content-length")
            if declared_length_raw is not None:
                try:
                    declared_length = int(declared_length_raw)
                except ValueError:
                    declared_length = -1
                if declared_length > _HTTP_MAX_CONTENT_LENGTH:
                    logger.warning(
                        "plugin_http_response_too_large",
                        tool=self.name,
                        plugin_id=self.plugin_id,
                        content_length=declared_length,
                        limit=_HTTP_MAX_CONTENT_LENGTH,
                    )
                    return (
                        f"Plugin tool error: HTTP response exceeds {_HTTP_MAX_CONTENT_LENGTH} bytes"
                    )

            # Content-Type allowlist. Split off any charset parameter.
            content_type_raw = response.headers.get("content-type", "")
            content_type = content_type_raw.split(";", 1)[0].strip().lower()
            if content_type and content_type not in _HTTP_ALLOWED_CONTENT_TYPES:
                logger.warning(
                    "plugin_http_response_bad_content_type",
                    tool=self.name,
                    plugin_id=self.plugin_id,
                    content_type=content_type,
                    allowed=sorted(_HTTP_ALLOWED_CONTENT_TYPES),
                )
                return (
                    f"Plugin tool error: HTTP response Content-Type '{content_type}' "
                    "not in allowed set (application/json, text/plain)"
                )

            body = response.text
            if len(body) > _HTTP_RESPONSE_TRUNCATE_BYTES:
                logger.info(
                    "plugin_http_response_truncated",
                    tool=self.name,
                    plugin_id=self.plugin_id,
                    original_length=len(body),
                    truncated_length=_HTTP_RESPONSE_TRUNCATE_BYTES,
                )
                body = body[:_HTTP_RESPONSE_TRUNCATE_BYTES] + "\n[... truncated]"
            return body


class PluginRegistry:
    """Central registry for all installed plugins and their tools.

    Manages plugin lifecycle: registration, loading, hot-reload, and removal.
    Tools from plugins are exposed to agents through the standard tool registry.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginManifest] = {}
        self._tools: dict[str, PluginTool] = {}

    @property
    def plugin_count(self) -> int:
        return len(self._plugins)

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    def get_tool(self, name: str) -> PluginTool | None:
        """Get a plugin tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered plugin tools."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "plugin_id": tool.plugin_id,
                "requires_approval": tool.requires_approval,
                "type": "python" if tool.python_callable else "http",
            }
            for tool in self._tools.values()
        ]

    def list_plugins(self) -> list[dict[str, Any]]:
        """List all registered plugins."""
        return [manifest.to_dict() for manifest in self._plugins.values()]

    async def register_python_plugin(
        self,
        module_path: str,
        *,
        session: AsyncSession | None = None,
        workspace_id: str | None = None,
    ) -> PluginManifest:
        """Register a Python package as a plugin.

        The module must export a `PLUGIN_MANIFEST` dict and tool functions.

        Args:
            module_path: Python module path (e.g., 'my_tools.plugin').
            session: Database session for persistence.
            workspace_id: Owning workspace.

        Returns:
            The loaded plugin manifest.

        Raises:
            ImportError: If the module cannot be loaded.
            ValueError: If the module has no PLUGIN_MANIFEST.
        """
        module = importlib.import_module(module_path)

        manifest_dict = getattr(module, "PLUGIN_MANIFEST", None)
        if not manifest_dict:
            raise ValueError(f"Module {module_path} has no PLUGIN_MANIFEST")

        manifest = PluginManifest(
            name=manifest_dict["name"],
            version=manifest_dict.get("version", "0.1.0"),
            description=manifest_dict.get("description", ""),
            tools=manifest_dict.get("tools", []),
            requires_approval=manifest_dict.get("requires_approval", []),
        )

        plugin_id = f"python:{module_path}"
        self._plugins[plugin_id] = manifest

        # Register tools from the module
        for tool_def in manifest.tools:
            func_name = tool_def["function"]
            func = getattr(module, func_name, None)
            if func is None:
                logger.warning(
                    "plugin_tool_missing",
                    module=module_path,
                    function=func_name,
                )
                continue

            tool_name = tool_def.get("name", func_name)
            declared = (
                func_name in manifest.requires_approval or tool_name in manifest.requires_approval
            )
            effective_requires_approval = _enforce_approval_for_dangerous_name(
                tool_name=tool_name,
                declared_requires_approval=declared,
                plugin_id=plugin_id,
            )

            tool = PluginTool(
                name=tool_name,
                description=tool_def.get("description", func.__doc__ or ""),
                parameters=tool_def.get("parameters", {}),
                plugin_id=plugin_id,
                python_callable=func,
                requires_approval=effective_requires_approval,
            )
            self._tools[tool.name] = tool

        # Persist to database
        if session:
            await self._persist_registration(
                session=session,
                plugin_id=plugin_id,
                manifest=manifest,
                plugin_type="python",
                source=module_path,
                workspace_id=workspace_id,
            )

        logger.info(
            "plugin_registered",
            plugin_id=plugin_id,
            tools=len(manifest.tools),
        )
        return manifest

    async def register_http_plugin(
        self,
        base_url: str,
        manifest_url: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        session: AsyncSession | None = None,
        workspace_id: str | None = None,
    ) -> PluginManifest:
        """Register an HTTP endpoint as a plugin.

        Fetches the plugin manifest from the endpoint and registers its tools.

        Args:
            base_url: Base URL of the plugin HTTP server.
            manifest_url: URL to fetch the manifest from (defaults to {base_url}/manifest).
            headers: Auth headers for the plugin endpoint.
            session: Database session for persistence.
            workspace_id: Owning workspace.

        Returns:
            The loaded plugin manifest.
        """
        manifest_endpoint = manifest_url or f"{base_url.rstrip('/')}/manifest"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                manifest_endpoint,
                headers=headers or {},
                timeout=15.0,
            )
            response.raise_for_status()
            manifest_dict = response.json()

        manifest = PluginManifest(
            name=manifest_dict["name"],
            version=manifest_dict.get("version", "0.1.0"),
            description=manifest_dict.get("description", ""),
            tools=manifest_dict.get("tools", []),
            requires_approval=manifest_dict.get("requires_approval", []),
        )

        plugin_id = f"http:{base_url}"
        self._plugins[plugin_id] = manifest

        # Register tools
        for tool_def in manifest.tools:
            endpoint = tool_def.get("endpoint", f"{base_url.rstrip('/')}/{tool_def['name']}")
            tool_name = tool_def.get("name", "")
            declared = tool_name in manifest.requires_approval
            effective_requires_approval = _enforce_approval_for_dangerous_name(
                tool_name=tool_name,
                declared_requires_approval=declared,
                plugin_id=plugin_id,
            )
            tool = PluginTool(
                name=tool_name,
                description=tool_def.get("description", ""),
                parameters=tool_def.get("parameters", {}),
                plugin_id=plugin_id,
                http_endpoint=endpoint,
                http_method=tool_def.get("method", "POST"),
                http_headers=headers or {},
                requires_approval=effective_requires_approval,
            )
            self._tools[tool.name] = tool

        if session:
            await self._persist_registration(
                session=session,
                plugin_id=plugin_id,
                manifest=manifest,
                plugin_type="http",
                source=base_url,
                workspace_id=workspace_id,
            )

        logger.info(
            "http_plugin_registered",
            plugin_id=plugin_id,
            tools=len(manifest.tools),
        )
        return manifest

    async def unregister_plugin(self, plugin_id: str) -> bool:
        """Remove a plugin and all its tools.

        Args:
            plugin_id: The plugin identifier.

        Returns:
            True if the plugin was found and removed.
        """
        manifest = self._plugins.pop(plugin_id, None)
        if not manifest:
            return False

        # Remove tools belonging to this plugin
        to_remove = [name for name, tool in self._tools.items() if tool.plugin_id == plugin_id]
        for name in to_remove:
            del self._tools[name]

        logger.info(
            "plugin_unregistered",
            plugin_id=plugin_id,
            tools_removed=len(to_remove),
        )
        return True

    async def reload_plugin(
        self,
        plugin_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> PluginManifest | None:
        """Hot-reload a plugin by unregistering and re-registering it.

        Acquires a Redis lock on ``plugin:reload:{plugin_id}`` (db:3) to prevent
        two concurrent reloads from racing each other — the second reload would
        otherwise unregister tools the first reload just installed and leave the
        in-memory registry inconsistent with the database. If the lock cannot be
        acquired the reload is skipped and ``None`` is returned.

        Args:
            plugin_id: The plugin to reload.
            session: Database session.

        Returns:
            The reloaded manifest, or None if the plugin was unknown or another
            reload is in progress.
        """
        if plugin_id not in self._plugins:
            return None

        # Lock against concurrent reloads. Imported lazily to keep this module
        # importable without a live Redis (e.g. for unit tests of helpers).
        from nexus.core.redis.clients import redis_locks

        lock_key = f"plugin:reload:{plugin_id}"
        lock_token = str(uuid4())
        acquired = await redis_locks.set(lock_key, lock_token, nx=True, ex=_RELOAD_LOCK_TTL_SECONDS)
        if not acquired:
            logger.warning(
                "plugin_reload_lock_busy",
                plugin_id=plugin_id,
                lock_key=lock_key,
            )
            return None

        try:
            if plugin_id.startswith("python:"):
                module_path = plugin_id.removeprefix("python:")
                # Invalidate module cache for hot-reload
                import sys

                if module_path in sys.modules:
                    importlib.reload(sys.modules[module_path])
                await self.unregister_plugin(plugin_id)
                return await self.register_python_plugin(module_path, session=session)

            if plugin_id.startswith("http:"):
                base_url = plugin_id.removeprefix("http:")
                await self.unregister_plugin(plugin_id)
                return await self.register_http_plugin(base_url, session=session)

            return None
        finally:
            # Best-effort release. If our token no longer matches (lock expired
            # and someone else took it) we leave their lock alone.
            try:
                current = await redis_locks.get(lock_key)
                if current == lock_token:
                    await redis_locks.delete(lock_key)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning(
                    "plugin_reload_lock_release_failed",
                    plugin_id=plugin_id,
                    error=str(exc),
                )

    async def load_from_database(self, session: AsyncSession) -> int:
        """Load all active plugins from the database on startup.

        Args:
            session: Database session.

        Returns:
            Number of plugins loaded.
        """
        stmt = select(PluginRegistration).where(PluginRegistration.is_active.is_(True))
        result = await session.execute(stmt)
        registrations = result.scalars().all()

        loaded = 0
        for reg in registrations:
            try:
                if reg.plugin_type == "python":
                    await self.register_python_plugin(reg.source)
                    loaded += 1
                elif reg.plugin_type == "http":
                    await self.register_http_plugin(reg.source)
                    loaded += 1
            except Exception as exc:
                logger.error(
                    "plugin_load_failed",
                    plugin_id=reg.plugin_id,
                    error=str(exc),
                )

        logger.info("plugins_loaded_from_db", count=loaded)
        return loaded

    async def _persist_registration(
        self,
        *,
        session: AsyncSession,
        plugin_id: str,
        manifest: PluginManifest,
        plugin_type: str,
        source: str,
        workspace_id: str | None,
    ) -> None:
        """Persist a plugin registration to the database."""
        # Check if already registered
        stmt = select(PluginRegistration).where(PluginRegistration.plugin_id == plugin_id)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.manifest = manifest.to_dict()
            existing.is_active = True
        else:
            reg = PluginRegistration(
                id=str(uuid4()),
                plugin_id=plugin_id,
                plugin_type=plugin_type,
                source=source,
                manifest=manifest.to_dict(),
                workspace_id=workspace_id,
                is_active=True,
            )
            session.add(reg)
        await session.flush()


# Singleton registry
_registry: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    """Get or create the singleton plugin registry."""
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry
