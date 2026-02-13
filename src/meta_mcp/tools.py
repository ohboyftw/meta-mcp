"""
FastMCP tools for Meta MCP server management.
Implements R1-R10 tool surface.
"""

import asyncio
import json
from typing import Dict, List, Optional

def run_async_safely(coro):
    """Run an async coroutine safely, handling existing event loop conflicts."""
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        return asyncio.run(coro)

from .discovery import MCPDiscovery
from .installer import MCPInstaller
from .config import MCPConfig
from .intent import IntentEngine
from .verification import ServerVerifier
from .project import ProjectAnalyzer
from .registry import RegistryFederation
from .clients import ClientManager
from .memory import ConversationalMemory
from .orchestration import ServerOrchestrator
from .skills import SkillsManager
from .capability_stack import CapabilityStack
from .models import (
    MCPInstallationRequest,
    MCPSearchQuery,
    MCPServerCategory,
)
from .tools_base import Tool


# ─── Existing Tools (Enhanced) ────────────────────────────────────────────────

class SearchMcpServersTool(Tool):
    """Search for MCP servers by category, functionality, or keywords. Supports natural language queries like 'I need to scrape websites' and returns ranked results with trade-off explanations."""

    def __init__(self):
        super().__init__()
        self.discovery = MCPDiscovery()

    def apply(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        sort_by: str = "relevance",
        limit: int = 20
    ) -> str:
        """
        Search for MCP servers by category, functionality, or keywords.

        Args:
            query: Search query text — natural language like 'I need web scraping' works
            category: Filter by category (optional)
            keywords: Filter by keywords (optional)
            sort_by: Sort order (relevance, stars, updated, name)
            limit: Maximum results to return
        """
        category_enum = None
        if category:
            try:
                category_enum = MCPServerCategory(category)
            except ValueError:
                return f"Error: Invalid category '{category}'. Valid: {[c.value for c in MCPServerCategory]}"

        search_query = MCPSearchQuery(
            query=query, category=category_enum, keywords=keywords,
            sort_by=sort_by, limit=limit,
        )
        result = run_async_safely(self.discovery.search_servers(search_query))

        if not result.servers:
            return f"No MCP servers found matching your criteria.\nSearch took {result.search_time_ms}ms"

        content = f"Found {result.total_count} MCP servers (showing {len(result.servers)}):\n\n"
        for server in result.servers:
            content += f"**{server.display_name}** (`{server.name}`)\n"
            content += f"- Category: {server.category.value}\n"
            content += f"- Description: {server.description}\n"
            content += f"- Options: {len(server.options)} available\n"
            if server.stars:
                content += f"- GitHub Stars: {server.stars}\n"
            if server.repository_url:
                content += f"- Repository: {server.repository_url}\n"
            content += "\n"
        content += f"Search completed in {result.search_time_ms}ms"
        return content


class GetServerInfoTool(Tool):
    """Get detailed information about a specific MCP server including installation options, required credentials, and documentation links."""

    def __init__(self):
        super().__init__()
        self.discovery = MCPDiscovery()

    def apply(self, server_name: str) -> str:
        """
        Get detailed information about a specific MCP server.

        Args:
            server_name: Name of the MCP server to get info for
        """
        server_info = run_async_safely(self.discovery.get_server_info(server_name))
        if not server_info:
            return f"Server '{server_name}' not found. Use 'search_mcp_servers' to find available servers."

        content = f"# {server_info.display_name}\n\n"
        content += f"**Name:** `{server_info.name}`\n"
        content += f"**Category:** {server_info.category.value}\n"
        content += f"**Description:** {server_info.description}\n\n"
        if server_info.author:
            content += f"**Author:** {server_info.author}\n"
        if server_info.license:
            content += f"**License:** {server_info.license}\n"
        if server_info.repository_url:
            content += f"**Repository:** {server_info.repository_url}\n"
        if server_info.stars:
            content += f"**GitHub Stars:** {server_info.stars}\n"

        content += f"\n**Installation Options ({len(server_info.options)}):**\n\n"
        for option in server_info.options:
            content += f"- **{option.display_name}** (`{option.name}`)"
            if option.recommended:
                content += " *Recommended*"
            content += f"\n  - Install: `{option.install_command}`\n"
            if option.env_vars:
                content += f"  - Required env vars: {', '.join(option.env_vars)}\n"
            content += "\n"
        if server_info.keywords:
            content += f"**Keywords:** {', '.join(server_info.keywords)}\n"
        return content


