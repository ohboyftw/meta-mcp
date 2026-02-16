"""
Command-line interface for Meta MCP Server.
"""

import asyncio
import sys
from typing import Optional

import click

from .server import MetaMCPServer


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to for HTTP mode")
@click.option("--port", default=8000, help="Port to bind to for HTTP mode")
@click.option("--stdio", is_flag=True, help="Use stdio transport (default)")
@click.option("--http", is_flag=True, help="Use HTTP transport")
@click.option(
    "--gateway",
    is_flag=True,
    help="Run in gateway mode (lean proxy, dynamic tool loading)",
)
def main(host: str, port: int, stdio: bool, http: bool, gateway: bool):
    """
    Meta MCP Server - A FastMCP-based MCP server manager.

    This server provides tools for discovering, installing, and managing
    other MCP servers using the proven FastMCP pattern.

    Use --gateway for lean mode: only ~8 tools loaded at startup,
    backend servers activated on demand to save context tokens.
    """
    if gateway:
        run_gateway_server(transport="sse" if http else "stdio")
    elif http:
        run_http_server(host, port)
    else:
        run_stdio_server()


def run_gateway_server(transport: str = "stdio"):
    """Run the server in gateway mode (lean proxy)."""
    from .gateway import GatewayServer

    server = GatewayServer()

    try:
        server.run(transport=transport)
    except KeyboardInterrupt:
        print("Meta MCP Gateway: Interrupted by user", file=sys.stderr)
    except Exception as e:
        print(f"Meta MCP Gateway: Error: {e}", file=sys.stderr)
        raise


def run_stdio_server():
    """Run the server in stdio mode."""
    server = MetaMCPServer()
    mcp = server.create_fastmcp_server()

    print("Meta MCP Server starting in stdio mode...", file=sys.stderr)

    # Run the server and keep it alive
    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        print("Meta MCP Server: Interrupted by user", file=sys.stderr)
    except Exception as e:
        print(f"Meta MCP Server: Error running stdio: {e}", file=sys.stderr)
        raise


def run_http_server(host: str, port: int):
    """Run the server in HTTP mode."""
    server = MetaMCPServer()
    mcp = server.create_fastmcp_server(host=host, port=port)

    print(f"Meta MCP Server starting on http://{host}:{port}", file=sys.stderr)
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
