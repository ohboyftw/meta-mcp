"""
FastMCP tools for Meta MCP server management.
"""

import asyncio
import concurrent.futures
from typing import Dict, List, Optional

from .discovery import MCPDiscovery
from .installer import MCPInstaller
from .config import MCPConfig
from .models import (
    MCPInstallationRequest,
    MCPSearchQuery,
    MCPServerCategory,
)
from .tools_base import Tool


def run_async_safely(coro):
    """
    Run an async coroutine safely, handling existing event loop conflicts.

    Args:
        coro: The coroutine to run

    Returns:
        The result of the coroutine
    """
    try:
        # Try to get the current event loop
        asyncio.get_running_loop()
        # If we're already in an event loop, we need to run in a thread pool
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No event loop running, we can run directly
        return asyncio.run(coro)


class SearchMcpServersTool(Tool):
    """Search for MCP servers by category, functionality, or keywords."""

    def __init__(self):
        super().__init__()
        self.discovery = MCPDiscovery()

    def apply(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        sort_by: str = "relevance",
        limit: int = 20,
    ) -> str:
        """
        Search for MCP servers by category, functionality, or keywords.

        Args:
            query: Search query text (optional)
            category: Filter by category (optional)
            keywords: Filter by keywords (optional)
            sort_by: Sort order (relevance, stars, updated, name)
            limit: Maximum results to return

        Returns:
            A formatted list of matching MCP servers with their details.
        """
        # Convert category string to enum if provided
        category_enum = None
        if category:
            try:
                category_enum = MCPServerCategory(category)
            except ValueError:
                return f"Error: Invalid category '{category}'. Valid categories: {[c.value for c in MCPServerCategory]}"

        # Create search query
        search_query = MCPSearchQuery(
            query=query,
            category=category_enum,
            keywords=keywords,
            sort_by=sort_by,
            limit=limit,
        )

        # Run search asynchronously
        result = run_async_safely(self.discovery.search_servers(search_query))

        # Format results
        if not result.servers:
            content = "No MCP servers found matching your criteria.\n"
            content += f"Search took {result.search_time_ms}ms"
        else:
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
    """Get detailed information about a specific MCP server."""

    def __init__(self):
        super().__init__()
        self.discovery = MCPDiscovery()

    def apply(self, server_name: str) -> str:
        """
        Get detailed information about a specific MCP server.

        Args:
            server_name: Name of the MCP server to get info for

        Returns:
            Detailed information about the specified server.
        """
        # Run discovery asynchronously
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
        if server_info.updated_at:
            content += (
                f"**Last Updated:** {server_info.updated_at.strftime('%Y-%m-%d')}\n"
            )

        content += f"\n**Installation Options ({len(server_info.options)}):**\n\n"
        for option in server_info.options:
            content += f"- **{option.display_name}** (`{option.name}`)"
            if option.recommended:
                content += " ⭐ *Recommended*"
            content += f"\n  - Install: `{option.install_command}`\n"
            if option.env_vars:
                content += f"  - Required env vars: {', '.join(option.env_vars)}\n"
            content += "\n"

        if server_info.keywords:
            content += f"**Keywords:** {', '.join(server_info.keywords)}\n"

        return content


