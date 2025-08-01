"""
MCP Server Installation and Management.

This module handles installing, uninstalling, updating, and managing MCP servers.
"""

import asyncio
import json
import logging
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from .config import MCPConfig
from .logging_manager import InstallationLogManager
from .models import (
    MCPInstallationRequest,
    MCPInstallationResult,
    MCPServerHealth,
    MCPServerInfo,
    MCPServerStatus,
    MCPServerWithOptions,
)

logger = logging.getLogger(__name__)


def get_config_directory() -> Path:
    """Get the appropriate config directory for the current platform."""
    system = platform.system().lower()
    
    if system == "windows":
        # Windows: Use APPDATA (roaming) or LOCALAPPDATA
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "meta-mcp"
        # Fallback to LOCALAPPDATA
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            return Path(localappdata) / "meta-mcp"
        # Final fallback
        return Path.home() / "AppData" / "Roaming" / "meta-mcp"
    
    elif system == "darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / "meta-mcp"
    
    else:  # Linux, WSL, other Unix-like systems
        # Follow XDG Base Directory Specification
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config_home:
            return Path(xdg_config_home) / "meta-mcp"
        return Path.home() / ".config" / "meta-mcp"


class MCPInstaller:
    """Handles MCP server installation and management."""
    
    def __init__(self):
        self.config = MCPConfig()
        self.installation_log = Path.home() / ".mcp-manager" / "installations.json"
        self.installation_log.parent.mkdir(exist_ok=True)
        
        # Enhanced logging
        self.log_manager = InstallationLogManager()
        
        # Server definitions (self-contained)
        self.server_definitions = self._get_server_definitions()
        
        # Track installations
        self.installed_servers: Dict[str, dict] = self._load_installation_log()

    def _load_installation_log(self) -> Dict[str, dict]:
        """Load installation log from disk."""
        if self.installation_log.exists():
            try:
                with open(self.installation_log, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load installation log: {e}")
        return {}

    def _save_installation_log(self) -> None:
        """Save installation log to disk."""
        try:
            with open(self.installation_log, 'w') as f:
                json.dump(self.installed_servers, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save installation log: {e}")

    async def install_server(self, request: MCPInstallationRequest) -> MCPInstallationResult:
        """Install an MCP server with the specified option."""
        server_name = request.server_name
        option_name = request.option_name
        config_name = f"{server_name}-{option_name}"
        
        install_command = await self._get_install_command(server_name, option_name)
        if not install_command:
            return MCPInstallationResult(
                success=False,
                server_name=server_name,
                option_name=option_name,
                config_name=config_name,
                message=f"Unknown server or option: {server_name}.{option_name}"
            )

        # Check for prerequisites if it's an npm installation
        if install_command.startswith("npm") or install_command.startswith("npx"):
            prereqs = await self.check_prerequisites()
            if not all([prereqs.get("node"), prereqs.get("npm")]):
                return MCPInstallationResult(
                    success=False,
                    server_name=server_name,
                    option_name=option_name,
                    config_name=config_name,
                    message="Node.js and npm are required for this installation. Please install them from https://nodejs.org/"
                )

        logger.info(f"Installing {server_name} with option {option_name}")
        
        # Start logging session
        session_id = self.log_manager.start_session(server_name, option_name, install_command)
        
        try:
            success, message = await self._execute_installation_with_fallback(install_command, server_name, option_name)
            
            if success:
                self.installed_servers[config_name] = {
                    "server_name": server_name,
                    "option_name": option_name,
                    "install_command": install_command,
                    "installed_at": datetime.now().isoformat(),
                    "env_vars": request.env_vars or {},
                    "status": "installed"
                }
                self._save_installation_log()
                
                if request.auto_configure:
                    # Try to update local .mcp.json first
                    local_config_updated = await self._update_local_mcp_config(config_name, install_command, request.env_vars)
                    
                    # Fall back to Claude Desktop config if local config fails or doesn't exist
                    if not local_config_updated:
                        await self._update_claude_config(config_name, install_command, request.env_vars)
                
                config_message = ""
                if request.auto_configure:
                    if local_config_updated:
                        config_message = "Local .mcp.json configuration updated automatically."
                    else:
                        config_message = "Claude Desktop configuration updated automatically."
                else:
                    config_message = "Manual configuration update required."
                
                # End logging session with success
                self.log_manager.end_session(True, f"Successfully installed {server_name}. {config_message}")
                
                return MCPInstallationResult(
                    success=True,
                    server_name=server_name,
                    option_name=option_name,
                    config_name=config_name,
                    message=f"Successfully installed {server_name}. {config_message}"
                )
            else:
                parsed_message = self._parse_npm_error(message) if (install_command.startswith("npm") or install_command.startswith("npx")) else message
                
                # End logging session with failure
                self.log_manager.end_session(False, f"Installation failed: {parsed_message}")
                
                return MCPInstallationResult(
                    success=False,
                    server_name=server_name,
                    option_name=option_name,
                    config_name=config_name,
                    message=f"Installation failed: {parsed_message}"
                )
                
        except Exception as e:
            logger.error(f"Installation failed: {e}")
            
            # End logging session with exception
            self.log_manager.end_session(False, f"Installation error: {str(e)}")
            
            return MCPInstallationResult(
                success=False,
                server_name=server_name,
                option_name=option_name,
                config_name=config_name,
                message=f"Installation error: {str(e)}"
            )

    def _get_server_definitions(self) -> Dict[str, Dict]:
        """Get server definitions with installation options from JSON config file."""
        # Try multiple locations for the config file
        config_locations = [
            # 1. User config directory (platform-specific, for user customizations)
            get_config_directory() / "server_definitions.json",
            # 2. Legacy location (for backward compatibility)
            Path.home() / ".meta-mcp" / "server_definitions.json",
            # 3. Current working directory (for development)
            Path.cwd() / "server_definitions.json",
            # 4. Package data (for pip installations)
            Path(__file__).parent / "server_definitions.json",
        ]
        
        # Try package resource first (most reliable for pip packages)
        try:
            import importlib.resources as resources
            with resources.open_text(__package__, "server_definitions.json") as f:
                return json.load(f)
        except (ImportError, FileNotFoundError, AttributeError):
            # Fall back to file system locations
            pass
        
        # Try filesystem locations
        for config_path in config_locations:
            try:
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        logger.info(f"Loaded server definitions from: {config_path}")
                        return json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse server definitions config at {config_path}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error loading server definitions from {config_path}: {e}")
                continue
        
        logger.warning("No server definitions config file found, using empty definitions")
        return {}

    def create_user_config_template(self) -> str:
        """Create a template server definitions config in user's platform-specific config directory."""
        user_config_dir = get_config_directory()
        user_config_dir.mkdir(parents=True, exist_ok=True)
        user_config_path = user_config_dir / "server_definitions.json"
        
        if user_config_path.exists():
            return f"User config already exists at: {user_config_path}"
        
        # Copy the default config to user directory
        try:
            import importlib.resources as resources
            with resources.open_text(__package__, "server_definitions.json") as f:
                default_config = f.read()
            
            with open(user_config_path, 'w') as f:
                f.write(default_config)
            
            return f"Created user config template at: {user_config_path}"
        except Exception as e:
            logger.error(f"Failed to create user config template: {e}")
            return f"Failed to create user config template: {e}"

    async def _get_install_command(self, server_name: str, option_name: str) -> Optional[str]:
        """Get installation command for a server and option."""
        # Look through all categories for the server
        for category_servers in self.server_definitions.values():
            if server_name in category_servers:
                server_info = category_servers[server_name]
                if option_name in server_info["options"]:
                    return server_info["options"][option_name]["install"]
        
        return None

    def _parse_npm_error(self, error_message: str) -> str:
        """Parse npm error messages to provide helpful suggestions."""
        if "EACCES" in error_message:
            return "Permission denied. Please try running the command with sudo, or check your npm permissions."
        if "lockfile" in error_message:
            return "An npm lockfile was detected, which can interfere with installations. Please remove the lockfile and try again."
        if "404 Not Found" in error_message:
            return "The requested package was not found in the npm registry. Please check the package name and try again."
        return error_message

    def get_server_option_info(self, server_name: str, option_name: str) -> Optional[Dict]:
        """Get complete option information for a server."""
        for category_servers in self.server_definitions.values():
            if server_name in category_servers:
                server_info = category_servers[server_name]
                if option_name in server_info["options"]:
                    return server_info["options"][option_name]
        return None

    async def _execute_installation(self, install_command: str) -> Tuple[bool, str]:
        """Legacy method - kept for backward compatibility. Use log_manager.log_installation_attempt instead."""
        try:
            # Split command into parts
            cmd_parts = install_command.split()
            
            # Execute installation
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=Path.home()
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return True, stdout.decode('utf-8')
            else:
                return False, stderr.decode('utf-8')
                
        except Exception as e:
            return False, str(e)

    async def _execute_installation_with_fallback(self, install_command: str, server_name: str, option_name: str) -> Tuple[bool, str]:
        """Execute installation with fallback mechanisms using enhanced logging."""
        # Try primary installation first
        success, message, log_data = await self.log_manager.log_installation_attempt(
            install_command, "primary"
        )
        
        if success:
            return True, message
        
        logger.info(f"Primary installation failed for {server_name}, trying fallback methods...")
        
        # Generate fallback commands
        fallback_commands = await self._generate_fallback_commands(server_name, option_name, install_command)
        
        for i, fallback_cmd in enumerate(fallback_commands, 1):
            logger.info(f"Trying fallback method {i}/{len(fallback_commands)}: {fallback_cmd}")
            
            try:
                success, fallback_message, fallback_log_data = await self.log_manager.log_installation_attempt(
                    fallback_cmd, f"fallback_{i}"
                )
                if success:
                    logger.info(f"Fallback method {i} succeeded for {server_name}")
                    return True, f"Installation succeeded using fallback method {i}: {fallback_message}"
                else:
                    logger.warning(f"Fallback method {i} failed: {fallback_message}")
            except Exception as e:
                logger.warning(f"Fallback method {i} error: {e}")
        
        # If all fallback methods failed, try to get README-based installation
        readme_command = await self._get_readme_install_command(server_name)
        if readme_command:
            logger.info(f"Trying README-based installation: {readme_command}")
            try:
                success, readme_message, readme_log_data = await self.log_manager.log_installation_attempt(
                    readme_command, "readme_based"
                )
                if success:
                    logger.info(f"README-based installation succeeded for {server_name}")
                    return True, f"Installation succeeded using README instructions: {readme_message}"
            except Exception as e:
                logger.warning(f"README-based installation failed: {e}")
        
        # All methods failed
        return False, f"All installation methods failed. Primary error: {message}"

    async def _update_claude_config(self, config_name: str, install_command: str, env_vars: Optional[Dict[str, str]]) -> None:
        """Update Claude Code CLI configuration with the new server."""
        try:
            # Determine command type and arguments
            if install_command.startswith("npx"):
                command = "npx"
                args = install_command.split()[1:]  # Skip 'npx'
            elif install_command.startswith("uvx"):
                command = "uvx" 
                # Extract the final command name from uvx --from git+... pattern
                parts = install_command.split()
                args = [parts[-1]]  # Last part is the command
            else:
                # Generic fallback
                parts = install_command.split()
                command = parts[0]
                args = parts[1:]
            
            # Determine working directory for Claude Code CLI
            # For globally installed servers (npx/uvx), no cwd needed
            # For local servers, use relative path from config location
            cwd = None
            if not (install_command.startswith("npx") or install_command.startswith("uvx")):
                # For local installations, use relative path
                cwd = f"./{config_name}"
            
            # Update configuration
            await self.config.add_server(config_name, command, args, cwd, env_vars)
            
        except Exception as e:
            logger.error(f"Failed to update Claude Code CLI config: {e}")

    async def list_installed_servers(self) -> List[MCPServerWithOptions]:
        """List all installed MCP servers."""
        servers = []
        
        for config_name, install_info in self.installed_servers.items():
            # Create server info from installation record
            server = MCPServerWithOptions(
                name=install_info["server_name"],
                display_name=install_info["server_name"].replace("-", " ").title(),
                description=f"Installed MCP server ({install_info['option_name']})",
                category=self._guess_category(install_info["server_name"]),
                status=MCPServerStatus.INSTALLED,
                options=[]  # Could be populated with available options
            )
            servers.append(server)
        
        return servers

    async def uninstall_server(self, server_name: str, remove_config: bool = True) -> bool:
        """Uninstall an MCP server."""
        try:
            # Find the server in our installation log
            config_to_remove = None
            for config_name, install_info in self.installed_servers.items():
                if install_info["server_name"] == server_name:
                    config_to_remove = config_name
                    break
            
            if not config_to_remove:
                logger.warning(f"Server {server_name} not found in installation log")
                return False
            
            # Remove from configuration if requested
            if remove_config:
                await self.config.remove_server(config_to_remove)
            
            # Remove from installation log
            del self.installed_servers[config_to_remove]
            self._save_installation_log()
            
            logger.info(f"Successfully uninstalled {server_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to uninstall {server_name}: {e}")
            return False

    async def update_server(self, server_name: str) -> str:
        """Update an MCP server to the latest version."""
        try:
            # Find the server
            config_name = None
            install_info = None
            for cfg_name, info in self.installed_servers.items():
                if info["server_name"] == server_name:
                    config_name = cfg_name
                    install_info = info
                    break
            
            if not install_info:
                return f"Server {server_name} is not installed"
            
            # Re-run the installation command to update with logging
            session_id = self.log_manager.start_session(server_name, "update", install_info["install_command"])
            success, message, log_data = await self.log_manager.log_installation_attempt(
                install_info["install_command"], "update"
            )
            
            if success:
                # Update the installation timestamp
                install_info["updated_at"] = datetime.now().isoformat()
                self._save_installation_log()
                self.log_manager.end_session(True, f"Successfully updated {server_name}")
                return f"Successfully updated {server_name}"
            else:
                self.log_manager.end_session(False, f"Failed to update {server_name}: {message}")
                return f"Failed to update {server_name}: {message}"
                
        except Exception as e:
            return f"Update failed: {str(e)}"

    async def get_server_health(self, server_name: str) -> Optional[MCPServerHealth]:
        """Get health status of an installed server."""
        try:
            # This would involve checking if the server process is running
            # For now, return basic status based on installation record
            
            config_name = None
            install_info = None
            for cfg_name, info in self.installed_servers.items():
                if info["server_name"] == server_name:
                    config_name = cfg_name
                    install_info = info
                    break
            
            if not install_info:
                return None
            
            # Basic health check - could be enhanced to actually ping the server
            status = MCPServerStatus.INSTALLED
            if install_info.get("status") == "error":
                status = MCPServerStatus.ERROR
            
            return MCPServerHealth(
                server_name=server_name,
                status=status,
                last_checked=datetime.now(),
                response_time_ms=None,  # Would measure actual response time
                error_message=install_info.get("last_error"),
                version=install_info.get("version")
            )
            
        except Exception as e:
            logger.error(f"Health check failed for {server_name}: {e}")
            return None

    async def get_server_documentation(self, server_name: str, format_type: str = "markdown") -> Optional[str]:
        """Get documentation for an installed server."""
        try:
            # Find installation info
            install_info = None
            for info in self.installed_servers.values():
                if info["server_name"] == server_name:
                    install_info = info
                    break
            
            if not install_info:
                return None
            
            # Generate documentation based on installation info
            docs = f"# {server_name.title()} Documentation\n\n"
            docs += f"**Installation Command:** `{install_info['install_command']}`\n\n"
            docs += f"**Installed:** {install_info['installed_at']}\n\n"
            
            if install_info.get("env_vars"):
                docs += "## Environment Variables\n\n"
                for key, value in install_info["env_vars"].items():
                    docs += f"- `{key}`: {value}\n"
                docs += "\n"
            
            docs += "## Configuration\n\n"
            docs += "This server is configured in your Claude Desktop configuration.\n"
            docs += "Restart Claude Desktop after any configuration changes.\n\n"
            
            docs += "## Troubleshooting\n\n"
            docs += "If the server is not working:\n"
            docs += "1. Check that all environment variables are set\n"
            docs += "2. Verify the installation completed successfully\n"
            docs += "3. Restart Claude Desktop\n"
            docs += "4. Check Claude Desktop logs for errors\n"
            
            return docs
            
        except Exception as e:
            logger.error(f"Failed to get documentation for {server_name}: {e}")
            return None

    def _guess_category(self, server_name: str):
        """Guess server category based on name."""
        from .models import MCPServerCategory
        
        name_lower = server_name.lower()
        
        if any(term in name_lower for term in ["search", "brave", "google", "perplexity"]):
            return MCPServerCategory.SEARCH
        elif any(term in name_lower for term in ["github", "gitlab", "git"]):
            return MCPServerCategory.VERSION_CONTROL
        elif any(term in name_lower for term in ["browser", "puppeteer", "firecrawl"]):
            return MCPServerCategory.AUTOMATION
        elif any(term in name_lower for term in ["code", "serena", "coding"]):
            return MCPServerCategory.CODING
        elif any(term in name_lower for term in ["context", "doc"]):
            return MCPServerCategory.CONTEXT
        elif any(term in name_lower for term in ["zen", "router"]):
            return MCPServerCategory.ORCHESTRATION
        else:
            return MCPServerCategory.OTHER

    async def check_prerequisites(self) -> Dict[str, bool]:
        """Check if required tools are installed."""
        prerequisites = {}
        
        # Check for npm
        try:
            process = await asyncio.create_subprocess_exec(
                "npm", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            prerequisites["npm"] = process.returncode == 0
        except FileNotFoundError:
            prerequisites["npm"] = False
        
        # Check for uvx
        try:
            process = await asyncio.create_subprocess_exec(
                "uvx", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            prerequisites["uvx"] = process.returncode == 0
        except FileNotFoundError:
            prerequisites["uvx"] = False
        
        # Check for node
        try:
            process = await asyncio.create_subprocess_exec(
                "node", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            prerequisites["node"] = process.returncode == 0
        except FileNotFoundError:
            prerequisites["node"] = False
        
        return prerequisites

    async def install_prerequisites(self) -> Dict[str, str]:
        """Install missing prerequisites."""
        results = {}
        
        # Check what's missing
        prereqs = await self.check_prerequisites()
        
        # Install uv if uvx is missing (uvx comes with uv)
        if not prereqs.get("uvx", False):
            try:
                # Install uv using the official installer
                process = await asyncio.create_subprocess_shell(
                    "curl -LsSf https://astral.sh/uv/install.sh | sh",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    results["uv"] = "Successfully installed uv/uvx"
                else:
                    results["uv"] = f"Failed to install uv: {stderr.decode()}"
            except Exception as e:
                results["uv"] = f"Error installing uv: {str(e)}"
        
        # Note about npm/node - these need to be installed by the user
        if not prereqs.get("npm", False) or not prereqs.get("node", False):
            results["node_npm"] = "Please install Node.js and npm from https://nodejs.org/"
        
        return results

    async def _generate_fallback_commands(self, server_name: str, option_name: str, original_command: str) -> List[str]:
        """Generate fallback installation commands for all known MCP servers."""
        fallback_commands = []
        
        # Comprehensive fallback mapping for all servers in meta-mcp
        fallback_mappings = {
            # Orchestration
            "zen-mcp": {
                "uvx_alternatives": [
                    "uvx --from git+https://github.com/BeehiveInnovations/zen-mcp-server zen-mcp-server",
                    "uvx --from git+https://github.com/199-mcp/mcp-zen zen-mcp-server"
                ],
                "npm_alternatives": []
            },
            
            # Context & Search
            "context7": {
                "uvx_alternatives": ["uvx @upstash/context7-mcp"],
                "npm_alternatives": ["npx -y @upstash/context7-mcp"]
            },
            "perplexity": {
                "uvx_alternatives": [
                    "uvx --from git+https://github.com/ppl-ai/modelcontextprotocol perplexity-mcp",
                    "uvx --from git+https://github.com/cyanheads/perplexity-mcp-server perplexity-mcp-server"
                ],
                "npm_alternatives": []
            },
            "brave-search": {
                "uvx_alternatives": [
                    "uvx @modelcontextprotocol/server-brave-search",
                    "uvx --from git+https://github.com/modelcontextprotocol/server-brave-search"
                ],
                "npm_alternatives": ["npx -y @modelcontextprotocol/server-brave-search"]
            },
            
            # Coding
            "serena": {
                "uvx_alternatives": ["uvx --from git+https://github.com/oraios/serena serena-mcp-server"],
                "npm_alternatives": []
            },
            
            # Automation & Browser
            "puppeteer": {
                "uvx_alternatives": [
                    "uvx @modelcontextprotocol/server-puppeteer",
                    "uvx --from git+https://github.com/modelcontextprotocol/server-puppeteer",
                    "uvx --from git+https://github.com/merajmehrabi/puppeteer-mcp-server puppeteer-mcp-server"
                ],
                "npm_alternatives": ["npx -y @modelcontextprotocol/server-puppeteer"]
            },
            "firecrawl": {
                "uvx_alternatives": ["uvx firecrawl-mcp"],
                "npm_alternatives": ["npx -y firecrawl-mcp"]
            },
            "desktop-commander": {
                "uvx_alternatives": ["uvx @wonderwhy-er/desktop-commander"],
                "npm_alternatives": ["npx @wonderwhy-er/desktop-commander@latest setup"]
            },
            "playwright": {
                "uvx_alternatives": ["uvx @executeautomation/playwright-mcp-server"],
                "npm_alternatives": [
                    "npx -y @executeautomation/playwright-mcp-server", 
                    "npm install -g @executeautomation/playwright-mcp-server"
                ]
            },
            "testsprite": {
                "uvx_alternatives": ["uvx @testsprite/mcp-server"],
                "npm_alternatives": [
                    "npx -y @testsprite/mcp-server",
                    "npm install -g @testsprite/mcp-server"
                ]
            },
            
            # Version Control
            "github": {
                "uvx_alternatives": [
                    "uvx @modelcontextprotocol/server-github",
                    "uvx --from git+https://github.com/modelcontextprotocol/server-github"
                ],
                "npm_alternatives": ["npx -y @modelcontextprotocol/server-github"]
            },
            "gitlab": {
                "uvx_alternatives": ["uvx --from git+https://github.com/zereight/gitlab-mcp gitlab-mcp"],
                "npm_alternatives": []
            },
            
            # Common MCP servers not in our definitions
            "filesystem": {
                "uvx_alternatives": [
                    "uvx @modelcontextprotocol/server-filesystem",
                    "uvx --from git+https://github.com/modelcontextprotocol/server-filesystem"
                ],
                "npm_alternatives": ["npx -y @modelcontextprotocol/server-filesystem"]
            },
            "sqlite": {
                "uvx_alternatives": [
                    "uvx @modelcontextprotocol/server-sqlite",
                    "uvx --from git+https://github.com/modelcontextprotocol/server-sqlite"
                ],
                "npm_alternatives": ["npx -y @modelcontextprotocol/server-sqlite"]
            }
        }
        
        # Get fallbacks for this specific server
        if server_name in fallback_mappings:
            server_fallbacks = fallback_mappings[server_name]
            
            # If original is npm/npx, try uvx alternatives
            if original_command.startswith(("npm", "npx")):
                fallback_commands.extend(server_fallbacks.get("uvx_alternatives", []))
                
            # If original is uvx, try npm alternatives
            elif original_command.startswith("uvx"):
                fallback_commands.extend(server_fallbacks.get("npm_alternatives", []))
            
            # Add all alternatives as final fallbacks
            fallback_commands.extend(server_fallbacks.get("uvx_alternatives", []))
            fallback_commands.extend(server_fallbacks.get("npm_alternatives", []))
        
        # Generic pattern-based fallbacks for unknown servers
        else:
            if original_command.startswith(("npm", "npx")):
                # Try to convert npm commands to uvx
                if "@modelcontextprotocol/server-" in original_command:
                    package_name = original_command.split()[-1]
                    fallback_commands.append(f"uvx {package_name}")
                    fallback_commands.append(f"uvx --from git+https://github.com/modelcontextprotocol/server-{server_name}")
                elif "@" in original_command:
                    package_name = original_command.split()[-1]
                    fallback_commands.append(f"uvx {package_name}")
                    
            elif original_command.startswith("uvx"):
                # Try to convert uvx commands to npm
                if "--from git+" in original_command and "modelcontextprotocol" in original_command:
                    fallback_commands.append(f"npx -y @modelcontextprotocol/server-{server_name}")
        
        # Remove duplicates and the original command
        fallback_commands = [cmd for cmd in fallback_commands if cmd != original_command]
        return list(dict.fromkeys(fallback_commands))  # Remove duplicates while preserving order

    async def _get_readme_install_command(self, server_name: str) -> Optional[str]:
        """Try to extract installation command from README files on GitHub."""
        github_patterns = [
            f"https://api.github.com/repos/modelcontextprotocol/server-{server_name}/readme",
            f"https://api.github.com/repos/{server_name}/{server_name}/readme",
            f"https://api.github.com/repos/{server_name}/{server_name}-mcp/readme",
            f"https://api.github.com/repos/{server_name}/{server_name}-mcp-server/readme",
        ]
        
        for url in github_patterns:
            try:
                async with httpx.AsyncClient() as client:
                    headers = {}
                    if hasattr(self, 'github_token') and self.github_token:
                        headers['Authorization'] = f'token {self.github_token}'
                    
                    response = await client.get(url, headers=headers, timeout=10.0)
                    if response.status_code == 200:
                        import base64
                        readme_content = base64.b64decode(response.json()['content']).decode('utf-8')
                        
                        # Look for common installation patterns
                        install_patterns = [
                            r'uvx\s+--from\s+[^\s]+\s+[^\s]+',
                            r'uvx\s+[^\s]+',
                            r'npx\s+-y\s+[^\s]+',
                            r'npm\s+install\s+-g\s+[^\s]+',
                            r'pip\s+install\s+[^\s]+',
                        ]
                        
                        import re
                        for pattern in install_patterns:
                            matches = re.findall(pattern, readme_content)
                            if matches:
                                # Return the first match that looks reasonable
                                return matches[0].strip()
                                
            except Exception as e:
                logger.debug(f"Failed to fetch README from {url}: {e}")
                continue
        
        return None

    async def get_installation_stats(self) -> Dict[str, Any]:
        """Get comprehensive installation statistics and analysis."""
        return self.log_manager.get_installation_stats()

    async def get_session_details(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific installation session."""
        return self.log_manager.get_session_details(session_id)

    async def cleanup_old_logs(self, days_to_keep: int = 30) -> int:
        """Clean up old installation logs. Returns number of files cleaned."""
        return self.log_manager.cleanup_old_logs(days_to_keep)

    async def export_installation_logs(self, output_path: Optional[str] = None) -> str:
        """Export installation logs for analysis or bug reporting."""
        try:
            if not output_path:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = f"mcp_installation_logs_{timestamp}.json"
            
            stats = await self.get_installation_stats()
            
            # Get recent session details
            recent_sessions = []
            for attempt in stats.get("recent_attempts", [])[:10]:  # Last 10 sessions
                if "session_id" in attempt:
                    session_details = await self.get_session_details(attempt["session_id"])
                    if session_details:
                        recent_sessions.append(session_details)
            
            export_data = {
                "export_timestamp": datetime.now().isoformat(),
                "stats": stats,
                "recent_sessions": recent_sessions,
                "system_info": self.log_manager._get_system_info()
            }
            
            with open(output_path, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)
            
            logger.info(f"Installation logs exported to {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Failed to export installation logs: {e}")
            raise

    async def _update_local_mcp_config(self, config_name: str, install_command: str, env_vars: Optional[Dict[str, str]]) -> bool:
        """Update .mcp.json in current working directory with user permission."""
        import os
        from pathlib import Path
        
        local_config_path = Path.cwd() / ".mcp.json"
        
        # Load existing config or create new one
        config_data = {}
        if local_config_path.exists():
            try:
                with open(local_config_path, 'r') as f:
                    config_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read existing .mcp.json: {e}")
                return False
        
        # Ensure mcpServers section exists
        if "mcpServers" not in config_data:
            config_data["mcpServers"] = {}
        
        # Generate server configuration
        server_config = {}
        
        # Determine command and args based on install command
        if install_command.startswith("uvx"):
            if "--from" in install_command:
                # uvx --from git+https://github.com/user/repo package-name
                parts = install_command.split()
                if len(parts) >= 4:
                    repo_url = parts[2]  # git+https://github.com/user/repo
                    package_name = parts[3]  # package-name
                    server_config["command"] = "uvx"
                    server_config["args"] = ["--from", repo_url, package_name]
            else:
                # uvx package-name
                parts = install_command.split()
                if len(parts) >= 2:
                    server_config["command"] = "uvx"
                    server_config["args"] = [parts[1]]
        elif install_command.startswith("npx"):
            # npx -y @package/name
            parts = install_command.split()
            if len(parts) >= 2:
                server_config["command"] = "npx"
                args = parts[1:]  # Include -y and package name
                server_config["args"] = args
        elif install_command.startswith("npm"):
            # For npm global installs, we need to figure out the actual command
            # This is tricky because npm install -g installs but doesn't run
            logger.warning(f"npm global install detected: {install_command}")
            logger.warning("You may need to manually configure the command in .mcp.json")
            return False
        
        # Add environment variables if provided
        if env_vars:
            server_config["env"] = env_vars
        
        # Add the server configuration
        config_data["mcpServers"][config_name] = server_config
        
        try:
            # Write the updated configuration
            with open(local_config_path, 'w') as f:
                json.dump(config_data, f, indent=2)
            
            logger.info(f"Updated .mcp.json with {config_name} configuration")
            return True
            
        except Exception as e:
            logger.error(f"Failed to write .mcp.json: {e}")
            return False
