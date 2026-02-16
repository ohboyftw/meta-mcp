"""
Meta MCP Server - A FastMCP-based MCP server manager.

Exposes 30+ tools covering R1-R10 plus project init:
- Core: search, info, install, list, uninstall, validate, stats, refresh
- R1: detect_capability_gaps, suggest_workflow
- R3: check_ecosystem_health
- R4: analyze_project_context, install_workflow
- R5: search_federated
- R6: detect_clients, sync_configurations
- R7: get_installation_history
- R8: start_server, stop_server, restart_server, discover_server_tools, execute_workflow
- R9: search_capabilities, list_skills, install_skill, uninstall_skill, generate_workflow_skill, analyze_skill_trust, discover_prompts
- R10: analyze_capability_stack
"""

import functools
import inspect
import traceback

from mcp.server.fastmcp import FastMCP

from .tools import (
    # Core tools
    SearchMcpServersTool,
    GetServerInfoTool,
    InstallMcpServerTool,
    ListInstalledServersTool,
    UninstallMcpServerTool,
    ValidateConfigTool,
    GetManagerStatsTool,
    RefreshServerCacheTool,
    # R1: Intent-Based Resolution
    DetectCapabilityGapsTool,
    SuggestWorkflowTool,
    # R3: Verification
    CheckEcosystemHealthTool,
    # R4: Project Context
    AnalyzeProjectContextTool,
    InstallWorkflowTool,
    # R5: Registry Federation
    SearchFederatedTool,
    # R6: Multi-Client
    DetectClientsTool,
    SyncConfigurationsTool,
    # R7: Memory
    GetInstallationHistoryTool,
    # R8: Orchestration
    StartServerTool,
    StopServerTool,
    RestartServerTool,
    DiscoverServerToolsTool,
    ExecuteWorkflowTool,
    # R9: Skills
    SearchCapabilitiesTool,
    ListSkillsTool,
    InstallSkillTool,
    UninstallSkillTool,
    GenerateWorkflowSkillTool,
    AnalyzeSkillTrustTool,
    DiscoverPromptsTool,
    # R10: Capability Stack
    AnalyzeCapabilityStackTool,
    # Project Init
    ProjectInitTool,
    ProjectValidateTool,
)
from .tools_base import Tool


class MetaMCPServer:
    """Meta MCP Server - manages discovery, installation, and lifecycle of MCP servers, skills, and capabilities."""

    def __init__(self):
        self.tools = self._initialize_tools()

    def _initialize_tools(self):
        return [
            # Core management
            SearchMcpServersTool(),
            GetServerInfoTool(),
            InstallMcpServerTool(),
            ListInstalledServersTool(),
            UninstallMcpServerTool(),
            ValidateConfigTool(),
            GetManagerStatsTool(),
            RefreshServerCacheTool(),
            # R1: Intent-Based Capability Resolution
            DetectCapabilityGapsTool(),
            SuggestWorkflowTool(),
            # R3: Post-Install Verification
            CheckEcosystemHealthTool(),
            # R4: Project Context Awareness
            AnalyzeProjectContextTool(),
            InstallWorkflowTool(),
            # R5: Registry Federation
            SearchFederatedTool(),
            # R6: Multi-Client Configuration
            DetectClientsTool(),
            SyncConfigurationsTool(),
            # R7: Memory and Learning
            GetInstallationHistoryTool(),
            # R8: Live Orchestration
            StartServerTool(),
            StopServerTool(),
            RestartServerTool(),
            DiscoverServerToolsTool(),
            ExecuteWorkflowTool(),
            # R9: Agent Skills
            SearchCapabilitiesTool(),
            ListSkillsTool(),
            InstallSkillTool(),
            UninstallSkillTool(),
            GenerateWorkflowSkillTool(),
            AnalyzeSkillTrustTool(),
            DiscoverPromptsTool(),
            # R10: Capability Stack
            AnalyzeCapabilityStackTool(),
            # Project Init
            ProjectInitTool(),
            ProjectValidateTool(),
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