class InstallMcpServerTool(Tool):
    """Install an MCP server with specified options."""

    def __init__(self):
        super().__init__()
        self.installer = MCPInstaller()
        self.discovery = MCPDiscovery()

    def apply(
        self,
        server_name: str,
        option_name: str,
        env_vars: Optional[Dict[str, str]] = None,
        auto_configure: bool = True,
    ) -> str:
        """
        Install an MCP server with specified options.

        Args:
            server_name: Name of the server to install
            option_name: Installation option to use (e.g., 'official', 'enhanced')
            env_vars: Environment variables to set (optional)
            auto_configure: Automatically update Claude configuration

        Returns:
            Installation result message.
        """
        # Create installation request
        request = MCPInstallationRequest(
            server_name=server_name,
            option_name=option_name,
            env_vars=env_vars,
            auto_configure=auto_configure,
        )

        # Get server info for environment variable requirements
        server_info = run_async_safely(
            self.discovery.get_server_info(request.server_name)
        )
        if server_info:
            # Find the requested option to get env vars
            for option in server_info.options:
                if option.name == request.option_name:
                    # Add environment variable info if not provided
                    if not request.env_vars and option.env_vars:
                        request.env_vars = {
                            var: f"<YOUR_{var}>" for var in option.env_vars
                        }
                    break

        result = run_async_safely(self.installer.install_server(request))

        if result.success:
            content = f"✅ Successfully installed {result.server_name} ({request.option_name})\n\n"
            content += f"**Configuration name:** `{result.config_name}`\n"
            content += f"**Installed at:** {result.installed_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            content += result.message

            if request.auto_configure:
                content += "\n\n🔧 Claude Desktop configuration has been updated automatically."
                content += "\n📋 **Next steps:**"
                content += "\n1. Set any required environment variables"
                content += "\n2. Restart Claude Desktop to load the new server"

                # Show required environment variables
                if request.env_vars:
                    content += "\n\n**Required environment variables:**"
                    for var in request.env_vars:
                        content += f"\n- `{var}`: Set your API key/token"
        else:
            content = f"❌ Failed to install {result.server_name}\n\n"
            content += f"**Error:** {result.message}"

        return content


class ListInstalledServersTool(Tool):
    """Show currently installed MCP servers and their status."""

    def __init__(self):
        super().__init__()
        self.installer = MCPInstaller()

    def apply(self, include_health: bool = True) -> str:
        """
        Show currently installed MCP servers and their status.

        Args:
            include_health: Include health status information

        Returns:
            List of installed servers with their status.
        """
        # Run installer asynchronously
        installed_servers = run_async_safely(self.installer.list_installed_servers())

        if not installed_servers:
            content = "No MCP servers are currently installed.\n\n"
            content += "Use 'search_mcp_servers' to find servers to install."
        else:
            content = f"**Installed MCP Servers ({len(installed_servers)}):**\n\n"

            for server in installed_servers:
                content += f"**{server.display_name}** (`{server.name}`)\n"
                content += f"- Status: {server.status.value}\n"
                content += f"- Category: {server.category.value}\n"

                if include_health and hasattr(server, "health"):
                    if server.health.response_time_ms:
                        content += (
                            f"- Response time: {server.health.response_time_ms}ms\n"
                        )
                    if server.health.error_message:
                        content += f"- Error: {server.health.error_message}\n"

                content += "\n"

        return content


class UninstallMcpServerTool(Tool):
    """Uninstall an MCP server and remove from configuration."""

    def __init__(self):
        super().__init__()
        self.installer = MCPInstaller()

    def apply(self, server_name: str, remove_config: bool = True) -> str:
        """
        Uninstall an MCP server and remove from configuration.

        Args:
            server_name: Name of the server to uninstall
            remove_config: Remove from Claude configuration

        Returns:
            Uninstallation result message.
        """
        # Run uninstaller asynchronously
        result = run_async_safely(
            self.installer.uninstall_server(server_name, remove_config)
        )

        if result:
            content = f"✅ Successfully uninstalled {server_name}\n\n"
            if remove_config:
                content += "Configuration has been removed from Claude Desktop.\n"
            content += "Restart Claude Desktop to complete the removal."
        else:
            content = f"❌ Failed to uninstall {server_name}\n\n"
            content += (
                "The server may not be installed or there was an error during removal."
            )

        return content


class ValidateConfigTool(Tool):
    """Validate current MCP configuration for errors."""

    def __init__(self):
        super().__init__()
        self.config = MCPConfig()

    def apply(self, fix_errors: bool = False) -> str:
        """
        Validate current MCP configuration for errors.

        Args:
            fix_errors: Attempt to fix configuration errors

        Returns:
            Validation result with any errors found.
        """
        # Run validation asynchronously
        validation_result = run_async_safely(
            self.config.validate_configuration(fix_errors)
        )

        if validation_result.is_valid:
            content = "✅ MCP configuration is valid!\n\n"
            content += f"Found {len(validation_result.servers)} configured servers."
        else:
            content = (
                f"❌ Found {len(validation_result.errors)} configuration errors:\n\n"
            )
            for error in validation_result.errors:
                content += f"- {error}\n"

            if fix_errors and validation_result.fixes_applied:
                content += (
                    f"\n🔧 Applied {validation_result.fixes_applied} automatic fixes."
                )

        return content


