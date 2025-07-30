"""
FastMCP tools for Meta MCP server management.
"""

import asyncio
from typing import Dict, List, Optional

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
        loop = asyncio.get_running_loop()
        # If we're already in an event loop, we need to run in a thread pool
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No event loop running, we can run directly
        return asyncio.run(coro)

from .discovery import MCPDiscovery
from .installer import MCPInstaller
from .config import MCPConfig
from .models import (
    MCPInstallationRequest,
    MCPSearchQuery,
    MCPServerCategory,
)
from .tools_base import Tool


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
        limit: int = 20
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
            limit=limit
        )
        
        # Run search asynchronously
        result = run_async_safely(self.discovery.search_servers(search_query))
        
        # Format results
        if not result.servers:
            content = f"No MCP servers found matching your criteria.\n"
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
            content += f"**Last Updated:** {server_info.updated_at.strftime('%Y-%m-%d')}\n"
        
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
        auto_configure: bool = True
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
            auto_configure=auto_configure
        )
        
        # Get server info for environment variable requirements
        server_info = run_async_safely(self.discovery.get_server_info(request.server_name))
        if server_info:
            # Find the requested option to get env vars
            for option in server_info.options:
                if option.name == request.option_name:
                    # Add environment variable info if not provided
                    if not request.env_vars and option.env_vars:
                        request.env_vars = {var: f"<YOUR_{var}>" for var in option.env_vars}
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
                
                if include_health and hasattr(server, 'health'):
                    if server.health.response_time_ms:
                        content += f"- Response time: {server.health.response_time_ms}ms\n"
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
        result = run_async_safely(self.installer.uninstall_server(server_name, remove_config))
        
        if result:
            content = f"✅ Successfully uninstalled {server_name}\n\n"
            if remove_config:
                content += "Configuration has been removed from Claude Desktop.\n"
            content += "Restart Claude Desktop to complete the removal."
        else:
            content = f"❌ Failed to uninstall {server_name}\n\n"
            content += "The server may not be installed or there was an error during removal."
        
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
        validation_result = run_async_safely(self.config.validate_configuration(fix_errors))
        
        if validation_result.is_valid:
            content = "✅ MCP configuration is valid!\n\n"
            content += f"Found {len(validation_result.servers)} configured servers."
        else:
            content = f"❌ Found {len(validation_result.errors)} configuration errors:\n\n"
            for error in validation_result.errors:
                content += f"- {error}\n"
            
            if fix_errors and validation_result.fixes_applied:
                content += f"\n🔧 Applied {validation_result.fixes_applied} automatic fixes."
        
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
            content += f"\n**Installed servers:**\n"
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
        servers = run_async_safely(self.discovery.discover_new_servers(force_refresh=force))
        after_count = len(servers)
        
        content = f"✅ Server cache refreshed!\n\n"
        content += f"**Before:** {before_count} servers\n"
        content += f"**After:** {after_count} servers\n"
        content += f"**Net change:** {after_count - before_count:+d} servers"
        
        return content