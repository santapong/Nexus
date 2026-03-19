"""Plugin system for custom MCP tool providers.

Users can register Python packages or HTTP endpoints as tool providers.
Each plugin defines a manifest with tool definitions, parameters, and
approval requirements. Supports hot-reload without restart.

Plugin types:
1. Python package plugins — imported and called directly
2. HTTP endpoint plugins — called via async HTTP client
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import PluginRegistration
from nexus.tools.adapter import _sanitize_tool_output

logger = structlog.get_logger()


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

        Args:
            **kwargs: Tool arguments matching the parameter schema.

        Returns:
            Tool output as a string.
        """
        try:
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
        """Call an HTTP endpoint plugin tool."""
        async with httpx.AsyncClient() as client:
            response = await client.request(
                self.http_method,
                self.http_endpoint,  # type: ignore[arg-type]
                json=kwargs,
                headers=self.http_headers,
                timeout=60.0,
            )
            response.raise_for_status()
            return response.text


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

            tool = PluginTool(
                name=tool_def.get("name", func_name),
                description=tool_def.get("description", func.__doc__ or ""),
                parameters=tool_def.get("parameters", {}),
                plugin_id=plugin_id,
                python_callable=func,
                requires_approval=func_name in manifest.requires_approval,
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
            tool = PluginTool(
                name=tool_def.get("name", ""),
                description=tool_def.get("description", ""),
                parameters=tool_def.get("parameters", {}),
                plugin_id=plugin_id,
                http_endpoint=endpoint,
                http_method=tool_def.get("method", "POST"),
                http_headers=headers or {},
                requires_approval=tool_def.get("name", "") in manifest.requires_approval,
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
        to_remove = [
            name for name, tool in self._tools.items()
            if tool.plugin_id == plugin_id
        ]
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

        Args:
            plugin_id: The plugin to reload.
            session: Database session.

        Returns:
            The reloaded manifest, or None if not found.
        """
        if plugin_id not in self._plugins:
            return None

        if plugin_id.startswith("python:"):
            module_path = plugin_id.removeprefix("python:")
            # Invalidate module cache for hot-reload
            import sys
            if module_path in sys.modules:
                importlib.reload(sys.modules[module_path])
            await self.unregister_plugin(plugin_id)
            return await self.register_python_plugin(module_path, session=session)

        elif plugin_id.startswith("http:"):
            base_url = plugin_id.removeprefix("http:")
            await self.unregister_plugin(plugin_id)
            return await self.register_http_plugin(base_url, session=session)

        return None

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