class GetManagerStatsTool(Tool):
    """Get statistics about the MCP Manager and installed servers."""

    def __init__(self):
        super().__init__()
        self.discovery = MCPDiscovery()
        self.installer = MCPInstaller()

    def apply(self) -> str:
        """
        Get statistics about the MCP Manager and installed servers.

        Returns:
            Manager statistics including server counts and categories.
        """
        # Run statistics gathering asynchronously
        available_servers = run_async_safely(self.discovery.discover_new_servers())
        installed_servers = run_async_safely(self.installer.list_installed_servers())

        # Count by category
        category_counts = {}
        for server in available_servers:
            category = server.category.value
            category_counts[category] = category_counts.get(category, 0) + 1

        content = "# MCP Manager Statistics\n\n"
        content += f"**Total available servers:** {len(available_servers)}\n"
        content += f"**Total installed servers:** {len(installed_servers)}\n\n"

        content += "**Servers by category:**\n"
        for category, count in sorted(category_counts.items()):
            content += f"- {category}: {count}\n"

        if installed_servers:
            content += "\n**Installed servers:**\n"
            for server in installed_servers[:5]:  # Show first 5
                content += f"- {server.name} ({server.status.value})\n"

            if len(installed_servers) > 5:
                content += f"- ... and {len(installed_servers) - 5} more\n"

        return content


class RefreshServerCacheTool(Tool):
    """Refresh the cache of available MCP servers."""

    def __init__(self):
        super().__init__()
        self.discovery = MCPDiscovery()

    def apply(self, force: bool = False) -> str:
        """
        Refresh the cache of available MCP servers.

        Args:
            force: Force refresh even if cache is fresh

        Returns:
            Cache refresh result with before/after counts.
        """
        # Run cache refresh asynchronously
        before_count = len(self.discovery.server_cache)
        servers = run_async_safely(
            self.discovery.discover_new_servers(force_refresh=force)
        )
        after_count = len(servers)

        content = "✅ Server cache refreshed!\n\n"
        content += f"**Before:** {before_count} servers\n"
        content += f"**After:** {after_count} servers\n"
        content += f"**Net change:** {after_count - before_count:+d} servers"

        return content


class GetInstallationStatsTool(Tool):
    """Get comprehensive installation statistics and error analysis."""

    def __init__(self):
        super().__init__()
        self.installer = MCPInstaller()

    def apply(self, format_type: str = "summary") -> str:
        """
        Get comprehensive installation statistics and error analysis.

        Args:
            format_type: Format type - "summary", "detailed", or "errors_only"

        Returns:
            Installation statistics and analysis.
        """
        # Run stats gathering asynchronously
        stats = run_async_safely(self.installer.get_installation_stats())

        if stats.get("error"):
            return f"❌ Failed to get installation stats: {stats['error']}"

        content = "# Installation Statistics\n\n"

        # Basic stats
        total_attempts = stats.get("total_attempts", 0)
        successful_installs = stats.get("successful_installs", 0)
        failed_installs = stats.get("failed_installs", 0)

        content += f"**Total Attempts:** {total_attempts}\n"
        content += f"**Successful Installs:** {successful_installs}\n"
        content += f"**Failed Installs:** {failed_installs}\n"

        if total_attempts > 0:
            success_rate = (successful_installs / total_attempts) * 100
            content += f"**Success Rate:** {success_rate:.1f}%\n"

        # Error categories
        error_categories = stats.get("error_categories", {})
        if error_categories and format_type in ["summary", "detailed", "errors_only"]:
            content += "\n## Error Categories\n\n"
            for category, count in sorted(
                error_categories.items(), key=lambda x: x[1], reverse=True
            ):
                content += (
                    f"- **{category.replace('_', ' ').title()}:** {count} occurrences\n"
                )

        # Recent attempts (only for detailed format)
        if format_type == "detailed":
            recent = stats.get("recent_attempts", [])[:10]
            if recent:
                content += "\n## Recent Installation Attempts\n\n"
                for attempt in recent:
                    status = "✅" if attempt.get("success") else "❌"
                    duration = (
                        f"{attempt.get('duration', 0):.1f}s"
                        if attempt.get("duration")
                        else "N/A"
                    )
                    timestamp = attempt.get("timestamp", "Unknown")
                    content += f"{status} **{attempt.get('server', 'Unknown')}** ({duration}) - {timestamp}\n"

        return content


