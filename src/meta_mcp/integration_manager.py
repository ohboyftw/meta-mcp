"""
MCP Integration Manager for handling client configuration integration.

This module handles the integration of MCP servers with various MCP clients
like Claude Desktop, Gemini, and local .mcp.json configurations.
"""

import json
import platform
from pathlib import Path
from typing import Dict, List, Optional, Any
import asyncio
import logging

from .models import (
    IntegrationResult, 
    MCPClientIntegration, 
    MCPServerOptionEnhanced
)

logger = logging.getLogger(__name__)


class MCPIntegrationManager:
    """Manages integration of MCP servers with various MCP clients."""
    
    def __init__(self):
        self.platform = platform.system().lower()
        
        # Platform-specific config paths
        self.config_paths = {
            "claude_desktop": self._get_claude_desktop_path(),
            "gemini": self._get_gemini_config_path(),
            "local_mcp_json": Path.cwd() / ".mcp.json"
        }
        
        logger.info(f"Initialized integration manager for platform: {self.platform}")
    
    def _get_claude_desktop_path(self) -> Path:
        """Get Claude Desktop config path for current platform."""
        if self.platform == "darwin":  # macOS
            return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
        elif self.platform == "windows":
            return Path.home() / "AppData/Roaming/Claude/claude_desktop_config.json"
        else:  # Linux
            return Path.home() / ".config/claude/claude_desktop_config.json"
    
    def _get_gemini_config_path(self) -> Path:
        """Get Gemini config path."""
        return Path.home() / ".config/gemini/mcp_config.json"
    
    async def integrate_server(
        self,
        server_name: str,
        server_config: MCPServerOptionEnhanced,
        client_targets: List[str] = None
    ) -> List[IntegrationResult]:
        """Integrate MCP server with specified clients."""
        
        if client_targets is None:
            # Default to Claude Desktop and local .mcp.json
            client_targets = ["claude_desktop", "local_mcp_json"]
        
        results = []
        integrations = server_config.integrations
        
        logger.info(f"Starting integration of {server_name} with clients: {client_targets}")
        
        for client in client_targets:
            if client not in integrations:
                logger.warning(f"No integration configuration for client: {client}")
                results.append(IntegrationResult(
                    success=False,
                    client_name=client,
                    config_path="",
                    message=f"No integration configuration for {client}",
                    restart_required=False
                ))
                continue
            
            try:
                result = await self._integrate_with_client(
                    server_name,
                    client,
                    integrations[client]
                )
                results.append(result)
                logger.info(f"Integration with {client}: {'✅ Success' if result.success else '❌ Failed'}")
            except Exception as e:
                logger.error(f"Integration with {client} failed: {str(e)}", exc_info=True)
                results.append(IntegrationResult(
                    success=False,
                    client_name=client,
                    config_path="",
                    message=f"Integration failed: {str(e)}",
                    restart_required=False
                ))
        
        return results
    
    async def _integrate_with_client(
        self,
        server_name: str,
        client_name: str,
        integration_config: MCPClientIntegration
    ) -> IntegrationResult:
        """Integrate with specific MCP client."""
        
        config_path = Path(integration_config.config_path.replace("~", str(Path.home())))
        config_template = integration_config.config_template
        restart_required = integration_config.restart_required
        instructions = integration_config.instructions or ""
        
        logger.debug(f"Integrating {server_name} with {client_name} at {config_path}")
        
        # Ensure config directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing config or create new
        existing_config = {}
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    existing_config = json.load(f)
                logger.debug(f"Loaded existing config from {config_path}")
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in {config_path}, starting with empty config: {e}")
                existing_config = {}
            except Exception as e:
                logger.error(f"Error reading config from {config_path}: {e}")
                raise
        else:
            logger.debug(f"Creating new config at {config_path}")
        
        # Merge configurations
        merged_config = self._merge_configs(existing_config, config_template)
        
        # Write updated config
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(merged_config, f, indent=2, ensure_ascii=False)
            logger.debug(f"Successfully wrote merged config to {config_path}")
        except Exception as e:
            logger.error(f"Error writing config to {config_path}: {e}")
            raise
        
        message = f"Successfully integrated {server_name} with {client_name}"
        if restart_required and instructions:
            message += f". {instructions}"
        elif restart_required:
            message += f". Restart {client_name} to activate the server"
        
        return IntegrationResult(
            success=True,
            client_name=client_name,
            config_path=str(config_path),
            message=message,
            restart_required=restart_required
        )
    
    def _merge_configs(self, existing: Dict, template: Dict) -> Dict:
        """Merge template config into existing config."""
        result = existing.copy()
        
        for key, value in template.items():
            if key not in result:
                result[key] = value
            elif isinstance(value, dict) and isinstance(result[key], dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                # For specific server configurations, update/add the server
                if isinstance(value, dict) and key in ["mcpServers", "servers"]:
                    if not isinstance(result[key], dict):
                        result[key] = {}
                    result[key].update(value)
                else:
                    result[key] = value
        
        return result
    
    async def remove_server_integration(
        self,
        server_name: str,
        client_targets: List[str] = None
    ) -> List[IntegrationResult]:
        """Remove server integration from clients."""
        
        if client_targets is None:
            client_targets = ["claude_desktop", "local_mcp_json", "gemini"]
        
        results = []
        logger.info(f"Removing {server_name} integration from clients: {client_targets}")
        
        for client in client_targets:
            config_path = self.config_paths.get(client)
            if not config_path or not config_path.exists():
                logger.debug(f"No config file found for {client} at {config_path}")
                continue
            
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # Remove server from config
                removed = False
                if client == "claude_desktop" and "mcpServers" in config:
                    if server_name in config["mcpServers"]:
                        del config["mcpServers"][server_name]
                        removed = True
                elif client == "gemini" and "servers" in config:
                    if server_name in config["servers"]:
                        del config["servers"][server_name]
                        removed = True
                elif client == "local_mcp_json" and "mcpServers" in config:
                    if server_name in config["mcpServers"]:
                        del config["mcpServers"][server_name]
                        removed = True
                
                if removed:
                    with open(config_path, 'w', encoding='utf-8') as f:
                        json.dump(config, f, indent=2, ensure_ascii=False)
                    
                    logger.info(f"Successfully removed {server_name} from {client}")
                    results.append(IntegrationResult(
                        success=True,
                        client_name=client,
                        config_path=str(config_path),
                        message=f"Removed {server_name} from {client}",
                        restart_required=client in ["claude_desktop", "gemini"]
                    ))
                else:
                    logger.debug(f"{server_name} was not configured in {client}")
            
            except Exception as e:
                logger.error(f"Failed to remove {server_name} from {client}: {e}", exc_info=True)
                results.append(IntegrationResult(
                    success=False,
                    client_name=client,
                    config_path=str(config_path) if config_path else "",
                    message=f"Failed to remove from {client}: {str(e)}",
                    restart_required=False
                ))
        
        return results
    
    async def list_integrations(self, server_name: str) -> Dict[str, bool]:
        """Check which clients currently have this server integrated."""
        
        integrations = {}
        
        for client, config_path in self.config_paths.items():
            if not config_path.exists():
                integrations[client] = False
                continue
            
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                if client == "claude_desktop":
                    integrations[client] = server_name in config.get("mcpServers", {})
                elif client == "gemini":
                    integrations[client] = server_name in config.get("servers", {})
                elif client == "local_mcp_json":
                    integrations[client] = server_name in config.get("mcpServers", {})
                else:
                    integrations[client] = False
            
            except Exception as e:
                logger.error(f"Error checking integration for {client}: {e}")
                integrations[client] = False
        
        return integrations
    
    def get_client_config_paths(self) -> Dict[str, str]:
        """Get the configuration file paths for all supported clients."""
        return {
            client: str(path) for client, path in self.config_paths.items()
        }
    
    async def validate_client_configs(self) -> Dict[str, Dict[str, Any]]:
        """Validate configuration files for all clients."""
        validation_results = {}
        
        for client, config_path in self.config_paths.items():
            result = {
                "exists": config_path.exists(),
                "readable": False,
                "valid_json": False,
                "has_mcp_servers": False,
                "server_count": 0,
                "errors": []
            }
            
            if result["exists"]:
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    
                    result["readable"] = True
                    result["valid_json"] = True
                    
                    if client == "claude_desktop":
                        servers = config.get("mcpServers", {})
                        result["has_mcp_servers"] = bool(servers)
                        result["server_count"] = len(servers)
                    elif client == "gemini":
                        servers = config.get("servers", {})
                        result["has_mcp_servers"] = bool(servers)
                        result["server_count"] = len(servers)
                    elif client == "local_mcp_json":
                        servers = config.get("mcpServers", {})
                        result["has_mcp_servers"] = bool(servers)
                        result["server_count"] = len(servers)
                
                except json.JSONDecodeError as e:
                    result["errors"].append(f"Invalid JSON: {str(e)}")
                except Exception as e:
                    result["errors"].append(f"Read error: {str(e)}")
            
            validation_results[client] = result
        
        return validation_results