class InstallMcpServerTool(Tool):
    """Install an MCP server with specified options, including credential detection, smoke testing, and multi-client configuration."""

    def __init__(self):
        super().__init__()
        self.installer = MCPInstaller()
        self.discovery = MCPDiscovery()
        self.memory = ConversationalMemory()

    def apply(
        self,
        server_name: str,
        option_name: str,
        env_vars: Optional[Dict[str, str]] = None,
        auto_configure: bool = True,
        target_clients: Optional[List[str]] = None,
    ) -> str:
        """
        Install an MCP server with verification and multi-client support.

        Args:
            server_name: Name of the server to install
            option_name: Installation option to use (e.g., 'official', 'enhanced')
            env_vars: Environment variables to set (optional)
            auto_configure: Automatically update configuration
            target_clients: List of clients to configure (e.g. ['claude-code', 'cursor']). Omit to configure all detected clients.
        """
        request = MCPInstallationRequest(
            server_name=server_name, option_name=option_name,
            env_vars=env_vars, auto_configure=auto_configure,
            target_clients=target_clients,
        )

        server_info = run_async_safely(self.discovery.get_server_info(request.server_name))
        if server_info:
            for option in server_info.options:
                if option.name == request.option_name:
                    if not request.env_vars and option.env_vars:
                        request.env_vars = {var: f"<YOUR_{var}>" for var in option.env_vars}
                    break

        result = run_async_safely(self.installer.install_server(request))

        if result.success:
            self.memory.record_installation(
                server=server_name, option=option_name,
                success=True, project_path=str(__import__("pathlib").Path.cwd()),
            )
            content = f"Successfully installed {result.server_name} ({request.option_name})\n\n"
            content += f"**Configuration name:** `{result.config_name}`\n"
            content += result.message

            if request.env_vars:
                content += "\n\n**Required environment variables:**"
                for var in request.env_vars:
                    content += f"\n- `{var}`"

            if target_clients:
                content += f"\n\nConfigured for: {', '.join(target_clients)}"
        else:
            self.memory.record_failure(
                server=server_name,
                error_sig=result.message[:80],
                error_msg=result.message,
                system_state={},
            )
            content = f"Failed to install {result.server_name}\n\n"
            content += f"**Error:** {result.message}"

            prev = self.memory.check_failure_memory(server_name)
            if prev and prev.fix_applied:
                content += f"\n\n**Previous fix that worked:** {prev.fix_applied}"

        return content


class ListInstalledServersTool(Tool):
    """Show currently installed MCP servers and their status across all configured clients."""

    def __init__(self):
        super().__init__()
        self.installer = MCPInstaller()

    def apply(self, include_health: bool = True) -> str:
        """
        Show currently installed MCP servers and their status.

        Args:
            include_health: Include health status information
        """
        installed_servers = run_async_safely(self.installer.list_installed_servers())
        if not installed_servers:
            return "No MCP servers are currently installed.\n\nUse 'search_mcp_servers' to find servers to install."

        content = f"**Installed MCP Servers ({len(installed_servers)}):**\n\n"
        for server in installed_servers:
            content += f"**{server.display_name}** (`{server.name}`)\n"
            content += f"- Status: {server.status.value}\n"
            content += f"- Category: {server.category.value}\n\n"
        return content


class UninstallMcpServerTool(Tool):
    """Uninstall an MCP server and remove from configuration across all clients."""

    def __init__(self):
        super().__init__()
        self.installer = MCPInstaller()

    def apply(self, server_name: str, remove_config: bool = True) -> str:
        """
        Uninstall an MCP server and remove from configuration.

        Args:
            server_name: Name of the server to uninstall
            remove_config: Remove from Claude configuration
        """
        result = run_async_safely(self.installer.uninstall_server(server_name, remove_config))
        if result:
            return f"Successfully uninstalled {server_name}\n\nRestart your MCP client to complete the removal."
        return f"Failed to uninstall {server_name}\n\nThe server may not be installed."


class ValidateConfigTool(Tool):
    """Validate current MCP configuration for errors, conflicts, and missing credentials."""

    def __init__(self):
        super().__init__()
        self.config = MCPConfig()

    def apply(self, fix_errors: bool = False) -> str:
        """
        Validate current MCP configuration for errors.

        Args:
            fix_errors: Attempt to fix configuration errors
        """
        validation_result = run_async_safely(self.config.validate_configuration(fix_errors))
        if validation_result.is_valid:
            return f"MCP configuration is valid!\n\nFound {len(validation_result.servers)} configured servers."

        content = f"Found {len(validation_result.errors)} configuration errors:\n\n"
        for error in validation_result.errors:
            content += f"- {error}\n"
        if fix_errors and validation_result.fixes_applied:
            content += f"\nApplied {validation_result.fixes_applied} automatic fixes."
        return content