class GetSessionDetailsTool(Tool):
    """Get detailed information about a specific installation session."""

    def __init__(self):
        super().__init__()
        self.installer = MCPInstaller()

    def apply(self, session_id: str) -> str:
        """
        Get detailed information about a specific installation session.

        Args:
            session_id: Unique identifier for the installation session

        Returns:
            Detailed session information including all attempts and errors.
        """
        # Run session details gathering asynchronously
        session_data = run_async_safely(self.installer.get_session_details(session_id))

        if not session_data:
            return f"❌ Session '{session_id}' not found. Use GetInstallationStatsTool to see recent sessions."

        content = f"# Installation Session: {session_id}\n\n"

        # Basic session info
        content += f"**Server:** {session_data.get('server_name')}-{session_data.get('option_name')}\n"
        content += f"**Command:** `{session_data.get('install_command')}`\n"
        content += f"**Started:** {session_data.get('started_at')}\n"
        content += f"**Duration:** {session_data.get('duration_seconds', 0):.1f}s\n"
        content += (
            f"**Success:** {'✅ Yes' if session_data.get('success') else '❌ No'}\n"
        )
        content += f"**Final Message:** {session_data.get('final_message')}\n"

        # System info
        system_info = session_data.get("system_info", {})
        if system_info:
            content += "\n## System Information\n\n"
            content += f"**Platform:** {system_info.get('platform', 'Unknown')}\n"
            content += (
                f"**Python Version:** {system_info.get('python_version', 'Unknown')}\n"
            )
            content += (
                f"**Architecture:** {system_info.get('architecture', 'Unknown')}\n"
            )

        # Installation attempts
        attempts = session_data.get("attempts", [])
        if attempts:
            content += f"\n## Installation Attempts ({len(attempts)})\n\n"
            for i, attempt in enumerate(attempts, 1):
                status = "✅" if attempt.get("success") else "❌"
                attempt_type = attempt.get("attempt_type", "unknown")
                duration = f"{attempt.get('duration_seconds', 0):.1f}s"

                content += (
                    f"### Attempt {i}: {status} {attempt_type.title()} ({duration})\n\n"
                )
                content += f"**Command:** `{attempt.get('command')}`\n"
                content += f"**Return Code:** {attempt.get('return_code')}\n"

                if not attempt.get("success") and attempt.get("error"):
                    error = attempt["error"]
                    content += f"**Error Category:** {error.get('category')}\n"
                    content += f"**Error Message:** {error.get('message')}\n"

                    details = error.get("details", {})
                    if details.get("suggestion"):
                        content += f"**Suggested Fix:** {details['suggestion']}\n"

                # Show stdout/stderr if available (truncated)
                stdout = attempt.get("stdout", "")
                stderr = attempt.get("stderr", "")

                if stdout:
                    content += f"\n**Output:** \n```\n{stdout[:500]}{'...' if len(stdout) > 500 else ''}\n```\n"
                if stderr:
                    content += f"\n**Error Output:** \n```\n{stderr[:500]}{'...' if len(stderr) > 500 else ''}\n```\n"

                content += "\n"

        return content


