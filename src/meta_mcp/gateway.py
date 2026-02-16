"""
Gateway Server Mode for Meta-MCP.

Exposes a lean set of always-available tools (~8) and dynamically
registers/unregisters backend MCP server tools on demand.  This cuts
the per-turn token overhead from ~7,400 tokens (60 tools) down to ~480
tokens at baseline.

Usage:
    py -m meta_mcp --stdio --gateway
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from .gateway_registry import BackendConfig, GatewayRegistry
from .models import DiscoveredTool, ServerToolsResult
from .orchestration import ServerOrchestrator

logger = logging.getLogger(__name__)

# Estimated tokens per tool definition in the system prompt.
_TOKENS_PER_TOOL_ESTIMATE = 60


class GatewayServer:
    """Meta-MCP in gateway mode — single MCP server proxying to backends.

    Instead of registering 30+ meta-mcp tools *and* having Claude Code also
    load firecrawl/engram/beacon/rlm/llm-council tools directly, we expose
    only ~8 lean gateway tools.  Backend server tools are loaded dynamically
    when ``activate_backend`` is called, and removed when
    ``deactivate_backend`` is called.
    """

    def __init__(self, registry: Optional[GatewayRegistry] = None) -> None:
        self.mcp = FastMCP("Meta MCP Gateway")
        self.orchestrator = ServerOrchestrator()
        self.registry = registry or GatewayRegistry()

        # backend_name -> ServerToolsResult (discovered tools/prompts)
        self.active_backends: Dict[str, ServerToolsResult] = {}
        # tool_name -> (backend_name, original_tool_name)
        self._proxy_tool_map: Dict[str, tuple[str, str]] = {}
        # Keep a few core meta-mcp tools from the existing codebase.
        self._core_tools_registered = False

        self._register_gateway_tools()

    # ------------------------------------------------------------------
    # Gateway tool registration
    # ------------------------------------------------------------------

    def _register_gateway_tools(self) -> None:
        """Register the minimal set of always-available tools."""

        @self.mcp.tool(
            name="activate_backend",
            description=(
                "Activate a backend MCP server by name. Starts the server process, "
                "discovers its tools, and makes them available as callable tools. "
                "Use list_backends() first to see what's available."
            ),
        )
        async def activate_backend(name: str) -> str:
            return await self._activate_backend(name)

        @self.mcp.tool(
            name="deactivate_backend",
            description=(
                "Deactivate a running backend MCP server. Stops the process and "
                "removes its tools to free context budget."
            ),
        )
        async def deactivate_backend(name: str) -> str:
            return await self._deactivate_backend(name)

        @self.mcp.tool(
            name="list_backends",
            description=(
                "List all known backend MCP servers with their status "
                "(active/inactive), tool count, and estimated token cost. "
                "Use this to decide which backends to activate for your task."
            ),
        )
        async def list_backends() -> str:
            return self._list_backends()

        @self.mcp.tool(
            name="context_budget",
            description=(
                "Report current gateway token usage: active backends, total tool "
                "count, and estimated context overhead. Helps self-regulate tool "
                "loading to preserve context for code."
            ),
        )
        async def context_budget() -> str:
            return self._context_budget()

        @self.mcp.tool(
            name="register_backend",
            description=(
                "Register a new backend MCP server in the gateway. "
                "Provide the name, command, args, and optional env vars. "
                "The backend will be saved to the registry for future sessions."
            ),
        )
        async def register_backend(
            name: str,
            command: str,
            args: str = "[]",
            env: str = "{}",
            auto_activate: bool = False,
            description: str = "",
        ) -> str:
            return self._register_backend(
                name, command, args, env, auto_activate, description
            )

        # Keep existing useful tools from meta-mcp
        self._register_core_meta_tools()

    def _register_core_meta_tools(self) -> None:
        """Register a small subset of meta-mcp's core tools (search, install, gaps)."""
        # Import lazily to avoid circular imports and only pull what we need.
        from .tools import (
            SearchMcpServersTool,
            InstallMcpServerTool,
            DetectCapabilityGapsTool,
        )

        core_tools = [
            SearchMcpServersTool(),
            InstallMcpServerTool(),
            DetectCapabilityGapsTool(),
        ]

        for tool_instance in core_tools:
            name = tool_instance.get_name()
            description = (
                tool_instance.__class__.__doc__
                or tool_instance.get_apply_docstring()
            )
            from .server import MetaMCPServer
            fn = MetaMCPServer._wrap_tool(tool_instance)
            self.mcp.tool(name=name, description=description)(fn)

        self._core_tools_registered = True

    # ------------------------------------------------------------------
    # activate / deactivate
    # ------------------------------------------------------------------

    async def _activate_backend(self, name: str) -> str:
        """Start a backend, discover its tools, register them dynamically."""
        if name in self.active_backends:
            tools = self.active_backends[name].tools
            tool_names = [f"{name}_{t.name}" for t in tools]
            return (
                f"Backend '{name}' is already active with {len(tools)} tool(s):\n"
                + "\n".join(f"  - {tn}" for tn in tool_names)
            )

        config = self.registry.get(name)
        if config is None:
            available = ", ".join(sorted(self.registry.backends.keys()))
            return (
                f"Unknown backend '{name}'. "
                f"Known backends: {available or '(none)'}.\n"
                "Use register_backend() to add a new one."
            )

        try:
            # Start the server process
            await self.orchestrator.start_server(
                name=name,
                command=config.command,
                args=config.args,
                env=config.env or None,
            )

            # Perform MCP handshake
            proc = self.orchestrator._processes.get(name)
            if proc is not None:
                await self.orchestrator._perform_handshake(proc, name)

            # Discover tools
            result = await self.orchestrator.discover_server_tools(
                name=name,
                command=config.command,
                args=config.args,
                env=config.env or None,
            )

            # Register each discovered tool as a proxy on our FastMCP instance
            registered_names: List[str] = []
            for tool in result.tools:
                proxy_name = f"{name}_{tool.name}"
                proxy_fn = self._make_proxy(name, tool.name)
                self.mcp.tool(
                    name=proxy_name,
                    description=tool.description,
                )(proxy_fn)
                self._proxy_tool_map[proxy_name] = (name, tool.name)
                registered_names.append(proxy_name)

            self.active_backends[name] = result

            # Notify Claude Code that our tool list changed
            await self._send_tools_list_changed()

            return (
                f"Activated backend '{name}' — {len(registered_names)} tool(s) now available:\n"
                + "\n".join(f"  - {tn}" for tn in registered_names)
            )

        except Exception as exc:
            logger.exception("Failed to activate backend '%s'", name)
            return f"Failed to activate backend '{name}': {exc}"

    async def _deactivate_backend(self, name: str) -> str:
        """Stop a backend and unregister its proxied tools."""
        if name not in self.active_backends:
            return f"Backend '{name}' is not active."

        result = self.active_backends.pop(name)

        # Remove proxied tools from FastMCP
        removed: List[str] = []
        for tool in result.tools:
            proxy_name = f"{name}_{tool.name}"
            self._remove_tool(proxy_name)
            self._proxy_tool_map.pop(proxy_name, None)
            removed.append(proxy_name)

        # Stop the server process
        try:
            await self.orchestrator.stop_server(name)
        except KeyError:
            pass

        await self._send_tools_list_changed()

        return (
            f"Deactivated backend '{name}' — removed {len(removed)} tool(s).\n"
            f"Freed ~{len(removed) * _TOKENS_PER_TOOL_ESTIMATE} tokens of context budget."
        )

    # ------------------------------------------------------------------
    # list / budget / register
    # ------------------------------------------------------------------

    def _list_backends(self) -> str:
        """List all known backends with status."""
        lines = ["# Known Backends\n"]

        all_backends = self.registry.backends
        if not all_backends:
            lines.append("No backends registered. Use `register_backend()` to add one.")
            return "\n".join(lines)

        for name, cfg in sorted(all_backends.items()):
            active = name in self.active_backends
            tool_count = (
                len(self.active_backends[name].tools)
                if active
                else "?"
            )
            status = "ACTIVE" if active else "inactive"
            tokens = (
                len(self.active_backends[name].tools) * _TOKENS_PER_TOOL_ESTIMATE
                if active
                else cfg.estimated_tokens
            )
            auto = " [auto]" if cfg.auto_activate else ""
            desc = f" — {cfg.description}" if cfg.description else ""

            lines.append(
                f"- **{name}** [{status}]{auto}: {tool_count} tools, "
                f"~{tokens} tokens{desc}"
            )

        lines.append("")
        lines.append(
            f"**Active**: {len(self.active_backends)} | "
            f"**Total registered**: {len(all_backends)}"
        )
        return "\n".join(lines)

    def _context_budget(self) -> str:
        """Report current context token usage."""
        gateway_tool_count = len(self._get_gateway_tool_names())
        proxy_tool_count = len(self._proxy_tool_map)
        total_tools = gateway_tool_count + proxy_tool_count
        estimated_tokens = total_tools * _TOKENS_PER_TOOL_ESTIMATE

        lines = [
            "# Context Budget Report\n",
            f"- **Gateway tools** (always loaded): {gateway_tool_count}",
            f"- **Proxied backend tools**: {proxy_tool_count}",
            f"- **Total tools**: {total_tools}",
            f"- **Estimated token overhead**: ~{estimated_tokens} tokens",
            "",
            "## Active Backends",
        ]

        if self.active_backends:
            for name, result in sorted(self.active_backends.items()):
                tc = len(result.tools)
                lines.append(f"  - {name}: {tc} tools (~{tc * _TOKENS_PER_TOOL_ESTIMATE} tokens)")
        else:
            lines.append("  (none)")

        lines.append("")

        # How much we're saving vs full mode
        all_backends = self.registry.backends
        full_mode_tokens = sum(
            cfg.estimated_tokens for cfg in all_backends.values()
        )
        savings = max(0, full_mode_tokens - estimated_tokens)
        if full_mode_tokens > 0:
            pct = int((savings / full_mode_tokens) * 100)
            lines.append(
                f"**Savings vs all-loaded**: ~{savings} tokens ({pct}% reduction)"
            )

        return "\n".join(lines)

    def _register_backend(
        self,
        name: str,
        command: str,
        args: str,
        env: str,
        auto_activate: bool,
        description: str,
    ) -> str:
        """Register a new backend in the persistent registry."""
        try:
            args_list = json.loads(args) if args else []
        except json.JSONDecodeError:
            return f"Invalid args JSON: {args}"

        try:
            env_dict = json.loads(env) if env else {}
        except json.JSONDecodeError:
            return f"Invalid env JSON: {env}"

        config = BackendConfig(
            command=command,
            args=args_list,
            env=env_dict,
            auto_activate=auto_activate,
            description=description,
        )
        self.registry.add(name, config)
        self.registry.save()
        return (
            f"Registered backend '{name}' (command: {command} {' '.join(args_list)}). "
            f"Auto-activate: {auto_activate}. "
            "Use `activate_backend(name)` to start it."
        )

    # ------------------------------------------------------------------
    # Proxy machinery
    # ------------------------------------------------------------------

    def _make_proxy(self, server_name: str, tool_name: str) -> Callable:
        """Create an async proxy function that forwards calls to a backend."""

        async def proxy(**kwargs: Any) -> str:
            result = await self.orchestrator.forward_tool_call(
                server_name=server_name,
                tool_name=tool_name,
                arguments=kwargs,
            )
            if isinstance(result, str):
                return result
            return json.dumps(result, indent=2, ensure_ascii=False)

        # Give the proxy a meaningful name and docstring for FastMCP introspection
        proxy.__name__ = f"{server_name}_{tool_name}"
        proxy.__qualname__ = f"GatewayServer.proxy.{server_name}_{tool_name}"
        return proxy

    # ------------------------------------------------------------------
    # Dynamic tool list management
    # ------------------------------------------------------------------

    def _remove_tool(self, tool_name: str) -> None:
        """Remove a dynamically registered tool from FastMCP.

        FastMCP stores tools in ``_tool_manager._tools`` (a dict keyed by name).
        We remove the entry directly.
        """
        try:
            manager = self.mcp._tool_manager
            if hasattr(manager, "_tools") and tool_name in manager._tools:
                del manager._tools[tool_name]
                logger.info("Removed tool '%s' from FastMCP", tool_name)
        except Exception:
            logger.warning("Could not remove tool '%s' from FastMCP", tool_name, exc_info=True)

    async def _send_tools_list_changed(self) -> None:
        """Send ``notifications/tools/list_changed`` to the connected client.

        This tells Claude Code to re-fetch the tool list, picking up any
        tools we just added or removed.
        """
        try:
            # FastMCP -> low-level server -> session
            low_level = self.mcp._mcp_server
            if hasattr(low_level, "request_context") and low_level.request_context:
                session = low_level.request_context.session
                if hasattr(session, "send_tool_list_changed"):
                    await session.send_tool_list_changed()
                    logger.info("Sent tools/list_changed notification")
                    return

            # Fallback: try direct notification via the active session
            if hasattr(low_level, "_session") and low_level._session is not None:
                await low_level._session.send_tool_list_changed()
                logger.info("Sent tools/list_changed notification (via _session)")
                return

            logger.debug("No active session to send tools/list_changed to")
        except Exception:
            logger.debug("Could not send tools/list_changed", exc_info=True)

    def _get_gateway_tool_names(self) -> List[str]:
        """Return names of the always-loaded gateway tools (non-proxy)."""
        all_tools = set()
        try:
            manager = self.mcp._tool_manager
            if hasattr(manager, "_tools"):
                all_tools = set(manager._tools.keys())
        except Exception:
            pass
        proxy_names = set(self._proxy_tool_map.keys())
        return sorted(all_tools - proxy_names)

    # ------------------------------------------------------------------
    # Auto-activation
    # ------------------------------------------------------------------

    async def _auto_activate(self) -> None:
        """Activate backends marked with ``auto_activate: true``."""
        for name in self.registry.auto_activate_backends():
            logger.info("Auto-activating backend '%s'", name)
            try:
                await self._activate_backend(name)
            except Exception:
                logger.exception("Failed to auto-activate '%s'", name)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self, transport: str = "stdio") -> None:
        """Start the gateway server.

        Auto-activates any backends marked for auto-activation, then hands
        off to FastMCP's event loop.
        """
        import sys

        print(
            f"Meta MCP Gateway starting ({transport} mode, "
            f"{len(self.registry.backends)} backend(s) registered)...",
            file=sys.stderr,
        )

        # Schedule auto-activation to run once the event loop starts.
        # We hook into FastMCP's startup by wrapping the run call.
        original_run = self.mcp.run

        def patched_run(**kwargs: Any) -> None:
            # Register a startup callback if possible
            loop = None
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Create a task for auto-activation that runs after the server starts
            async def _startup_auto_activate() -> None:
                await asyncio.sleep(0.5)  # let the MCP handshake complete
                await self._auto_activate()

            # We can't easily hook into FastMCP's startup, so we use
            # call_soon to schedule it
            if self.registry.auto_activate_backends():
                try:
                    loop.call_soon(
                        lambda: asyncio.ensure_future(_startup_auto_activate())
                    )
                except Exception:
                    logger.debug("Could not schedule auto-activation", exc_info=True)

            original_run(**kwargs)

        patched_run(transport=transport)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Stop all active backends and clean up."""
        for name in list(self.active_backends.keys()):
            try:
                await self._deactivate_backend(name)
            except Exception:
                logger.exception("Error deactivating '%s' during shutdown", name)
        await self.orchestrator.shutdown()