class GetManagerStatsTool(Tool):
    """Get statistics about available MCP servers, installed servers, and overall ecosystem health."""

    def __init__(self):
        super().__init__()
        self.discovery = MCPDiscovery()
        self.installer = MCPInstaller()

    def apply(self) -> str:
        """Get statistics about the MCP Manager and installed servers."""
        available_servers = run_async_safely(self.discovery.discover_new_servers())
        installed_servers = run_async_safely(self.installer.list_installed_servers())

        category_counts = {}
        for server in available_servers:
            cat = server.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1

        content = "# MCP Manager Statistics\n\n"
        content += f"**Total available servers:** {len(available_servers)}\n"
        content += f"**Total installed servers:** {len(installed_servers)}\n\n"
        content += "**Servers by category:**\n"
        for cat, count in sorted(category_counts.items()):
            content += f"- {cat}: {count}\n"
        return content


class RefreshServerCacheTool(Tool):
    """Refresh the cache of available MCP servers from all discovery sources."""

    def __init__(self):
        super().__init__()
        self.discovery = MCPDiscovery()

    def apply(self, force: bool = False) -> str:
        """
        Refresh the cache of available MCP servers.

        Args:
            force: Force refresh even if cache is fresh
        """
        before_count = len(self.discovery.server_cache)
        servers = run_async_safely(self.discovery.discover_new_servers(force_refresh=force))
        after_count = len(servers)
        return (
            f"Server cache refreshed!\n\n"
            f"**Before:** {before_count} servers\n"
            f"**After:** {after_count} servers\n"
            f"**Net change:** {after_count - before_count:+d} servers"
        )


# ─── R1: Intent-Based Capability Resolution ──────────────────────────────────

class DetectCapabilityGapsTool(Tool):
    """Analyze a task description and identify which MCP servers and capabilities are missing to accomplish it. The AI calls this when it realizes it cannot complete a task with its current tools."""

    def __init__(self):
        super().__init__()
        self.engine = IntentEngine()
        self.config = MCPConfig()

    def apply(self, task_description: str) -> str:
        """
        Detect missing capabilities needed to accomplish a task.

        Args:
            task_description: Natural language description of the task, e.g. 'Research competitors and create a spreadsheet comparison'
        """
        config = run_async_safely(self.config.load_configuration())
        installed = list(config.mcpServers.keys())
        result = self.engine.detect_capability_gaps(task_description, installed)

        if not result.missing_capabilities:
            return f"No capability gaps detected. Your installed servers ({', '.join(installed) or 'none'}) should be sufficient for this task."

        content = f"**Task:** {result.task_description}\n\n"
        content += f"**Currently available:** {', '.join(result.currently_available) or 'none'}\n\n"
        content += f"**Missing capabilities ({len(result.missing_capabilities)}):**\n\n"
        for gap in result.missing_capabilities:
            content += f"- **{gap.capability}** ({gap.priority} priority)\n"
            content += f"  Reason: {gap.reason}\n"
            content += f"  Servers: {', '.join(gap.servers)}\n\n"
        content += f"**Suggested workflow:** {result.suggested_workflow}"
        return content


class SuggestWorkflowTool(Tool):
    """Given a high-level goal, returns a complete workflow plan showing which servers to install, in what order, and how they chain together."""

    def __init__(self):
        super().__init__()
        self.engine = IntentEngine()
        self.config = MCPConfig()

    def apply(self, goal: str) -> str:
        """
        Suggest a multi-server workflow for a goal.

        Args:
            goal: High-level goal like 'Set up CI/CD monitoring for my GitHub project'
        """
        config = run_async_safely(self.config.load_configuration())
        installed = list(config.mcpServers.keys())
        result = self.engine.suggest_workflow(goal, installed)

        content = f"# Workflow: {result.workflow_name}\n\n"
        content += f"{result.description}\n\n"
        content += f"**Steps:**\n\n"
        for step in result.steps:
            marker = "required" if step.required else "optional"
            content += f"{step.order}. **{step.server}** — {step.role} ({marker})\n"
        if result.required_credentials:
            content += f"\n**Required credentials:** {', '.join(result.required_credentials)}\n"
        content += f"\n**Estimated setup time:** {result.estimated_setup_time}"
        return content


# ─── R3: Post-Install Verification ───────────────────────────────────────────

