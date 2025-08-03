"""
FastMCP-based Meta MCP Server implementation.

This follows the Serena pattern using FastMCP to avoid CallToolResult iteration issues.
"""

import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp.server import FastMCP
from mcp.server.fastmcp.tools.base import Tool as MCPTool

from .tools import (
    SearchMcpServersTool,
    GetServerInfoTool,
    InstallMcpServerTool,
    ListInstalledServersTool,
    UninstallMcpServerTool,
    ValidateConfigTool,
    GetManagerStatsTool,
    RefreshServerCacheTool,
)


def create_mcp_tool(tool_instance) -> MCPTool:
    """
    Convert a Meta MCP tool to a FastMCP tool.

    This follows the exact pattern from Serena's implementation.
    """
    func_name = tool_instance.get_name()
    func_doc = tool_instance.get_apply_docstring() or ""
    func_arg_metadata = tool_instance.get_apply_fn_metadata()
    is_async = False
    parameters = func_arg_metadata.arg_model.model_json_schema()

    def execute_fn(**kwargs) -> str:
        return tool_instance.apply_ex(log_call=True, catch_exceptions=True, **kwargs)

    return MCPTool(
        fn=execute_fn,
        name=func_name,
        description=func_doc,
        parameters=parameters,
        fn_metadata=func_arg_metadata,
        is_async=is_async,
        context_kwarg=None,
        annotations=None,
        title=None,
    )


class MetaMCPServer:
    """FastMCP-based Meta MCP Server."""

    def __init__(self):
        """Initialize the server with all tools."""
        self.tools = [
            SearchMcpServersTool(),
            GetServerInfoTool(),
            InstallMcpServerTool(),
            ListInstalledServersTool(),
            UninstallMcpServerTool(),
            ValidateConfigTool(),
            GetManagerStatsTool(),
            RefreshServerCacheTool(),
        ]

    def create_fastmcp_server(self, host: str = "0.0.0.0", port: int = 8000) -> FastMCP:
        """Create a FastMCP server instance."""
        mcp = FastMCP(host=host, port=port, lifespan=self.server_lifespan)
        return mcp

    @asynccontextmanager
    async def server_lifespan(self, mcp_server: FastMCP) -> AsyncIterator[None]:
        """Manage server startup and shutdown with tool registration."""
        try:
            # Register all tools with the FastMCP server
            for tool_instance in self.tools:
                mcp_tool = create_mcp_tool(tool_instance)
                mcp_server._tool_manager._tools[tool_instance.get_name()] = mcp_tool

            print("Meta MCP Server: All tools registered successfully", file=sys.stderr)
            print(
                f"Meta MCP Server: Registered {len(self.tools)} tools:", file=sys.stderr
            )
            for tool in self.tools:
                print(f"  - {tool.get_name()}", file=sys.stderr)
            print("Meta MCP Server: Ready to handle requests", file=sys.stderr)

            yield

        except Exception as e:
            print(f"Meta MCP Server: Error during startup: {e}", file=sys.stderr)
            raise
        finally:
            print("Meta MCP Server: Shutting down", file=sys.stderr)


async def create_server() -> FastMCP:
    """Create and return a configured FastMCP server."""
    server = MetaMCPServer()
    return server.create_fastmcp_server()
