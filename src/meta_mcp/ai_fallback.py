"""
AI-assisted installation fallback system for Meta MCP.

This module provides AI-assisted installation as a fallback when 
standard Meta MCP installation fails.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from .models import AIInstallationRequest, AIInstallationResult, IntegrationResult
from .integration_manager import MCPIntegrationManager
from .logging_manager import InstallationLogManager


class AIFallbackManager:
    """Manages AI-assisted installation as fallback mechanism."""

    def __init__(self):
        self.integration_manager = MCPIntegrationManager()
        self.log_manager = InstallationLogManager()

    async def request_ai_installation(
        self,
        server_name: str,
        failure_reason: str,
        target_clients: Optional[List[str]] = None,
    ) -> AIInstallationResult:
        """
        Request AI-assisted installation as fallback.
        
        Args:
            server_name: Name of server that failed to install
            failure_reason: Reason why standard installation failed
            target_clients: Target MCP clients for integration
            
        Returns:
            Result of AI-assisted installation
        """
        # Create AI installation request
        ai_request = AIInstallationRequest(
            server_name=server_name,
            reason=failure_reason,
            clients=target_clients or ["local_mcp_json"],
        )

        # Generate AI suggestions
        await self._generate_ai_suggestions(ai_request)

        # Present to user for approval
        if not await self._request_user_approval(ai_request):
            return AIInstallationResult(
                success=False,
                server_name=server_name,
                method="ai_fallback",
                command_executed="",
                message="❌ User declined AI-assisted installation",
            )

        # Execute AI-suggested installation
        return await self._execute_ai_installation(ai_request)

    async def _generate_ai_suggestions(self, request: AIInstallationRequest) -> None:
        """Generate AI suggestions with registry search."""
        server_name = request.server_name

        # First check built-in patterns
        suggestions = self._get_installation_suggestions(server_name)
        
        if not suggestions:
            # Search registries for real packages
            print(f"🔍 Searching package registries for '{server_name}'...")
            
            # Search npm registry
            npm_packages = await self._search_npm_registry(server_name)
            
            # Search PyPI registry  
            pypi_packages = await self._search_pypi_registry(server_name)
            
            if npm_packages:
                # Use the most relevant npm package
                best_match = npm_packages[0]
                print(f"📦 Found npm package: {best_match}")
                
                # Extract command name from package name
                if best_match.startswith('@'):
                    # For scoped packages like @modelcontextprotocol/server-brave-search
                    command_name = best_match.split('/')[-1]
                else:
                    # For regular packages
                    command_name = best_match
                
                suggestions = {
                    "command": f"npm install -g {best_match}",
                    "integration": {
                        "command": command_name,
                        "args": [],
                        "description": f"Found via npm search: {best_match}"
                    }
                }
                
            elif pypi_packages:
                # Use the most relevant PyPI package  
                best_match = pypi_packages[0]
                print(f"🐍 Found PyPI package: {best_match}")
                
                suggestions = {
                    "command": f"pip install {best_match}",
                    "integration": {
                        "command": "python",
                        "args": ["-m", best_match.replace("-", "_")],
                        "description": f"Found via PyPI search: {best_match}"
                    }
                }
                
            else:
                # Last resort: GitHub repository search
                print("🔍 Searching GitHub repositories...")
                github_repo = await self._search_github_repos(server_name)
                
                if github_repo:
                    print(f"📁 Found GitHub repo: {github_repo}")
                    
                    suggestions = {
                        "command": f"uvx --from git+{github_repo} {server_name}",
                        "integration": {
                            "command": server_name,
                            "args": [],
                            "description": f"Found GitHub repo: {github_repo}"
                        }
                    }
                else:
                    print("❌ No packages found in registries or GitHub")
        
        if suggestions:
            request.suggested_command = suggestions["command"]
            request.suggested_integration = suggestions["integration"]

    def _get_installation_suggestions(self, server_name: str) -> Optional[Dict[str, Any]]:
        """Get installation suggestions based on server name patterns."""
        
        # Common patterns for MCP servers
        patterns = {
            "playwright": {
                "command": "npm install -g playwright-mcp-server",
                "integration": {
                    "command": "playwright-mcp-server",
                    "args": [],
                    "description": "Browser automation server"
                }
            },
            "mcp-atlassian": {
                "command": "pip install mcp-atlassian",
                "integration": {
                    "command": "python",
                    "args": ["-m", "mcp_atlassian"],
                    "description": "Atlassian integration server"
                },
                "env_vars": {
                    "ATLASSIAN_API_TOKEN": "your-atlassian-token",
                    "ATLASSIAN_EMAIL": "your-email@domain.com",
                    "ATLASSIAN_DOMAIN": "your-domain.atlassian.net"
                }
            },
            "obsidian": {
                "command": "npm install -g @mcp-obsidian/server",
                "integration": {
                    "command": "mcp-obsidian",
                    "args": [],
                    "description": "Obsidian note management"
                }
            },
            "slack": {
                "command": "pip install mcp-slack",
                "integration": {
                    "command": "python",
                    "args": ["-m", "mcp_slack"],
                    "description": "Slack integration server"
                },
                "env_vars": {
                    "SLACK_BOT_TOKEN": "xoxb-your-bot-token",
                    "SLACK_APP_TOKEN": "xapp-your-app-token"
                }
            }
        }

        # Check for exact matches
        if server_name in patterns:
            return patterns[server_name]

        # Check for partial matches
        for pattern, config in patterns.items():
            if pattern.lower() in server_name.lower() or server_name.lower() in pattern.lower():
                return config

        # Generic npm/pip fallback
        if "mcp" in server_name.lower():
            if server_name.startswith("@") or "-" in server_name:
                # Likely npm package
                return {
                    "command": f"npm install -g {server_name}",
                    "integration": {
                        "command": server_name.replace("@", "").replace("/", "-"),
                        "args": [],
                        "description": f"AI-suggested {server_name} server"
                    }
                }
            else:
                # Likely pip package
                return {
                    "command": f"pip install {server_name}",
                    "integration": {
                        "command": "python",
                        "args": ["-m", server_name.replace("-", "_")],
                        "description": f"AI-suggested {server_name} server"
                    }
                }

        return None

    async def _search_npm_registry(self, server_name: str) -> List[str]:
        """Search npm registry for MCP server packages."""
        search_terms = [
            server_name,
            f"{server_name}-mcp",
            f"mcp-{server_name}",
            f"@{server_name}/mcp-server",
            f"@modelcontextprotocol/server-{server_name}",
            f"@executeautomation/{server_name}-mcp-server"
        ]
        
        found_packages = []
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                for term in search_terms:
                    try:
                        response = await client.get(f"https://registry.npmjs.org/-/v1/search?text={term}")
                        if response.status_code == 200:
                            results = response.json()
                            for pkg in results.get('objects', []):
                                name = pkg['package']['name']
                                description = pkg['package'].get('description', '').lower()
                                keywords = pkg['package'].get('keywords', [])
                                keywords_str = ' '.join(keywords).lower() if keywords else ''
                                
                                # Check if it's MCP-related
                                if (
                                    'mcp' in description or 
                                    'model context protocol' in description or
                                    'mcp' in keywords_str or
                                    'model-context-protocol' in name.lower()
                                ):
                                    found_packages.append(name)
                                    
                        # Limit requests to avoid rate limiting
                        if len(found_packages) >= 3:
                            break
                            
                    except Exception as e:
                        print(f"Error searching npm for {term}: {e}")
                        continue
                        
        except ImportError:
            print("httpx not available for npm search")
        except Exception as e:
            print(f"npm registry search failed: {e}")
            
        return found_packages[:3]  # Return top 3 matches

    async def _search_pypi_registry(self, server_name: str) -> List[str]:
        """Search PyPI registry for MCP server packages."""
        search_terms = [
            server_name,
            f"{server_name}-mcp", 
            f"mcp-{server_name}",
            f"mcp_{server_name}",
            f"{server_name.replace('-', '_')}"
        ]
        
        found_packages = []
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                for term in search_terms:
                    try:
                        # Try exact package lookup first
                        response = await client.get(f"https://pypi.org/pypi/{term}/json")
                        if response.status_code == 200:
                            pkg_info = response.json()
                            description = pkg_info.get('info', {}).get('summary', '').lower()
                            name = pkg_info.get('info', {}).get('name', term)
                            
                            if (
                                'mcp' in description or 
                                'model context protocol' in description or
                                'mcp' in name.lower()
                            ):
                                found_packages.append(name)
                                
                    except Exception:
                        # If exact lookup fails, try search API
                        try:
                            search_response = await client.get(
                                f"https://pypi.org/search/?q={term}",
                                headers={'Accept': 'application/json'}
                            )
                            # PyPI search API is limited, so we'll skip complex parsing
                        except Exception:
                            continue
                            
        except ImportError:
            print("httpx not available for PyPI search")
        except Exception as e:
            print(f"PyPI registry search failed: {e}")
            
        return found_packages[:3]  # Return top 3 matches

    async def _search_github_repos(self, server_name: str) -> Optional[str]:
        """Search GitHub for MCP server repositories."""
        search_queries = [
            f"{server_name} mcp server",
            f"mcp {server_name}",
            f"model context protocol {server_name}",
            f"{server_name}-mcp-server"
        ]
        
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                for query in search_queries:
                    try:
                        headers = {'Accept': 'application/vnd.github.v3+json'}
                        # Note: Could add GitHub token here for higher rate limits
                        # if hasattr(self, 'github_token') and self.github_token:
                        #     headers['Authorization'] = f'token {self.github_token}'
                            
                        response = await client.get(
                            f"https://api.github.com/search/repositories?q={query}",
                            headers=headers
                        )
                        
                        if response.status_code == 200:
                            results = response.json()
                            for repo in results.get('items', [])[:3]:  # Check top 3
                                description = (repo.get('description') or '').lower()
                                name = repo.get('name', '').lower()
                                
                                if (
                                    'mcp' in description or 
                                    'model context protocol' in description or
                                    'mcp' in name
                                ):
                                    return repo['clone_url'].replace('.git', '')
                                    
                    except Exception as e:
                        print(f"Error searching GitHub for {query}: {e}")
                        continue
                        
        except ImportError:
            print("httpx not available for GitHub search")
        except Exception as e:
            print(f"GitHub repository search failed: {e}")
            
        return None

    async def _request_user_approval(self, request: AIInstallationRequest) -> bool:
        """Request user approval with search context."""
        
        print("\n" + "=" * 60)
        print("🤖 AI-ASSISTED INSTALLATION FALLBACK")
        print("=" * 60)
        print(f"📦 Server: {request.server_name}")
        print(f"❌ Standard installation failed: {request.reason}")
        
        # Show search context based on description
        if request.suggested_integration:
            description = request.suggested_integration.get("description", "")
            
            if "Found via npm search:" in description:
                print("🔍 Search Result: Found via npm registry search")
                package_name = description.split("Found via npm search: ")[-1]
                print(f"   Package: {package_name}")
            elif "Found via PyPI search:" in description:
                print("🔍 Search Result: Found via PyPI registry search") 
                package_name = description.split("Found via PyPI search: ")[-1]
                print(f"   Package: {package_name}")
            elif "Found GitHub repo:" in description:
                print("🔍 Search Result: Found via GitHub repository search")
                repo_url = description.split("Found GitHub repo: ")[-1]
                print(f"   Repository: {repo_url}")
            else:
                print("🧠 Source: Generated from built-in patterns")
                
        print(f"\n💡 AI Suggestion:")
        print(f"   Command: {request.suggested_command}")
        
        if request.env_vars:
            print("   Environment variables needed:")
            for key, value in request.env_vars.items():
                print(f"     - {key}: {value}")
        
        if request.suggested_integration:
            print("   Integration config:")
            integration = request.suggested_integration
            print(f"     - Command: {integration.get('command')}")
            print(f"     - Args: {integration.get('args', [])}")
        
        print("\n⚠️  WARNING: AI-suggested installation is experimental")
        print("   - Meta MCP cannot guarantee compatibility")
        print("   - Please review the suggested command carefully")
        print("   - You can cancel and install manually if preferred")
        
        while True:
            response = input("\n❓ Proceed with AI-suggested installation? [y/N/details/manual]: ").strip().lower()
            
            if response in ['y', 'yes']:
                request.user_approved = True
                return True
            elif response in ['n', 'no', '']:
                return False
            elif response == 'details':
                await self._show_detailed_info(request)
                continue
            elif response == 'manual':
                self._show_manual_instructions(request)
                return False
            else:
                print("Please enter 'y' (yes), 'n' (no), 'details', or 'manual'")

    async def _show_detailed_info(self, request: AIInstallationRequest) -> None:
        """Show detailed information about the AI suggestion."""
        print("\n📋 DETAILED AI SUGGESTION INFO")
        print("-" * 40)
        print(f"Server name: {request.server_name}")
        print(f"Suggested command: {request.suggested_command}")
        print(f"Installation method: {'npm' if 'npm' in request.suggested_command else 'pip'}")
        
        if request.suggested_integration:
            print("\nProposed integration configuration:")
            print(json.dumps(request.suggested_integration, indent=2))
        
        print(f"\nTarget clients: {', '.join(request.clients or ['local_mcp_json'])}")
        
        print("\n🔍 How AI made this suggestion:")
        print("   1. Analyzed server name patterns")
        print("   2. Matched against common MCP server formats")
        print("   3. Generated compatible installation command")
        print("   4. Created integration configuration template")

    def _show_manual_instructions(self, request: AIInstallationRequest) -> None:
        """Show manual installation instructions."""
        print("\n📖 MANUAL INSTALLATION INSTRUCTIONS")
        print("-" * 45)
        print("You can install this server manually by:")
        print(f"1. Running: {request.suggested_command}")
        print("2. Adding to your MCP client configuration:")
        
        if request.suggested_integration:
            integration = request.suggested_integration
            config = {
                "mcpServers": {
                    request.server_name: {
                        "command": integration.get("command"),
                        "args": integration.get("args", []),
                        "env": request.env_vars or {}
                    }
                }
            }
            print(json.dumps(config, indent=2))
        
        print("\n3. Restart your MCP client")
        
        if request.env_vars:
            print(f"\n4. Set environment variables:")
            for key, value in request.env_vars.items():
                print(f"   export {key}={value}")

    async def _execute_ai_installation(self, request: AIInstallationRequest) -> AIInstallationResult:
        """Execute the AI-suggested installation."""
        
        print(f"\n🤖 Executing AI-suggested installation...")
        print(f"Command: {request.suggested_command}")
        
        # Start logging session
        session_id = self.log_manager.start_session(
            request.server_name, "ai_fallback", request.suggested_command
        )
        
        try:
            # Execute installation command
            result = await self._run_installation_command(request.suggested_command)
            
            if result["success"]:
                print("✅ Installation command completed successfully")
                
                # Create integration configuration
                integration_success = await self._create_ai_integration(request)
                
                # Log successful installation
                self.log_manager.log_success(
                    session_id, "AI-assisted installation completed"
                )
                
                return AIInstallationResult(
                    success=True,
                    server_name=request.server_name,
                    method="ai_fallback",
                    command_executed=request.suggested_command,
                    integration_created=integration_success,
                    message=f"✅ AI-assisted installation of {request.server_name} completed",
                    warnings=["⚠️ This was an AI-suggested installation - please verify functionality"]
                )
            else:
                # Log failed installation
                self.log_manager.log_error(
                    session_id, "ai_installation_failed", result["error"]
                )
                
                return AIInstallationResult(
                    success=False,
                    server_name=request.server_name,
                    method="ai_fallback",
                    command_executed=request.suggested_command,
                    message=f"❌ AI-assisted installation failed: {result['error']}"
                )
                
        except Exception as e:
            self.log_manager.log_error(session_id, "ai_installation_error", str(e))
            
            return AIInstallationResult(
                success=False,
                server_name=request.server_name,
                method="ai_fallback", 
                command_executed=request.suggested_command,
                message=f"❌ AI-assisted installation error: {str(e)}"
            )

    async def _run_installation_command(self, command: str) -> Dict[str, Any]:
        """Run the AI-suggested installation command."""
        try:
            # Split command into parts
            cmd_parts = command.split()
            
            # Execute command
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return {
                    "success": True,
                    "stdout": stdout.decode(),
                    "stderr": stderr.decode()
                }
            else:
                return {
                    "success": False,
                    "error": stderr.decode() or stdout.decode(),
                    "return_code": process.returncode
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def _create_ai_integration(self, request: AIInstallationRequest) -> bool:
        """Create integration configuration for AI-installed server."""
        
        if not request.suggested_integration:
            return False
        
        try:
            # Create integration config
            integration_config = {
                "command": request.suggested_integration["command"],
                "args": request.suggested_integration.get("args", []),
                "description": request.suggested_integration.get("description", f"AI-installed {request.server_name}"),
                "env": request.env_vars or {}
            }
            
            # Use integration manager to set up client configurations
            results = await self.integration_manager.integrate_server(
                request.server_name,
                integration_config,
                request.clients or ["local_mcp_json"]
            )
            
            # Check if any integration succeeded
            return any(result.success for result in results)
            
        except Exception as e:
            print(f"⚠️ Failed to create integration: {e}")
            return False