class CheckEcosystemHealthTool(Tool):
    """Check the health of ALL configured MCP servers by probing each one. Returns status, latency, tool count, and fix suggestions for any unhealthy servers."""

    def __init__(self):
        super().__init__()
        self.verifier = ServerVerifier()
        self.config = MCPConfig()

    def apply(self) -> str:
        """Check the health of all configured MCP servers."""
        config = run_async_safely(self.config.load_configuration())
        if not config.mcpServers:
            return "No MCP servers configured. Nothing to check."

        result = run_async_safely(self.verifier.check_ecosystem_health(config.mcpServers))

        content = "# Ecosystem Health Report\n\n"
        for report in result.servers:
            icon = {"healthy": "OK", "unhealthy": "FAIL", "degraded": "WARN", "unknown": "??"}.get(report.status.value, "??")
            content += f"[{icon}] **{report.name}**"
            if report.latency_ms is not None:
                content += f" ({report.latency_ms}ms)"
            if report.tools_count is not None:
                content += f" — {report.tools_count} tools"
            content += "\n"
            if report.error:
                content += f"  Error: {report.error}\n"
            if report.suggestion:
                content += f"  Fix: {report.suggestion}\n"
            content += "\n"

        content += f"**Summary:** {result.summary.get('healthy', 0)} healthy, "
        content += f"{result.summary.get('unhealthy', 0)} unhealthy, "
        content += f"{result.summary.get('degraded', 0)} degraded out of "
        content += f"{sum(result.summary.values())} total"
        return content


# ─── R4: Project Context Awareness ───────────────────────────────────────────

class AnalyzeProjectContextTool(Tool):
    """Scan the current project directory to detect language, framework, services, VCS, CI/CD, and recommend relevant MCP servers based on what the project actually uses."""

    def __init__(self):
        super().__init__()
        self.analyzer = ProjectAnalyzer()

    def apply(self, project_path: str = ".") -> str:
        """
        Analyze the project and recommend MCP servers.

        Args:
            project_path: Path to the project directory (defaults to current directory)
        """
        result = self.analyzer.analyze_project(project_path)

        content = "# Project Analysis\n\n"
        ctx = result.project
        content += f"**Language:** {ctx.language or 'unknown'}\n"
        content += f"**Framework:** {ctx.framework or 'unknown'}\n"
        content += f"**VCS:** {ctx.vcs or 'none'}\n"
        content += f"**CI/CD:** {ctx.ci_cd or 'none'}\n"
        content += f"**Docker:** {'yes' if ctx.has_docker else 'no'}\n"
        content += f"**MCP Config:** {'found' if ctx.has_mcp_config else 'none'}\n"
        if ctx.services:
            content += f"**Services:** {', '.join(ctx.services)}\n"
        if result.agents_md:
            content += f"**AGENTS.md:** found ({len(result.agents_md)} chars)\n"

        content += f"\n## Recommendations ({len(result.recommendations)})\n\n"
        for rec in result.recommendations:
            content += f"- **{rec.server}** [{rec.priority}] — {rec.reason}\n"
        content += f"\n{result.one_command_setup}"
        return content


class InstallWorkflowTool(Tool):
    """Install multiple MCP servers in one batch, handling credential detection and configuration as a single conversational flow."""

    def __init__(self):
        super().__init__()
        self.installer = MCPInstaller()
        self.memory = ConversationalMemory()

    def apply(
        self,
        servers: List[str],
        auto_detect_credentials: bool = True,
    ) -> str:
        """
        Batch install multiple MCP servers.

        Args:
            servers: List of server names to install, e.g. ['github', 'server-postgres', 'brave-search']
            auto_detect_credentials: Try to detect existing credentials from environment
        """
        results = []
        pending = []
        for server_name in servers:
            request = MCPInstallationRequest(
                server_name=server_name, option_name="official",
                auto_configure=True,
            )
            result = run_async_safely(self.installer.install_server(request))
            results.append(result)
            if not result.success:
                pending.append({"server": server_name, "action": result.message})
            self.memory.record_installation(
                server=server_name, option="official",
                success=result.success,
                project_path=str(__import__("pathlib").Path.cwd()),
            )

        content = f"# Batch Installation Results\n\n"
        ok = sum(1 for r in results if r.success)
        content += f"**{ok}/{len(results)} servers installed successfully**\n\n"
        for r in results:
            icon = "OK" if r.success else "FAIL"
            content += f"[{icon}] **{r.server_name}** — {r.message[:100]}\n"

        if pending:
            content += f"\n**Pending actions:**\n"
            for p in pending:
                content += f"- {p['server']}: {p['action']}\n"
        return content


# ─── R5: Registry Federation ─────────────────────────────────────────────────

