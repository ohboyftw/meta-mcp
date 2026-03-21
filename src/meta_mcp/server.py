"""
Meta MCP Server - A FastMCP-based MCP server manager.

Exposes 31 tools organized in 3 tiers:
- Tier 1 (Sync & Bootstrap): detect_clients, sync_configurations, validate_config, project_init, project_validate
- Tier 2 (Skills & Repo): search_capabilities, list_skills, install_skill, uninstall_skill, analyze_skill_trust,
  list_repo_skills, search_repo, install_from_repo, batch_install_from_repo, list_repo_servers, add_skill_repo
- Tier 3 (Server Lifecycle): search_mcp_servers, get_server_info, install_mcp_server, list_installed_servers,
  uninstall_mcp_server, search_federated, refresh_server_cache, get_manager_stats, analyze_project_context,
  install_workflow, check_ecosystem_health, start_server, stop_server, restart_server, discover_server_tools
"""

import functools
import inspect
import traceback

from mcp.server.fastmcp import FastMCP

from .tools import (
    # Tier 1: Sync & Bootstrap
    DetectClientsTool,
    SyncConfigurationsTool,
    ValidateConfigTool,
    ProjectInitTool,
    ProjectValidateTool,
    # Tier 2: Skills & Repo
    SearchCapabilitiesTool,
    ListSkillsTool,
    InstallSkillTool,
    UninstallSkillTool,
    AnalyzeSkillTrustTool,
    ListRepoSkillsTool,
    SearchRepoTool,
    InstallFromRepoTool,
    BatchInstallFromRepoTool,
    ListRepoServersTool,
    AddSkillRepoTool,
    # Tier 3: Server Lifecycle
    SearchMcpServersTool,
    GetServerInfoTool,
    InstallMcpServerTool,
    ListInstalledServersTool,
    UninstallMcpServerTool,
    SearchFederatedTool,
    RefreshServerCacheTool,
    GetManagerStatsTool,
    AnalyzeProjectContextTool,
    InstallWorkflowTool,
    CheckEcosystemHealthTool,
    StartServerTool,
    StopServerTool,
    RestartServerTool,
    DiscoverServerToolsTool,
)
from .tools_base import Tool


class MetaMCPServer:
    """Meta MCP Server - manages discovery, installation, and lifecycle of MCP servers, skills, and capabilities."""

    def __init__(self):
        self.tools = self._initialize_tools()

    def _initialize_tools(self):
        return [
            # ── Tier 1: Sync & Bootstrap ──────────────────────────────
            DetectClientsTool(),
            SyncConfigurationsTool(),
            ValidateConfigTool(),
            ProjectInitTool(),
            ProjectValidateTool(),
            # ── Tier 2: Skills & Repo ─────────────────────────────────
            SearchCapabilitiesTool(),
            ListSkillsTool(),
            InstallSkillTool(),
            UninstallSkillTool(),
            AnalyzeSkillTrustTool(),
            ListRepoSkillsTool(),
            SearchRepoTool(),
            InstallFromRepoTool(),
            BatchInstallFromRepoTool(),
            ListRepoServersTool(),
            AddSkillRepoTool(),
            # ── Tier 3: Server Lifecycle ──────────────────────────────
            SearchMcpServersTool(),
            GetServerInfoTool(),
            InstallMcpServerTool(),
            ListInstalledServersTool(),
            UninstallMcpServerTool(),
            SearchFederatedTool(),
            RefreshServerCacheTool(),
            GetManagerStatsTool(),
            AnalyzeProjectContextTool(),
            InstallWorkflowTool(),
            CheckEcosystemHealthTool(),
            StartServerTool(),
            StopServerTool(),
            RestartServerTool(),
            DiscoverServerToolsTool(),
        ]

    @staticmethod
    def _wrap_tool(tool_instance: "Tool"):
        """Create a wrapper that preserves apply()'s signature for FastMCP schema generation,
        while adding logging and error handling from apply_ex."""

        @functools.wraps(tool_instance.apply)
        def wrapper(**kwargs):
            try:
                print(f"Calling {tool_instance.get_name()} with args: {kwargs}")
                result = tool_instance.apply(**kwargs)
                print(f"Result: {result[:200]}{'...' if len(result) > 200 else ''}")
                return result
            except Exception as e:
                error_msg = f"Error executing tool {tool_instance.get_name()}: {e}"
                print(f"Error: {error_msg}")
                print(f"Traceback: {traceback.format_exc()}")
                return error_msg

        # Ensure the signature matches apply() exactly so FastMCP generates
        # correct parameter schemas (not a generic **kwargs string param).
        wrapper.__signature__ = inspect.signature(tool_instance.apply)
        return wrapper

    def create_fastmcp_server(self, host: str = "0.0.0.0", port: int = 8000) -> FastMCP:
        mcp = FastMCP(
            "Meta MCP Server",
            host=host,
            port=port,
        )

        for tool_instance in self.tools:
            name = tool_instance.get_name()
            description = tool_instance.__class__.__doc__ or tool_instance.get_apply_docstring()
            fn = self._wrap_tool(tool_instance)

            mcp.tool(name=name, description=description)(fn)

        return mcp
