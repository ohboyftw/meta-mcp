# Meta MCP Server

A FastMCP-based server for discovering, installing, and managing other MCP servers. This implementation uses the proven FastMCP pattern that avoids CallToolResult iteration issues.

## Features

- **Server Discovery**: Search and discover available MCP servers
- **Server Management**: Install, uninstall, and update MCP servers
- **Configuration Management**: Validate and manage MCP configurations
- **Health Monitoring**: Check server status and health
- **FastMCP Integration**: Uses FastMCP framework for robust tool handling

## Installation

```bash
pip install -e .
```

## Usage

Start the MCP server:

```bash
meta-mcp-server
```

## Architecture

This server uses the FastMCP pattern similar to Serena, where:
- Tools return simple strings via `apply() -> str` methods
- FastMCP framework handles all CallToolResult wrapping automatically
- No direct CallToolResult object creation to avoid iteration issues

## Available Tools

- `search_mcp_servers` - Search for available MCP servers
- `get_server_info` - Get detailed information about a specific server
- `install_mcp_server` - Install an MCP server
- `list_installed_servers` - List currently installed servers
- `uninstall_mcp_server` - Uninstall an MCP server
- `update_server` - Update a server to latest version
- `validate_config` - Validate MCP configuration
- `get_manager_stats` - Get manager statistics
- `refresh_server_cache` - Refresh server cache