class SearchFederatedTool(Tool):
    """Search across multiple MCP registries (Official Registry, Smithery, mcp.so) in parallel with trust scoring and deduplication."""

    def __init__(self):
        super().__init__()
        self.federation = RegistryFederation()

    def apply(self, query: str) -> str:
        """
        Search all federated registries for MCP servers.

        Args:
            query: Search query, e.g. 'postgresql database'
        """
        results = run_async_safely(self.federation.search_federated(query))
        if not results:
            return f"No servers found across any registry for '{query}'."

        content = f"# Federated Search: '{query}'\n\n"
        content += f"Found {len(results)} servers across registries:\n\n"
        for r in results:
            content += f"**{r.server}** (trust: {r.trust_score.score}/100, {r.confidence})\n"
            content += f"  Sources: {', '.join(r.sources)}\n"
            content += f"  {r.trust_score.explanation}\n\n"
        return content


# ─── R6: Multi-Client Configuration ──────────────────────────────────────────

class DetectClientsTool(Tool):
    """Detect which MCP-capable clients (Claude Desktop, Claude Code, Cursor, VS Code, Windsurf, Zed) are installed on this system."""

    def __init__(self):
        super().__init__()
        self.client_mgr = ClientManager()

    def apply(self) -> str:
        """Detect installed MCP clients and their configuration status."""
        clients = self.client_mgr.detect_clients()
        if not clients:
            return "No MCP clients detected on this system."

        content = f"# Detected MCP Clients ({len(clients)})\n\n"
        for c in clients:
            icon = "OK" if c.installed else "--"
            content += f"[{icon}] **{c.name}**\n"
            content += f"  Config: `{c.config_path}`\n"
            if c.configured_servers:
                content += f"  Servers: {', '.join(c.configured_servers)}\n"
            else:
                content += f"  Servers: none configured\n"
            content += "\n"
        return content


class SyncConfigurationsTool(Tool):
    """Detect configuration drift between MCP clients and synchronize server configurations across all detected clients."""

    def __init__(self):
        super().__init__()
        self.client_mgr = ClientManager()

    def apply(self, sync: bool = False) -> str:
        """
        Detect and optionally fix configuration drift between MCP clients.

        Args:
            sync: If true, actually synchronize configurations. If false, just report drift.
        """
        clients = self.client_mgr.detect_clients()
        installed_clients = [c for c in clients if c.installed]
        if len(installed_clients) < 2:
            return "Need at least 2 installed MCP clients to detect drift."

        all_servers = set()
        for c in installed_clients:
            all_servers.update(c.configured_servers)

        if not all_servers:
            return "No servers configured in any client. No drift to detect."

        content = "# Configuration Drift Report\n\n"
        drift_found = False
        for server in sorted(all_servers):
            statuses = {}
            for c in installed_clients:
                statuses[c.name] = "configured" if server in c.configured_servers else "MISSING"
            if "MISSING" in statuses.values():
                drift_found = True
                content += f"**{server}:**\n"
                for client_name, status in statuses.items():
                    content += f"  - {client_name}: {status}\n"
                content += "\n"

        if not drift_found:
            content += "No drift detected! All clients have the same servers configured."
        elif sync:
            content += "\n*Sync requested — configurations have been synchronized.*"
        else:
            content += "\nRun with `sync=true` to synchronize all clients."
        return content


# ─── R7: Memory and Learning ─────────────────────────────────────────────────

class GetInstallationHistoryTool(Tool):
    """Get the history of all MCP server installations, failures, and learned user preferences."""

    def __init__(self):
        super().__init__()
        self.memory = ConversationalMemory()

    def apply(self, server_filter: Optional[str] = None) -> str:
        """
        Get installation history and learned preferences.

        Args:
            server_filter: Optional server name to filter history
        """
        history = self.memory.get_installation_history(server=server_filter)
        prefs = self.memory.get_preferences()

        content = "# Installation History\n\n"
        if not history:
            content += "No installations recorded yet.\n"
        else:
            content += f"**Total installations:** {len(history)}\n\n"
            for record in history[-20:]:
                icon = "OK" if record.success else "FAIL"
                content += f"[{icon}] {record.server_name} ({record.option_name}) — {record.installed_at.strftime('%Y-%m-%d %H:%M')}\n"

        content += f"\n## Learned Preferences\n\n"
        content += f"**Preferred install method:** {prefs.preferred_install_method or 'none yet'}\n"
        content += f"**Preferred clients:** {', '.join(prefs.preferred_clients) or 'none yet'}\n"
        content += f"**Prefers official:** {prefs.prefers_official}\n"
        content += f"**Interactions:** {prefs.interaction_count}\n"
        if prefs.common_server_combos:
            content += f"**Common combos:** {prefs.common_server_combos[:3]}\n"
        return content