class ExportInstallationLogsTool(Tool):
    """Export installation logs for analysis or bug reporting."""

    def __init__(self):
        super().__init__()
        self.installer = MCPInstaller()

    def apply(self, output_path: Optional[str] = None) -> str:
        """
        Export installation logs for analysis or bug reporting.

        Args:
            output_path: Optional path for the export file

        Returns:
            Export result with file path.
        """
        try:
            # Run export asynchronously
            export_path = run_async_safely(
                self.installer.export_installation_logs(output_path)
            )

            content = "✅ Installation logs exported successfully!\n\n"
            content += f"**Export File:** `{export_path}`\n\n"
            content += "The export includes:\n"
            content += "- Installation statistics\n"
            content += "- Recent session details\n"
            content += "- System information\n"
            content += "- Error analysis\n\n"
            content += "You can use this file for bug reports or detailed analysis."

            return content

        except Exception as e:
            return f"❌ Failed to export installation logs: {str(e)}"


class CleanupInstallationLogsTool(Tool):
    """Clean up old installation logs to free up space."""

    def __init__(self):
        super().__init__()
        self.installer = MCPInstaller()

    def apply(self, days_to_keep: int = 30) -> str:
        """
        Clean up old installation logs to free up space.

        Args:
            days_to_keep: Number of days of logs to keep (default: 30)

        Returns:
            Cleanup result with number of files removed.
        """
        # Run cleanup asynchronously
        cleaned_count = run_async_safely(self.installer.cleanup_old_logs(days_to_keep))

        content = "✅ Cleanup completed!\n\n"
        content += f"**Files removed:** {cleaned_count}\n"
        content += f"**Retention period:** {days_to_keep} days\n\n"

        if cleaned_count > 0:
            content += "Old installation logs have been removed to free up space."
        else:
            content += "No old logs found to clean up."

        return content


class AnalyzeInstallationErrorsTool(Tool):
    """Analyze installation errors and provide solutions."""

    def __init__(self):
        super().__init__()
        self.installer = MCPInstaller()

    def apply(self, error_category: Optional[str] = None) -> str:
        """
        Analyze installation errors and provide solutions.

        Args:
            error_category: Focus on specific error category (optional)

        Returns:
            Error analysis with solutions and recommendations.
        """
        # Run stats gathering asynchronously
        stats = run_async_safely(self.installer.get_installation_stats())

        error_categories = stats.get("error_categories", {})
        if not error_categories:
            return "✅ No installation errors recorded yet."

        content = "# Installation Error Analysis\n\n"

        # Error solutions mapping
        error_solutions = {
            "permission_error": {
                "description": "Insufficient permissions to execute installation commands",
                "solutions": [
                    "Try running with sudo (use carefully)",
                    "Check file permissions in target directory",
                    "Ensure your user has write access to installation paths",
                    "For npm: Use 'npm config set prefix ~/.npm-global' to avoid permission issues",
                ],
            },
            "network_error": {
                "description": "Network connectivity issues during installation",
                "solutions": [
                    "Check your internet connection",
                    "Try again in a few minutes",
                    "Check if corporate firewall is blocking requests",
                    "Use a VPN if in a restricted network",
                    "Verify DNS resolution is working",
                ],
            },
            "dependency_missing": {
                "description": "Required dependencies are not installed",
                "solutions": [
                    "Install Node.js and npm from https://nodejs.org/",
                    "Install uv/uvx: curl -LsSf https://astral.sh/uv/install.sh | sh",
                    "Restart your terminal after installation",
                    "Verify installation with: node --version && npm --version",
                ],
            },
            "package_not_found": {
                "description": "The requested package or repository does not exist",
                "solutions": [
                    "Verify the package name is correct",
                    "Check if the repository URL is valid",
                    "Try alternative installation options",
                    "Search for similar packages with search_mcp_servers",
                ],
            },
            "environment_issue": {
                "description": "Environment configuration problems",
                "solutions": [
                    "Remove package-lock.json or yarn.lock files",
                    "Clear npm cache: npm cache clean --force",
                    "Check environment variables are set correctly",
                    "Ensure no conflicting global packages",
                ],
            },
            "system_error": {
                "description": "System-level errors (disk space, memory, etc.)",
                "solutions": [
                    "Check available disk space",
                    "Free up memory if needed",
                    "Check system permissions",
                    "Restart if system resources are locked",
                ],
            },
            "command_error": {
                "description": "Command syntax or parameter errors",
                "solutions": [
                    "Verify command syntax is correct",
                    "Check all required parameters are provided",
                    "Try alternative installation methods",
                    "Check for typos in server names",
                ],
            },
            "unknown": {
                "description": "Unclassified errors that need manual investigation",
                "solutions": [
                    "Check the full error output for specific details",
                    "Try alternative installation options",
                    "Export logs and report the issue",
                    "Use GetSessionDetailsTool for more information",
                ],
            },
        }

        # Filter by category if specified
        categories_to_show = (
            [error_category]
            if error_category and error_category in error_categories
            else error_categories.keys()
        )

        for category in sorted(
            categories_to_show, key=lambda x: error_categories.get(x, 0), reverse=True
        ):
            count = error_categories.get(category, 0)
            if count == 0:
                continue

            solution_info = error_solutions.get(category, {})

            content += (
                f"## {category.replace('_', ' ').title()} ({count} occurrences)\n\n"
            )

            if solution_info.get("description"):
                content += f"**Description:** {solution_info['description']}\n\n"

            if solution_info.get("solutions"):
                content += "**Solutions:**\n"
                for i, solution in enumerate(solution_info["solutions"], 1):
                    content += f"{i}. {solution}\n"
                content += "\n"
            else:
                content += (
                    "**Solution:** Check specific error details for guidance.\n\n"
                )

        # General recommendations
        content += "## General Recommendations\n\n"
        content += (
            "1. **Check Prerequisites:** Ensure Node.js/npm and uv/uvx are installed\n"
        )
        content += "2. **Network Issues:** Verify internet connectivity and firewall settings\n"
        content += (
            "3. **Permission Problems:** Consider using user-level package managers\n"
        )
        content += "4. **Export Logs:** Use ExportInstallationLogsTool for detailed debugging\n"
        content += (
            "5. **Try Alternatives:** Most servers have multiple installation options\n"
        )

        return content

