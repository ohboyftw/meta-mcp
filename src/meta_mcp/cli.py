"""
Command-line interface for Meta MCP Server.
"""

import asyncio
import json
import sys
from typing import Optional

import click

from .server import MetaMCPServer
from .installer import MCPInstaller


@click.group()
def main():
    """Meta MCP Server - A FastMCP-based MCP server manager."""
    pass


@main.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to for HTTP mode")
@click.option("--port", default=8000, help="Port to bind to for HTTP mode")
@click.option("--stdio", is_flag=True, help="Use stdio transport (default)")
@click.option("--http", is_flag=True, help="Use HTTP transport")
def serve(host: str, port: int, stdio: bool, http: bool):
    """Start the Meta MCP Server."""
    if http:
        # HTTP mode - run FastMCP server directly
        run_http_server(host, port)
    else:
        # Default: stdio mode
        run_stdio_server()


@main.command()
@click.option("--format", "output_format", default="table", type=click.Choice(["table", "json"]), help="Output format")
def stats(output_format: str):
    """Show installation statistics and analysis."""
    async def _show_stats():
        installer = MCPInstaller()
        stats_data = await installer.get_installation_stats()
        
        if output_format == "json":
            print(json.dumps(stats_data, indent=2, default=str))
        else:
            # Table format
            print("\n=== MCP Installation Statistics ===")
            print(f"Total Attempts: {stats_data.get('total_attempts', 0)}")
            print(f"Successful Installs: {stats_data.get('successful_installs', 0)}")
            print(f"Failed Installs: {stats_data.get('failed_installs', 0)}")
            
            if stats_data.get('total_attempts', 0) > 0:
                success_rate = (stats_data.get('successful_installs', 0) / stats_data.get('total_attempts', 1)) * 100
                print(f"Success Rate: {success_rate:.1f}%")
            
            # Error categories
            error_categories = stats_data.get('error_categories', {})
            if error_categories:
                print("\n=== Error Categories ===")
                for category, count in sorted(error_categories.items(), key=lambda x: x[1], reverse=True):
                    print(f"  {category}: {count}")
            
            # Recent attempts
            recent = stats_data.get('recent_attempts', [])[:10]
            if recent:
                print("\n=== Recent Installation Attempts ===")
                for attempt in recent:
                    status = "✓" if attempt.get('success') else "✗"
                    duration = f"{attempt.get('duration', 0):.1f}s" if attempt.get('duration') else "N/A"
                    print(f"  {status} {attempt.get('server', 'Unknown')} ({duration})")
    
    asyncio.run(_show_stats())


@main.command()
@click.argument("session_id")
@click.option("--format", "output_format", default="detailed", type=click.Choice(["detailed", "json"]), help="Output format")
def session(session_id: str, output_format: str):
    """Show detailed information about a specific installation session."""
    async def _show_session():
        installer = MCPInstaller()
        session_data = await installer.get_session_details(session_id)
        
        if not session_data:
            print(f"Session {session_id} not found.")
            return
        
        if output_format == "json":
            print(json.dumps(session_data, indent=2, default=str))
        else:
            # Detailed format
            print(f"\n=== Installation Session {session_id} ===")
            print(f"Server: {session_data.get('server_name')}-{session_data.get('option_name')}")
            print(f"Command: {session_data.get('install_command')}")
            print(f"Started: {session_data.get('started_at')}")
            print(f"Duration: {session_data.get('duration_seconds', 0):.1f}s")
            print(f"Success: {'Yes' if session_data.get('success') else 'No'}")
            print(f"Final Message: {session_data.get('final_message')}")
            
            attempts = session_data.get('attempts', [])
            if attempts:
                print(f"\n=== Installation Attempts ({len(attempts)}) ===")
                for i, attempt in enumerate(attempts, 1):
                    status = "✓" if attempt.get('success') else "✗"
                    attempt_type = attempt.get('attempt_type', 'unknown')
                    duration = f"{attempt.get('duration_seconds', 0):.1f}s"
                    print(f"  {i}. {status} {attempt_type} ({duration})")
                    print(f"     Command: {attempt.get('command')}")
                    
                    if not attempt.get('success') and attempt.get('error'):
                        error = attempt['error']
                        print(f"     Error: {error.get('category')} - {error.get('message')[:100]}...")
                    print()
    
    asyncio.run(_show_session())


@main.command()
@click.option("--output", "-o", help="Output file path")
def export_logs(output: Optional[str]):
    """Export installation logs for analysis or bug reporting."""
    async def _export_logs():
        installer = MCPInstaller()
        try:
            output_path = await installer.export_installation_logs(output)
            print(f"Installation logs exported to: {output_path}")
        except Exception as e:
            print(f"Failed to export logs: {e}")
            sys.exit(1)
    
    asyncio.run(_export_logs())


@main.command()
@click.option("--days", default=30, help="Days of logs to keep")
def cleanup_logs(days: int):
    """Clean up old installation logs."""
    async def _cleanup_logs():
        installer = MCPInstaller()
        cleaned_count = await installer.cleanup_old_logs(days)
        print(f"Cleaned up {cleaned_count} old log files (older than {days} days)")
    
    asyncio.run(_cleanup_logs())


@main.command()
def errors():
    """Show common installation errors and solutions."""
    async def _show_errors():
        installer = MCPInstaller()
        stats = await installer.get_installation_stats()
        
        error_categories = stats.get('error_categories', {})
        if not error_categories:
            print("No installation errors recorded.")
            return
        
        print("\n=== Common Installation Errors & Solutions ===")
        
        error_solutions = {
            "permission_error": "Try running with sudo or check file permissions",
            "network_error": "Check internet connection and try again",
            "dependency_missing": "Install required dependencies (Node.js/npm or uv/uvx)",
            "package_not_found": "Package may not exist or URL is incorrect",
            "environment_issue": "Check environment setup and remove lock files",
            "system_error": "Check system resources and permissions",
            "command_error": "Verify command syntax and parameters",
            "unknown": "Check full error output for specific details"
        }
        
        for category, count in sorted(error_categories.items(), key=lambda x: x[1], reverse=True):
            solution = error_solutions.get(category, "No specific solution available")
            print(f"\n{category.replace('_', ' ').title()} ({count} occurrences):")
            print(f"  Solution: {solution}")
    
    asyncio.run(_show_errors())


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