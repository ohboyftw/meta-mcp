"""
AI-assisted installation fallback system for Meta MCP.

When standard installation and deterministic fallbacks fail, this module
provides AI-assisted suggestions by searching npm, PyPI, and GitHub
registries for the requested server package.

Ported from the ``magic-installation`` branch and adapted to use the
current ``clients.ClientManager`` and ``memory.ConversationalMemory``
interfaces (replacing the deleted ``integration_manager`` and
``logging_manager`` modules).
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from .clients import ClientManager, ClientType
from .memory import ConversationalMemory
from .models import AIInstallationRequest, AIInstallationResult

logger = logging.getLogger(__name__)


class AIFallbackManager:
    """Manages AI-assisted installation as a fallback mechanism.

    When all deterministic installation methods have failed, this manager
    searches package registries for the requested server, generates a
    suggested install command and integration config, and (after user
    approval) executes the suggestion.
    """

    def __init__(self) -> None:
        self.client_manager = ClientManager()
        self.memory = ConversationalMemory()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def request_ai_installation(
        self,
        server_name: str,
        failure_reason: str,
        target_clients: Optional[List[str]] = None,
    ) -> AIInstallationResult:
        """Request AI-assisted installation as fallback.

        Parameters
        ----------
        server_name:
            Name of the server that failed to install.
        failure_reason:
            Reason why standard installation failed.
        target_clients:
            Target MCP clients for integration.

        Returns
        -------
        AIInstallationResult
        """
        ai_request = AIInstallationRequest(
            server_name=server_name,
            reason=failure_reason,
            clients=target_clients or ["local_mcp_json"],
        )

        # Generate AI suggestions via registry search
        await self._generate_ai_suggestions(ai_request)

        if not ai_request.suggested_command:
            return AIInstallationResult(
                success=False,
                server_name=server_name,
                method="ai_fallback",
                command_executed=None,
                message="No installation suggestions could be generated",
            )

        # Request user approval
        if not await self._request_user_approval(ai_request):
            return AIInstallationResult(
                success=False,
                server_name=server_name,
                method="ai_fallback",
                command_executed=None,
                message="User declined AI-assisted installation",
            )

        # Execute AI-suggested installation
        return await self._execute_ai_installation(ai_request)

    # ------------------------------------------------------------------
    # Suggestion generation
    # ------------------------------------------------------------------

    async def _generate_ai_suggestions(
        self, request: AIInstallationRequest
    ) -> None:
        """Generate AI suggestions with registry search."""
        server_name = request.server_name

        # Check built-in patterns first
        suggestions = self._get_installation_suggestions(server_name)

        if not suggestions:
            logger.info("Searching package registries for '%s'...", server_name)

            npm_packages = await self._search_npm_registry(server_name)
            pypi_packages = await self._search_pypi_registry(server_name)

            if npm_packages:
                best_match = npm_packages[0]
                logger.info("Found npm package: %s", best_match)
                command_name = (
                    best_match.split("/")[-1]
                    if best_match.startswith("@")
                    else best_match
                )
                suggestions = {
                    "command": f"npm install -g {best_match}",
                    "integration": {
                        "command": command_name,
                        "args": [],
                        "description": f"Found via npm search: {best_match}",
                    },
                }
            elif pypi_packages:
                best_match = pypi_packages[0]
                logger.info("Found PyPI package: %s", best_match)
                suggestions = {
                    "command": f"pip install {best_match}",
                    "integration": {
                        "command": "python",
                        "args": ["-m", best_match.replace("-", "_")],
                        "description": f"Found via PyPI search: {best_match}",
                    },
                }
            else:
                logger.info("Searching GitHub repositories...")
                github_repo = await self._search_github_repos(server_name)
                if github_repo:
                    logger.info("Found GitHub repo: %s", github_repo)
                    suggestions = {
                        "command": f"uvx --from git+{github_repo} {server_name}",
                        "integration": {
                            "command": server_name,
                            "args": [],
                            "description": f"Found GitHub repo: {github_repo}",
                        },
                    }
                else:
                    logger.warning(
                        "No packages found in registries or GitHub for '%s'",
                        server_name,
                    )

        if suggestions:
            request.suggested_command = suggestions["command"]
            request.suggested_integration = suggestions["integration"]
            if "env_vars" in suggestions:
                request.env_vars = suggestions["env_vars"]

    def _get_installation_suggestions(
        self, server_name: str
    ) -> Optional[Dict[str, Any]]:
        """Get installation suggestions based on server name patterns."""
        patterns: Dict[str, Dict[str, Any]] = {
            "playwright": {
                "command": "npm install -g playwright-mcp-server",
                "integration": {
                    "command": "playwright-mcp-server",
                    "args": [],
                    "description": "Browser automation server",
                },
            },
            "mcp-atlassian": {
                "command": "pip install mcp-atlassian",
                "integration": {
                    "command": "python",
                    "args": ["-m", "mcp_atlassian"],
                    "description": "Atlassian integration server",
                },
                "env_vars": {
                    "ATLASSIAN_API_TOKEN": "your-atlassian-token",
                    "ATLASSIAN_EMAIL": "your-email@domain.com",
                    "ATLASSIAN_DOMAIN": "your-domain.atlassian.net",
                },
            },
            "obsidian": {
                "command": "npm install -g @mcp-obsidian/server",
                "integration": {
                    "command": "mcp-obsidian",
                    "args": [],
                    "description": "Obsidian note management",
                },
            },
            "slack": {
                "command": "pip install mcp-slack",
                "integration": {
                    "command": "python",
                    "args": ["-m", "mcp_slack"],
                    "description": "Slack integration server",
                },
                "env_vars": {
                    "SLACK_BOT_TOKEN": "xoxb-your-bot-token",
                    "SLACK_APP_TOKEN": "xapp-your-app-token",
                },
            },
        }

        # Exact match
        if server_name in patterns:
            return patterns[server_name]

        # Partial match
        for pattern, config in patterns.items():
            if (
                pattern.lower() in server_name.lower()
                or server_name.lower() in pattern.lower()
            ):
                return config

        # Generic npm / pip fallback for MCP-related names
        if "mcp" in server_name.lower():
            if server_name.startswith("@") or "-" in server_name:
                return {
                    "command": f"npm install -g {server_name}",
                    "integration": {
                        "command": server_name.replace("@", "").replace("/", "-"),
                        "args": [],
                        "description": f"AI-suggested {server_name} server",
                    },
                }
            return {
                "command": f"pip install {server_name}",
                "integration": {
                    "command": "python",
                    "args": ["-m", server_name.replace("-", "_")],
                    "description": f"AI-suggested {server_name} server",
                },
            }

        return None

    # ------------------------------------------------------------------
    # Registry search helpers
    # ------------------------------------------------------------------

    async def _search_npm_registry(self, server_name: str) -> List[str]:
        """Search npm registry for MCP server packages."""
        search_terms = [
            server_name,
            f"{server_name}-mcp",
            f"mcp-{server_name}",
            f"@modelcontextprotocol/server-{server_name}",
        ]

        found_packages: List[str] = []
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                for term in search_terms:
                    try:
                        response = await client.get(
                            f"https://registry.npmjs.org/-/v1/search?text={term}"
                        )
                        if response.status_code == 200:
                            results = response.json()
                            for pkg in results.get("objects", []):
                                name = pkg["package"]["name"]
                                description = (
                                    pkg["package"].get("description", "").lower()
                                )
                                keywords = pkg["package"].get("keywords", [])
                                keywords_str = (
                                    " ".join(keywords).lower() if keywords else ""
                                )
                                if (
                                    "mcp" in description
                                    or "model context protocol" in description
                                    or "mcp" in keywords_str
                                    or "model-context-protocol" in name.lower()
                                ):
                                    if name not in found_packages:
                                        found_packages.append(name)
                        if len(found_packages) >= 3:
                            break
                    except Exception as exc:
                        logger.debug("Error searching npm for %s: %s", term, exc)
        except ImportError:
            logger.debug("httpx not available for npm search")
        except Exception as exc:
            logger.debug("npm registry search failed: %s", exc)

        return found_packages[:3]

    async def _search_pypi_registry(self, server_name: str) -> List[str]:
        """Search PyPI registry for MCP server packages."""
        search_terms = [
            server_name,
            f"{server_name}-mcp",
            f"mcp-{server_name}",
            f"mcp_{server_name}",
        ]

        found_packages: List[str] = []
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                for term in search_terms:
                    try:
                        response = await client.get(
                            f"https://pypi.org/pypi/{term}/json"
                        )
                        if response.status_code == 200:
                            pkg_info = response.json()
                            description = (
                                pkg_info.get("info", {}).get("summary", "").lower()
                            )
                            name = pkg_info.get("info", {}).get("name", term)
                            if (
                                "mcp" in description
                                or "model context protocol" in description
                                or "mcp" in name.lower()
                            ):
                                if name not in found_packages:
                                    found_packages.append(name)
                    except Exception:
                        continue
        except ImportError:
            logger.debug("httpx not available for PyPI search")
        except Exception as exc:
            logger.debug("PyPI registry search failed: %s", exc)

        return found_packages[:3]

    async def _search_github_repos(self, server_name: str) -> Optional[str]:
        """Search GitHub for MCP server repositories."""
        search_queries = [
            f"{server_name} mcp server",
            f"mcp {server_name}",
            f"{server_name}-mcp-server",
        ]

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                for query in search_queries:
                    try:
                        headers = {"Accept": "application/vnd.github.v3+json"}
                        response = await client.get(
                            f"https://api.github.com/search/repositories?q={query}",
                            headers=headers,
                        )
                        if response.status_code == 200:
                            results = response.json()
                            for repo in results.get("items", [])[:3]:
                                description = (
                                    repo.get("description") or ""
                                ).lower()
                                name = repo.get("name", "").lower()
                                if (
                                    "mcp" in description
                                    or "model context protocol" in description
                                    or "mcp" in name
                                ):
                                    clone_url = repo["clone_url"]
                                    return clone_url.replace(".git", "")
                    except Exception as exc:
                        logger.debug(
                            "Error searching GitHub for %s: %s", query, exc
                        )
        except ImportError:
            logger.debug("httpx not available for GitHub search")
        except Exception as exc:
            logger.debug("GitHub repository search failed: %s", exc)

        return None

    # ------------------------------------------------------------------
    # User approval
    # ------------------------------------------------------------------

    async def _request_user_approval(
        self, request: AIInstallationRequest
    ) -> bool:
        """Request user approval for AI-suggested installation.

        In a non-interactive context this returns ``False`` unless
        ``request.user_approved`` was already set to ``True`` externally.
        """
        if request.user_approved:
            return True

        # Log the suggestion for the caller to present to the user
        logger.info(
            "AI suggestion for '%s': command=%s",
            request.server_name,
            request.suggested_command,
        )
        return False

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute_ai_installation(
        self, request: AIInstallationRequest
    ) -> AIInstallationResult:
        """Execute the AI-suggested installation."""
        logger.info(
            "Executing AI-suggested installation: %s", request.suggested_command
        )

        try:
            result = await self._run_installation_command(
                request.suggested_command or ""
            )

            if result["success"]:
                logger.info("AI installation command completed successfully")

                # Record success in memory
                self.memory.record_installation(
                    server=request.server_name,
                    option="ai_fallback",
                    success=True,
                )

                # Create integration configuration
                integration_success = await self._create_ai_integration(request)

                return AIInstallationResult(
                    success=True,
                    server_name=request.server_name,
                    method="ai_fallback",
                    command_executed=request.suggested_command,
                    integration_created=integration_success,
                    message=(
                        f"AI-assisted installation of {request.server_name} completed"
                    ),
                    warnings=[
                        "This was an AI-suggested installation -- "
                        "please verify functionality"
                    ],
                )
            else:
                error_msg = result.get("error", "Unknown error")

                # Record failure in memory
                self.memory.record_failure(
                    server=request.server_name,
                    error_sig="ai_installation_failed",
                    error_msg=error_msg,
                )

                return AIInstallationResult(
                    success=False,
                    server_name=request.server_name,
                    method="ai_fallback",
                    command_executed=request.suggested_command,
                    message=f"AI-assisted installation failed: {error_msg}",
                )

        except Exception as exc:
            self.memory.record_failure(
                server=request.server_name,
                error_sig="ai_installation_error",
                error_msg=str(exc),
            )
            return AIInstallationResult(
                success=False,
                server_name=request.server_name,
                method="ai_fallback",
                command_executed=request.suggested_command,
                message=f"AI-assisted installation error: {exc}",
            )

    async def _run_installation_command(
        self, command: str
    ) -> Dict[str, Any]:
        """Run the AI-suggested installation command."""
        try:
            cmd_parts = command.split()
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return {
                    "success": True,
                    "stdout": stdout.decode(),
                    "stderr": stderr.decode(),
                }
            return {
                "success": False,
                "error": stderr.decode() or stdout.decode(),
                "return_code": process.returncode,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _create_ai_integration(
        self, request: AIInstallationRequest
    ) -> bool:
        """Create integration configuration for AI-installed server."""
        if not request.suggested_integration:
            return False

        try:
            command = request.suggested_integration["command"]
            args = request.suggested_integration.get("args", [])
            env = request.env_vars or {}

            # Map client string names to ClientType enum values
            _CLIENT_TYPE_MAP: Dict[str, ClientType] = {
                "local_mcp_json": ClientType.CLAUDE_CODE,
                "claude_desktop": ClientType.CLAUDE_DESKTOP,
                "claude_code": ClientType.CLAUDE_CODE,
                "cursor": ClientType.CURSOR,
                "vscode": ClientType.VSCODE,
                "windsurf": ClientType.WINDSURF,
                "zed": ClientType.ZED,
            }

            any_success = False
            for client_name in request.clients or ["local_mcp_json"]:
                client_type = _CLIENT_TYPE_MAP.get(client_name)
                if client_type is None:
                    logger.warning("Unknown client name: %s", client_name)
                    continue
                ok = self.client_manager.configure_server_for_client(
                    client=client_type,
                    server_name=request.server_name,
                    command=command,
                    args=args,
                    env=env,
                )
                if ok:
                    any_success = True

            return any_success

        except Exception as exc:
            logger.warning("Failed to create AI integration: %s", exc)
            return False