class AIAssistedInstallTool(Tool):
    """AI-assisted installation fallback for servers not in the registry."""

    def __init__(self):
        super().__init__()
        from .ai_fallback import AIFallbackManager
        self.ai_fallback_manager = AIFallbackManager()

    def apply(
        self, 
        server_name: str,
        reason: str = "Server not found in registry",
        clients: Optional[List[str]] = None
    ) -> str:
        """
        Request AI-assisted installation for servers not in the Meta MCP registry.
        
        Args:
            server_name: Name of the server to install
            reason: Reason why standard installation cannot be used
            clients: Target MCP clients for integration
            
        Returns:
            Result of AI-assisted installation attempt.
        """
        async def _ai_install():
            return await self.ai_fallback_manager.request_ai_installation(
                server_name=server_name,
                failure_reason=reason,
                target_clients=clients or ["local_mcp_json"]
            )
        
        # Run AI installation
        result = run_async_safely(_ai_install())
        
        if result.success:
            content = f"✅ AI-assisted installation successful!\n\n"
            content += f"**Server:** {result.server_name}\n"
            content += f"**Method:** {result.method}\n"
            content += f"**Command executed:** `{result.command_executed}`\n"
            
            if result.integration_created:
                content += f"**Integration:** ✅ Configuration created\n"
            else:
                content += f"**Integration:** ❌ Manual configuration required\n"
            
            content += f"\n{result.message}\n"
            
            if result.warnings:
                content += f"\n⚠️ **Warnings:**\n"
                for warning in result.warnings:
                    content += f"- {warning}\n"
                    
        else:
            content = f"❌ AI-assisted installation failed\n\n"
            content += f"**Server:** {result.server_name}\n"
            content += f"**Error:** {result.message}\n\n"
            content += "**Suggestions:**\n"
            content += "- Check the server name spelling\n"
            content += "- Verify the server exists and is installable\n"
            content += "- Try installing manually with specific commands\n"
            content += "- Check if prerequisites (Node.js, Python) are installed\n"
            
        return content
