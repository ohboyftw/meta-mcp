"""
MCP Configuration Management.

This module handles reading, writing, and validating Claude Desktop MCP configurations.
"""

import json
import logging
import os
import platform
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, ValidationError

from .models import MCPConfiguration, MCPConfigEntry

logger = logging.getLogger(__name__)


class ConfigValidationResult(BaseModel):
    """Result of configuration validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    servers: List[str]
    fixes_applied: int = 0


class MCPConfig:
    """Manages MCP configuration for Claude Desktop."""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._get_default_config_path()
        self.config_dir = Path(self.config_path).parent
        
        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _get_default_config_path(self) -> str:
        """Get the default MCP configuration path for Claude Code CLI."""
        # Look for .mcp.json in current working directory first
        cwd_config = Path.cwd() / ".mcp.json"
        if cwd_config.exists():
            return str(cwd_config)
        
        # Look for .mcp.json in parent directories (project root detection)
        current_path = Path.cwd()
        for parent in [current_path] + list(current_path.parents):
            mcp_config = parent / ".mcp.json"
            if mcp_config.exists():
                return str(mcp_config)
        
        # If no existing .mcp.json found, create in current working directory
        return str(cwd_config)

    async def load_configuration(self) -> MCPConfiguration:
        """Load the current MCP configuration."""
        try:
            if not Path(self.config_path).exists():
                # Return empty configuration if file doesn't exist
                return MCPConfiguration()
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Convert to our model
            return MCPConfiguration(**data)
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            raise ValueError(f"Configuration file contains invalid JSON: {e}")
        except ValidationError as e:
            logger.error(f"Invalid configuration structure: {e}")
            raise ValueError(f"Configuration file has invalid structure: {e}")
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise

    async def save_configuration(self, config: MCPConfiguration) -> None:
        """Save the MCP configuration."""
        try:
            # Convert to dict and save
            config_dict = config.model_dump(exclude_none=True)
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Configuration saved to {self.config_path}")
            
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            raise

    async def add_server(self, name: str, command: str, args: List[str], cwd: Optional[str] = None, env_vars: Optional[Dict[str, str]] = None) -> None:
        """Add a new MCP server to the configuration."""
        try:
            config = await self.load_configuration()
            
            # Create server entry
            server_entry = MCPConfigEntry(
                command=command,
                args=args,
                cwd=cwd,
                env=env_vars
            )
            
            # Add to configuration
            config.mcpServers[name] = server_entry
            
            # Save updated configuration
            await self.save_configuration(config)
            
            logger.info(f"Added server '{name}' to configuration")
            
        except Exception as e:
            logger.error(f"Failed to add server '{name}': {e}")
            raise

    async def remove_server(self, name: str) -> bool:
        """Remove an MCP server from the configuration."""
        try:
            config = await self.load_configuration()
            
            if name not in config.mcpServers:
                logger.warning(f"Server '{name}' not found in configuration")
                return False
            
            # Remove server
            del config.mcpServers[name]
            
            # Save updated configuration
            await self.save_configuration(config)
            
            logger.info(f"Removed server '{name}' from configuration")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove server '{name}': {e}")
            raise

    async def update_server(self, name: str, command: Optional[str] = None, args: Optional[List[str]] = None, cwd: Optional[str] = None, env_vars: Optional[Dict[str, str]] = None) -> bool:
        """Update an existing MCP server configuration."""
        try:
            config = await self.load_configuration()
            
            if name not in config.mcpServers:
                logger.warning(f"Server '{name}' not found in configuration")
                return False
            
            # Update server entry
            server = config.mcpServers[name]
            if command is not None:
                server.command = command
            if args is not None:
                server.args = args
            if cwd is not None:
                server.cwd = cwd
            if env_vars is not None:
                server.env = env_vars
            
            # Save updated configuration
            await self.save_configuration(config)
            
            logger.info(f"Updated server '{name}' configuration")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update server '{name}': {e}")
            raise

    async def list_servers(self) -> Dict[str, MCPConfigEntry]:
        """List all configured MCP servers."""
        try:
            config = await self.load_configuration()
            return config.mcpServers
        except Exception as e:
            logger.error(f"Failed to list servers: {e}")
            return {}

    async def validate_configuration(self, fix_errors: bool = False) -> ConfigValidationResult:
        """Validate the current MCP configuration."""
        errors = []
        warnings = []
        servers = []
        fixes_applied = 0
        
        try:
            # Check if config file exists
            if not Path(self.config_path).exists():
                warnings.append("Configuration file does not exist")
                if fix_errors:
                    # Create empty configuration
                    await self.save_configuration(MCPConfiguration())
                    fixes_applied += 1
                return ConfigValidationResult(
                    is_valid=True,
                    errors=errors,
                    warnings=warnings,
                    servers=servers,
                    fixes_applied=fixes_applied
                )
            
            # Try to load configuration
            try:
                config = await self.load_configuration()
            except ValueError as e:
                errors.append(str(e))
                return ConfigValidationResult(
                    is_valid=False,
                    errors=errors,
                    warnings=warnings,
                    servers=servers,
                    fixes_applied=fixes_applied
                )
            
            # Validate each server
            for server_name, server_config in config.mcpServers.items():
                servers.append(server_name)
                
                # Check command exists
                if not server_config.command:
                    errors.append(f"Server '{server_name}' has no command specified")
                elif not self._command_exists(server_config.command):
                    warnings.append(f"Command '{server_config.command}' for server '{server_name}' may not be available")
                
                # Check environment variables
                if server_config.env:
                    for env_var, value in server_config.env.items():
                        if value.startswith("<") and value.endswith(">"):
                            warnings.append(f"Server '{server_name}' has placeholder environment variable: {env_var}")
                        elif not value.strip():
                            warnings.append(f"Server '{server_name}' has empty environment variable: {env_var}")
            
            # Overall validation
            is_valid = len(errors) == 0
            
            return ConfigValidationResult(
                is_valid=is_valid,
                errors=errors,
                warnings=warnings,
                servers=servers,
                fixes_applied=fixes_applied
            )
            
        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            errors.append(f"Validation error: {str(e)}")
            return ConfigValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                servers=servers,
                fixes_applied=fixes_applied
            )

    def _command_exists(self, command: str) -> bool:
        """Check if a command exists in the system PATH."""
        import shutil
        return shutil.which(command) is not None

    async def backup_configuration(self) -> str:
        """Create a backup of the current configuration."""
        try:
            if not Path(self.config_path).exists():
                raise FileNotFoundError("No configuration file to backup")
            
            # Create backup filename with timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{self.config_path}.backup_{timestamp}"
            
            # Copy configuration file
            import shutil
            shutil.copy2(self.config_path, backup_path)
            
            logger.info(f"Configuration backed up to {backup_path}")
            return backup_path
            
        except Exception as e:
            logger.error(f"Failed to backup configuration: {e}")
            raise

    async def restore_configuration(self, backup_path: str) -> None:
        """Restore configuration from a backup."""
        try:
            if not Path(backup_path).exists():
                raise FileNotFoundError(f"Backup file not found: {backup_path}")
            
            # Validate backup before restoring
            with open(backup_path, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
            
            # Validate structure
            MCPConfiguration(**backup_data)
            
            # Copy backup to configuration file
            import shutil
            shutil.copy2(backup_path, self.config_path)
            
            logger.info(f"Configuration restored from {backup_path}")
            
        except json.JSONDecodeError as e:
            raise ValueError(f"Backup file contains invalid JSON: {e}")
        except ValidationError as e:
            raise ValueError(f"Backup file has invalid configuration structure: {e}")
        except Exception as e:
            logger.error(f"Failed to restore configuration: {e}")
            raise

    async def get_configuration_info(self) -> Dict[str, Any]:
        """Get information about the current configuration."""
        try:
            config_path = Path(self.config_path)
            
            info = {
                "config_path": str(config_path),
                "config_exists": config_path.exists(),
                "config_dir_exists": config_path.parent.exists(),
            }
            
            if config_path.exists():
                stat = config_path.stat()
                info.update({
                    "config_size": stat.st_size,
                    "config_modified": stat.st_mtime,
                    "config_readable": os.access(config_path, os.R_OK),
                    "config_writable": os.access(config_path, os.W_OK),
                })
                
                # Try to load and count servers
                try:
                    config = await self.load_configuration()
                    info["server_count"] = len(config.mcpServers)
                    info["servers"] = list(config.mcpServers.keys())
                except Exception as e:
                    info["load_error"] = str(e)
            
            return info
            
        except Exception as e:
            logger.error(f"Failed to get configuration info: {e}")
            return {"error": str(e)}

    async def export_server_config(self, server_name: str) -> Optional[Dict[str, Any]]:
        """Export configuration for a specific server."""
        try:
            config = await self.load_configuration()
            
            if server_name not in config.mcpServers:
                return None
            
            server_config = config.mcpServers[server_name]
            return {
                "name": server_name,
                "command": server_config.command,
                "args": server_config.args,
                "env": server_config.env,
                "exported_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to export server config for '{server_name}': {e}")
            return None

    async def import_server_config(self, server_config: Dict[str, Any]) -> bool:
        """Import configuration for a server."""
        try:
            name = server_config["name"]
            command = server_config["command"]
            args = server_config["args"]
            env_vars = server_config.get("env")
            
            await self.add_server(name, command, args, env_vars)
            return True
            
        except Exception as e:
            logger.error(f"Failed to import server config: {e}")
            return False