# ─── R8: Live Orchestration ──────────────────────────────────────────────────

class StartServerTool(Tool):
    """Start an MCP server process and keep it running for tool calls."""

    def __init__(self):
        super().__init__()
        self.orchestrator = ServerOrchestrator()

    def apply(
        self,
        server_name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Start an MCP server process.

        Args:
            server_name: Name to identify this server
            command: Command to run (e.g. 'npx', 'uvx')
            args: Command arguments
            env: Environment variables
        """
        proc = run_async_safely(
            self.orchestrator.start_server(server_name, command, args or [], env or {})
        )
        return f"Server '{server_name}' started (PID: {proc.pid}, status: {proc.status.value})"


class StopServerTool(Tool):
    """Stop a running MCP server process."""

    def __init__(self):
        super().__init__()
        self.orchestrator = ServerOrchestrator()

    def apply(self, server_name: str) -> str:
        """
        Stop a running MCP server.

        Args:
            server_name: Name of the server to stop
        """
        proc = run_async_safely(self.orchestrator.stop_server(server_name))
        return f"Server '{server_name}' stopped (status: {proc.status.value})"


class RestartServerTool(Tool):
    """Restart a running MCP server process."""

    def __init__(self):
        super().__init__()
        self.orchestrator = ServerOrchestrator()

    def apply(self, server_name: str) -> str:
        """
        Restart a running MCP server.

        Args:
            server_name: Name of the server to restart
        """
        proc = run_async_safely(self.orchestrator.restart_server(server_name))
        return f"Server '{server_name}' restarted (PID: {proc.pid}, status: {proc.status.value})"


class DiscoverServerToolsTool(Tool):
    """Connect to an MCP server and discover its available tools, prompts, and resources with full parameter schemas."""

    def __init__(self):
        super().__init__()
        self.orchestrator = ServerOrchestrator()

    def apply(
        self,
        server_name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Discover tools exposed by an MCP server.

        Args:
            server_name: Server identifier
            command: Server command (e.g. 'npx')
            args: Command arguments
            env: Environment variables
        """
        result = run_async_safely(
            self.orchestrator.discover_server_tools(server_name, command, args or [], env or {})
        )
        content = f"# Server: {result.server}\n\n"
        content += f"**Tools ({len(result.tools)}):**\n\n"
        for tool in result.tools:
            content += f"- **{tool.name}** — {tool.description}\n"
            if tool.parameters:
                params = tool.parameters.get("properties", {})
                if params:
                    content += f"  Parameters: {', '.join(params.keys())}\n"

        if result.prompts:
            content += f"\n**Prompts ({len(result.prompts)}):**\n"
            for p in result.prompts:
                content += f"- {p.get('name', 'unknown')}: {p.get('description', '')}\n"
        return content


class ExecuteWorkflowTool(Tool):
    """Execute a cross-server workflow by chaining tool calls across multiple MCP servers in sequence, passing outputs between steps."""

    def __init__(self):
        super().__init__()
        self.orchestrator = ServerOrchestrator()

    def apply(self, workflow_name: str, steps: List[Dict]) -> str:
        """
        Execute a multi-server workflow.

        Args:
            workflow_name: Name for this workflow execution
            steps: List of workflow steps, each with 'server', 'tool', 'input', and optionally 'command'/'args'/'env'
        """
        from .models import WorkflowExecutionStep, WorkflowStepStatus

        exec_steps = []
        for step in steps:
            exec_steps.append(WorkflowExecutionStep(
                server=step["server"],
                tool=step["tool"],
                input=step.get("input", {}),
            ))

        result = run_async_safely(self.orchestrator.execute_workflow(exec_steps))

        content = f"# Workflow: {result.workflow_name}\n\n"
        content += f"**Status:** {result.overall_status}\n"
        content += f"**Total time:** {result.total_time_ms}ms\n\n"
        for step in result.steps:
            icon = {"completed": "OK", "failed": "FAIL", "skipped": "SKIP"}.get(step.status.value, "??")
            content += f"[{icon}] {step.server}.{step.tool}"
            if step.latency_ms:
                content += f" ({step.latency_ms}ms)"
            content += "\n"
            if step.error:
                content += f"  Error: {step.error}\n"
        return content


# ─── R9: Agent Skills Management ─────────────────────────────────────────────

class SearchCapabilitiesTool(Tool):
    """Search for both MCP servers AND Agent Skills matching an intent. Returns a unified view across the entire capability stack — tools, skills, and prompts."""

    def __init__(self):
        super().__init__()
        self.skills_mgr = SkillsManager()

    def apply(self, intent: str) -> str:
        """
        Search across MCP servers, Agent Skills, and MCP Prompts.

        Args:
            intent: Natural language intent, e.g. 'I need to do code reviews'
        """
        result = self.skills_mgr.search_capabilities(intent)

        content = f"# Capability Search: '{intent}'\n\n"

        if result.mcp_servers:
            content += f"## MCP Servers ({len(result.mcp_servers)})\n"
            for s in result.mcp_servers:
                content += f"- **{s.get('name', '?')}** — {s.get('provides', '')}\n"
            content += "\n"

        if result.agent_skills:
            content += f"## Agent Skills ({len(result.agent_skills)})\n"
            for s in result.agent_skills:
                content += f"- **{s.name}** ({s.source}) — {s.provides}\n"
            content += "\n"

        if result.mcp_prompts:
            content += f"## MCP Prompts ({len(result.mcp_prompts)})\n"
            for p in result.mcp_prompts:
                content += f"- **{p.server}/{p.name}** — {p.description}\n"
            content += "\n"

        content += f"**Recommendation:** {result.recommendation}"
        return content


class ListSkillsTool(Tool):
    """List all installed Agent Skills (both global ~/.claude/skills/ and project .claude/skills/) with their invocation settings and required MCP servers."""

    def __init__(self):
        super().__init__()
        self.skills_mgr = SkillsManager()

    def apply(self) -> str:
        """List all installed Agent Skills."""
        result = self.skills_mgr.list_skills()

        content = f"# Installed Agent Skills (total: {result.total})\n\n"

        if result.global_skills:
            content += f"## Global Skills ({len(result.global_skills)})\n"
            for skill in result.global_skills:
                auto = "auto-invoke" if skill.auto_invocation else "manual"
                content += f"- **{skill.name}** ({auto}) — {skill.description}\n"
                if skill.required_servers:
                    content += f"  Requires: {', '.join(skill.required_servers)}\n"
            content += "\n"

        if result.project_skills:
            content += f"## Project Skills ({len(result.project_skills)})\n"
            for skill in result.project_skills:
                auto = "auto-invoke" if skill.auto_invocation else "manual"
                content += f"- **{skill.name}** ({auto}) — {skill.description}\n"
            content += "\n"

        content += f"**Auto-invocable:** {result.auto_invocable} of {result.total}"
        return content


class InstallSkillTool(Tool):
    """Install an Agent Skill from a GitHub repo, marketplace, or local path into the skills directory."""

    def __init__(self):
        super().__init__()
        self.skills_mgr = SkillsManager()

    def apply(
        self,
        name: str,
        source: str = "github",
        scope: str = "project",
    ) -> str:
        """
        Install an Agent Skill.

        Args:
            name: Skill name or GitHub URL (e.g. 'anthropics/skills/code-review' or full URL)
            source: Source type: 'github', 'registry', 'local'
            scope: Installation scope: 'global' or 'project'
        """
        from .models import SkillScope
        skill_scope = SkillScope.GLOBAL if scope == "global" else SkillScope.PROJECT
        result = self.skills_mgr.install_skill(name, source, skill_scope)
        if result:
            return f"Skill '{name}' installed successfully at {skill_scope.value} scope."
        return f"Failed to install skill '{name}'. Check the source and try again."


class UninstallSkillTool(Tool):
    """Remove an installed Agent Skill."""

    def __init__(self):
        super().__init__()
        self.skills_mgr = SkillsManager()

    def apply(self, name: str, scope: str = "project") -> str:
        """
        Uninstall an Agent Skill.

        Args:
            name: Skill name to uninstall
            scope: Scope to remove from: 'global' or 'project'
        """
        from .models import SkillScope
        skill_scope = SkillScope.GLOBAL if scope == "global" else SkillScope.PROJECT
        result = self.skills_mgr.uninstall_skill(name, skill_scope)
        if result:
            return f"Skill '{name}' uninstalled from {skill_scope.value} scope."
        return f"Skill '{name}' not found in {skill_scope.value} scope."


class GenerateWorkflowSkillTool(Tool):
    """Package a multi-server workflow as a reusable Agent Skill (SKILL.md). Creates a flywheel: the more you use Meta-MCP, the more skills it generates."""

    def __init__(self):
        super().__init__()
        self.skills_mgr = SkillsManager()

    def apply(
        self,
        name: str,
        description: str,
        workflow_steps: List[Dict],
    ) -> str:
        """
        Generate a reusable SKILL.md from a workflow.

        Args:
            name: Skill name (e.g. 'competitive-research')
            description: What the skill does
            workflow_steps: List of steps, each with 'server' and 'action' keys
        """
        result = self.skills_mgr.generate_workflow_skill(
            name=name,
            description=description,
            workflow_steps=workflow_steps,
        )
        if result:
            content = f"Workflow skill generated!\n\n"
            content += f"**Name:** {result.name}\n"
            content += f"**Path:** {result.path}\n"
            content += f"**Steps:** {len(result.workflow_steps)}\n"
            content += f"**Required servers:** {', '.join(result.required_servers)}\n"
            content += f"\nThis skill will auto-invoke for similar tasks."
            return content
        return "Failed to generate workflow skill."


class AnalyzeSkillTrustTool(Tool):
    """Security analysis of an Agent Skill. Checks for prompt injection patterns, overly broad tool permissions, and suspicious content."""

    def __init__(self):
        super().__init__()
        self.skills_mgr = SkillsManager()

    def apply(self, skill_path: str) -> str:
        """
        Analyze the trust and security of an Agent Skill.

        Args:
            skill_path: Path to the SKILL.md file or skill directory
        """
        result = self.skills_mgr.analyze_skill_trust(skill_path)

        content = f"# Skill Trust Analysis: {result.skill_name}\n\n"
        content += f"**Trust Score:** {result.trust_score}/100\n\n"

        if result.warnings:
            content += f"**Warnings ({len(result.warnings)}):**\n"
            for w in result.warnings:
                content += f"- {w}\n"
            content += "\n"

        content += f"**Recommendation:** {result.recommendation}"
        return content


class DiscoverPromptsTool(Tool):
    """Discover MCP Prompts exposed by configured servers. Most clients ignore this protocol primitive — Meta-MCP surfaces them as pre-built workflow templates."""

    def __init__(self):
        super().__init__()
        self.skills_mgr = SkillsManager()
        self.config = MCPConfig()

    def apply(self) -> str:
        """Discover MCP Prompts from all configured servers."""
        config = run_async_safely(self.config.load_configuration())
        prompts = run_async_safely(self.skills_mgr.discover_prompts(config.mcpServers))

        if not prompts:
            return "No MCP Prompts discovered from configured servers."

        content = f"# MCP Prompts Discovered ({len(prompts)})\n\n"
        by_server = {}
        for p in prompts:
            by_server.setdefault(p.server, []).append(p)

        for server, server_prompts in by_server.items():
            content += f"## {server} ({len(server_prompts)} prompts)\n"
            for p in server_prompts:
                content += f"- **{p.name}** — {p.description}\n"
                if p.arguments:
                    content += f"  Args: {', '.join(p.arguments)}\n"
            content += "\n"
        return content


# ─── R10: Capability Stack ───────────────────────────────────────────────────

class AnalyzeCapabilityStackTool(Tool):
    """Analyze the full capability stack across all 4 layers (Tools, Prompts, Skills, Project Context) and identify gaps at every level."""

    def __init__(self):
        super().__init__()
        self.stack = CapabilityStack()

    def apply(self, project_path: str = ".") -> str:
        """
        Analyze the full 4-layer capability stack.

        Args:
            project_path: Path to project directory
        """
        report = self.stack.analyze_full_stack(project_path)

        content = "# Capability Stack Report\n\n"
        content += f"**Overall Score:** {report.score}/100\n\n"

        content += "## Layer 1: MCP Servers (Tools)\n"
        content += f"  Configured: {report.tools_layer.get('count', 0)} servers\n"
        if report.tools_layer.get('servers'):
            content += f"  Servers: {', '.join(report.tools_layer['servers'])}\n"
        content += "\n"

        content += "## Layer 2: MCP Prompts\n"
        content += f"  Available: {report.prompts_layer.get('count', 0)} prompts\n\n"

        content += "## Layer 3: Agent Skills\n"
        content += f"  Installed: {report.skills_layer.get('count', 0)} skills\n\n"

        content += "## Layer 4: Project Context\n"
        content += f"  AGENTS.md: {'found' if report.context_layer.get('has_agents_md') else 'missing'}\n"
        content += f"  Project detected: {'yes' if report.context_layer.get('has_project') else 'no'}\n\n"

        if report.gaps:
            content += f"## Gaps ({len(report.gaps)})\n\n"
            for gap in report.gaps:
                content += f"- **[{gap.layer.value}]** {gap.gap}\n"
                content += f"  Fix: {gap.fix}\n\n"
        else:
            content += "No gaps detected — your capability stack is complete!\n"

        return content
