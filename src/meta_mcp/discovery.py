"""
MCP Server Discovery Engine.

This module handles discovering MCP servers from various sources including
GitHub repositories, curated lists, and community registries.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import httpx

from .models import (
    MCPServerCategory,
    MCPServerOption,
    MCPServerWithOptions,
    MCPSearchQuery,
    MCPSearchResult,
)

logger = logging.getLogger(__name__)


class MCPDiscovery:
    """Discovers MCP servers from various sources."""

    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token
        self.client = httpx.AsyncClient(
            timeout=30.0, headers=self._get_github_headers() if github_token else {}
        )
        self.server_cache: Dict[str, MCPServerWithOptions] = {}
        self.cache_expiry = timedelta(hours=1)
        self.last_cache_update: Optional[datetime] = None

        # Known MCP server repositories and patterns
        self.known_sources = [
            "https://api.github.com/repos/modelcontextprotocol/servers/contents/src",
            "https://api.github.com/repos/wong2/awesome-mcp-servers",
            "https://api.github.com/repos/punkpeye/awesome-mcp-servers",
            "https://api.github.com/repos/appcypher/awesome-mcp-servers",
            "https://api.github.com/repos/hesreallyhim/awesome-claude-code",
        ]

        # ClaudeLog.com curated servers
        self.claudelog_servers = [
            "https://claudelog.com/faqs/claude-code-best-mcps/",
            "https://claudelog.com/addons/",  # For additional MCP tools
        ]

        # MCP server patterns for GitHub search
        self.search_patterns = [
            "mcp-server",
            "mcp server",
            "model-context-protocol",
            "claude mcp",
            "mcp client",
        ]

    def _get_github_headers(self) -> Dict[str, str]:
        """Get GitHub API headers."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "MCP-Manager/0.1.0",
        }
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
        return headers

    async def search_servers(self, query: MCPSearchQuery) -> MCPSearchResult:
        """Search for MCP servers based on query parameters."""
        start_time = datetime.now()

        # Ensure cache is fresh
        await self._update_cache_if_needed()

        # Filter servers based on query
        filtered_servers = self._filter_servers(query)

        # Sort results
        sorted_servers = self._sort_servers(
            filtered_servers, query.sort_by or "relevance"
        )

        # Limit results
        if query.limit:
            sorted_servers = sorted_servers[: query.limit]

        search_time = int((datetime.now() - start_time).total_seconds() * 1000)

        return MCPSearchResult(
            query=query,
            total_count=len(filtered_servers),
            servers=sorted_servers,
            search_time_ms=search_time,
        )

    async def get_server_info(self, server_name: str) -> Optional[MCPServerWithOptions]:
        """Get detailed information about a specific server."""
        await self._update_cache_if_needed()
        return self.server_cache.get(server_name)

    async def discover_new_servers(
        self, force_refresh: bool = False
    ) -> List[MCPServerWithOptions]:
        """Discover new MCP servers from all sources."""
        if force_refresh or self._cache_expired():
            await self._refresh_server_cache()

        return list(self.server_cache.values())

    async def _update_cache_if_needed(self) -> None:
        """Update cache if it's expired or empty."""
        if self._cache_expired() or not self.server_cache:
            await self._refresh_server_cache()

    def _cache_expired(self) -> bool:
        """Check if cache has expired."""
        if not self.last_cache_update:
            return True
        return datetime.now() - self.last_cache_update > self.cache_expiry

    async def _refresh_server_cache(self) -> None:
        """Refresh the server cache from all sources."""
        logger.info("Refreshing MCP server cache...")

        # Discover from multiple sources in parallel
        tasks = [
            self._discover_from_official_repo(),
            self._discover_from_awesome_lists(),
            self._discover_from_github_search(),
            self._discover_from_curated_list(),
            self._discover_from_claudelog(),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results
        all_servers = {}
        for result in results:
            if isinstance(result, dict):
                all_servers.update(result)
            elif isinstance(result, Exception):
                logger.warning(f"Discovery source failed: {result}")

        self.server_cache = all_servers
        self.last_cache_update = datetime.now()

        logger.info(f"Discovered {len(all_servers)} MCP servers")

    async def _discover_from_official_repo(self) -> Dict[str, MCPServerWithOptions]:
        """Discover servers from the official MCP servers repository."""
        servers = {}

        try:
            # Get contents of the src directory
            response = await self.client.get(
                "https://api.github.com/repos/modelcontextprotocol/servers/contents/src"
            )
            response.raise_for_status()

            contents = response.json()

            for item in contents:
                if item["type"] == "dir":
                    server_name = item["name"]
                    server_info = await self._get_official_server_info(
                        server_name, item["url"]
                    )
                    if server_info:
                        servers[server_name] = server_info

        except Exception as e:
            logger.warning(f"Failed to discover from official repo: {e}")

        return servers

    async def _get_official_server_info(
        self, server_name: str, contents_url: str
    ) -> Optional[MCPServerWithOptions]:
        """Get information about an official MCP server."""
        try:
            # Get the contents of the server directory
            response = await self.client.get(contents_url)
            response.raise_for_status()

            contents = response.json()

            # Look for README file
            readme_content = None
            for file_info in contents:
                if file_info["name"].lower().startswith("readme"):
                    readme_response = await self.client.get(file_info["download_url"])
                    readme_response.raise_for_status()
                    readme_content = readme_response.text
                    break

            # Parse server information
            description = (
                self._extract_description_from_readme(readme_content)
                if readme_content
                else f"Official {server_name} MCP server"
            )
            category = self._categorize_server(server_name, description)

            # Create server info
            server_info = MCPServerWithOptions(
                name=server_name,
                display_name=server_name.replace("-", " ").title(),
                description=description,
                category=category,
                repository_url=f"https://github.com/modelcontextprotocol/servers/tree/main/src/{server_name}",
                documentation_url=f"https://github.com/modelcontextprotocol/servers/blob/main/src/{server_name}/README.md",
                author="Model Context Protocol Team",
                license="MIT",
                keywords=self._extract_keywords(server_name, description),
                options=[
                    MCPServerOption(
                        name="official",
                        display_name="Official",
                        description="Official implementation",
                        install_command=f"npx -y @modelcontextprotocol/server-{server_name}",
                        config_name=server_name,
                        env_vars=(
                            self._extract_env_vars_from_readme(readme_content)
                            if readme_content
                            else []
                        ),
                        repository_url=f"https://github.com/modelcontextprotocol/servers/tree/main/src/{server_name}",
                        recommended=True,
                    )
                ],
            )

            return server_info

        except Exception as e:
            logger.warning(f"Failed to get info for official server {server_name}: {e}")
            return None

    async def _discover_from_awesome_lists(self) -> Dict[str, MCPServerWithOptions]:
        """Discover servers from awesome MCP server lists."""
        servers = {}

        awesome_repos = [
            "wong2/awesome-mcp-servers",
            "punkpeye/awesome-mcp-servers",
            "appcypher/awesome-mcp-servers",
        ]

        for repo in awesome_repos:
            try:
                response = await self.client.get(
                    f"https://api.github.com/repos/{repo}/readme"
                )
                response.raise_for_status()

                readme_data = response.json()
                readme_content = self._decode_base64_content(readme_data["content"])

                # Parse README for MCP servers
                parsed_servers = self._parse_awesome_readme(readme_content, repo)
                servers.update(parsed_servers)

            except Exception as e:
                logger.warning(f"Failed to discover from awesome list {repo}: {e}")

        return servers

    async def _discover_from_github_search(self) -> Dict[str, MCPServerWithOptions]:
        """Discover servers using GitHub search API."""
        servers = {}

        for pattern in self.search_patterns:
            try:
                # Search for repositories
                response = await self.client.get(
                    "https://api.github.com/search/repositories",
                    params={
                        "q": f"{pattern} language:python OR language:typescript OR language:javascript",
                        "sort": "updated",
                        "order": "desc",
                        "per_page": 20,
                    },
                )
                response.raise_for_status()

                search_results = response.json()

                for repo in search_results.get("items", []):
                    server_name = repo["name"]
                    if server_name not in servers:
                        server_info = await self._github_repo_to_server_info(repo)
                        if server_info:
                            servers[server_name] = server_info

            except Exception as e:
                logger.warning(f"GitHub search failed for pattern '{pattern}': {e}")

        return servers

    async def _discover_from_curated_list(self) -> Dict[str, MCPServerWithOptions]:
        """Discover servers from our curated list (integrated with installer)."""
        try:
            # Import installer to get server definitions
            from .installer import MCPInstaller

            # Create installer instance to access server definitions
            installer = MCPInstaller()
            curated_servers = {}

            # Convert installer definitions to discovery format
            for category, servers in installer.server_definitions.items():
                for server_key, server_info in servers.items():
                    options = []
                    for option_key, option_info in server_info["options"].items():
                        options.append(
                            MCPServerOption(
                                name=option_key,
                                display_name=option_key.title(),
                                description=f"Curated {option_key} version",
                                install_command=option_info["install"],
                                config_name=option_info["config_name"],
                                env_vars=option_info["env_vars"],
                                recommended=option_key == "official",
                            )
                        )

                    curated_servers[server_key] = MCPServerWithOptions(
                        name=server_key,
                        display_name=server_info["name"],
                        description=server_info["description"],
                        category=self._categorize_server(
                            server_key, server_info["description"]
                        ),
                        keywords=self._extract_keywords(
                            server_key, server_info["description"]
                        ),
                        author="MCP Manager Curated",
                        options=options,
                    )

            logger.info(f"Loaded {len(curated_servers)} curated servers from installer")
            return curated_servers

        except Exception as e:
            logger.warning(f"Failed to load curated servers: {e}")
            return {}

    async def _discover_from_claudelog(self) -> Dict[str, MCPServerWithOptions]:
        """Discover servers from ClaudeLog.com curated lists."""
        servers = {}

        try:
            # Define ClaudeLog curated servers based on research
            claudelog_curated = {
                "brave-search": {
                    "name": "Brave Search MCP",
                    "description": "Web search integration for research and documentation lookup during development",
                    "category": MCPServerCategory.SEARCH,
                    "repository_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/brave-search",
                    "install_command": "npx -y @modelcontextprotocol/server-brave-search",
                    "env_vars": ["BRAVE_API_KEY"],
                    "keywords": ["search", "web", "research", "brave"],
                    "recommended_by": "ClaudeLog",
                },
                "context7": {
                    "name": "Context7 MCP",
                    "description": "Access to development documentation, APIs, and technical references",
                    "category": MCPServerCategory.CONTEXT,
                    "repository_url": "https://github.com/upstash/context7",
                    "install_command": "npx -y @upstash/context7-mcp",
                    "env_vars": ["CONTEXT7_API_KEY"],
                    "keywords": ["documentation", "api", "context", "upstash"],
                    "recommended_by": "ClaudeLog",
                },
                "puppeteer": {
                    "name": "Puppeteer MCP",
                    "description": "Browser automation for testing web applications and scraping data",
                    "category": MCPServerCategory.AUTOMATION,
                    "repository_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/puppeteer",
                    "install_command": "npx -y @modelcontextprotocol/server-puppeteer",
                    "env_vars": [],
                    "keywords": ["browser", "automation", "testing", "scraping"],
                    "recommended_by": "ClaudeLog",
                },
                "reddit-mcp": {
                    "name": "Reddit MCP",
                    "description": "Community insights and troubleshooting from developer discussions",
                    "category": MCPServerCategory.COMMUNICATION,
                    "repository_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/reddit",
                    "install_command": "npx -y @modelcontextprotocol/server-reddit",
                    "env_vars": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"],
                    "keywords": [
                        "reddit",
                        "community",
                        "discussions",
                        "troubleshooting",
                    ],
                    "recommended_by": "ClaudeLog",
                },
                "whatsapp-mcp": {
                    "name": "WhatsApp MCP",
                    "description": "Communication integration for team coordination",
                    "category": MCPServerCategory.COMMUNICATION,
                    "repository_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/whatsapp",
                    "install_command": "npx -y @modelcontextprotocol/server-whatsapp",
                    "env_vars": ["WHATSAPP_API_KEY"],
                    "keywords": ["whatsapp", "communication", "team", "coordination"],
                    "recommended_by": "ClaudeLog",
                },
                "basic-memory": {
                    "name": "Basic Memory MCP",
                    "description": "Innovative AI-human collaboration framework with Model Context Protocol",
                    "category": MCPServerCategory.OTHER,
                    "repository_url": "https://github.com/basic-machines-co/basic-memory",
                    "install_command": "uvx --from git+https://github.com/basic-machines-co/basic-memory basic-memory-mcp",
                    "env_vars": [],
                    "keywords": ["memory", "collaboration", "ai", "framework"],
                    "recommended_by": "Awesome Claude Code",
                },
                "claude-code-enhanced": {
                    "name": "Claude Code MCP Enhanced",
                    "description": "Detailed instructions for Claude to follow as a coding agent",
                    "category": MCPServerCategory.CODING,
                    "repository_url": "https://github.com/grahama1970/claude-code-mcp-enhanced",
                    "install_command": "uvx --from git+https://github.com/grahama1970/claude-code-mcp-enhanced claude-code-enhanced",
                    "env_vars": [],
                    "keywords": ["coding", "agent", "instructions", "enhanced"],
                    "recommended_by": "Awesome Claude Code",
                },
                "perplexity-family": {
                    "name": "Perplexity MCP (Family-IT-Guy)",
                    "description": "Step-by-step installation with multiple configuration options",
                    "category": MCPServerCategory.SEARCH,
                    "repository_url": "https://github.com/Family-IT-Guy/perplexity-mcp",
                    "install_command": "uvx --from git+https://github.com/Family-IT-Guy/perplexity-mcp perplexity-mcp",
                    "env_vars": ["PERPLEXITY_API_KEY"],
                    "keywords": ["perplexity", "search", "ai", "configuration"],
                    "recommended_by": "Awesome Claude Code",
                },
                "playwright-mcp": {
                    "name": "Playwright MCP Server",
                    "description": "Browser automation and testing with Playwright",
                    "category": MCPServerCategory.AUTOMATION,
                    "repository_url": "https://github.com/executeautomation/mcp-playwright",
                    "install_command": "npm install -g @executeautomation/playwright-mcp-server",
                    "env_vars": [],
                    "keywords": ["playwright", "browser", "automation", "testing"],
                    "recommended_by": "Community",
                },
                "testsprite-mcp": {
                    "name": "TestSprite MCP Server",
                    "description": "Automated testing with AI-powered test generation",
                    "category": MCPServerCategory.AUTOMATION,
                    "repository_url": "https://github.com/testsprite/mcp-server",
                    "install_command": "npm install -g @testsprite/mcp-server",
                    "env_vars": ["TESTSPRITE_API_KEY"],
                    "keywords": ["testsprite", "testing", "ai", "automation"],
                    "recommended_by": "Community",
                },
            }

            # Convert to MCPServerWithOptions format
            for server_key, server_data in claudelog_curated.items():
                options = [
                    MCPServerOption(
                        name="claudelog",
                        display_name="ClaudeLog Recommended",
                        description=f"Curated by {server_data['recommended_by']}",
                        install_command=server_data["install_command"],
                        config_name=server_key,
                        env_vars=server_data["env_vars"],
                        repository_url=server_data["repository_url"],
                        recommended=True,
                    )
                ]

                servers[server_key] = MCPServerWithOptions(
                    name=server_key,
                    display_name=server_data["name"],
                    description=server_data["description"],
                    category=server_data["category"],
                    repository_url=server_data["repository_url"],
                    keywords=server_data["keywords"],
                    author="Community Curated",
                    options=options,
                )

            logger.info(f"Discovered {len(servers)} servers from ClaudeLog")

        except Exception as e:
            logger.warning(f"Failed to discover from ClaudeLog: {e}")

        return servers

    def _filter_servers(self, query: MCPSearchQuery) -> List[MCPServerWithOptions]:
        """Filter servers based on search query."""
        servers = list(self.server_cache.values())

        # Filter by category
        if query.category:
            servers = [s for s in servers if s.category == query.category]

        # Filter by keywords
        if query.keywords:
            keyword_set = set(k.lower() for k in query.keywords)
            servers = [
                s
                for s in servers
                if keyword_set.intersection(set(k.lower() for k in s.keywords))
            ]

        # Filter by query text
        if query.query:
            query_lower = query.query.lower()
            servers = [
                s
                for s in servers
                if (
                    query_lower in s.name.lower()
                    or query_lower in s.display_name.lower()
                    or query_lower in s.description.lower()
                    or any(query_lower in k.lower() for k in s.keywords)
                )
            ]

        return servers

    def _sort_servers(
        self, servers: List[MCPServerWithOptions], sort_by: str
    ) -> List[MCPServerWithOptions]:
        """Sort servers by the specified criteria."""
        if sort_by == "name":
            return sorted(servers, key=lambda s: s.name)
        elif sort_by == "stars":
            return sorted(servers, key=lambda s: s.stars or 0, reverse=True)
        elif sort_by == "updated":
            return sorted(
                servers, key=lambda s: s.updated_at or datetime.min, reverse=True
            )
        else:  # relevance (default)
            return servers

    def _extract_description_from_readme(self, readme_content: str) -> str:
        """Extract description from README content."""
        lines = readme_content.split("\n")
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 20:
                return line[:200] + "..." if len(line) > 200 else line
        return "MCP Server"

    def _extract_env_vars_from_readme(self, readme_content: str) -> List[str]:
        """Extract environment variables from README content."""
        env_vars = []
        env_pattern = r"([A-Z_]+_(?:API_)?KEY|[A-Z_]+_TOKEN)"
        matches = re.findall(env_pattern, readme_content)
        return list(set(matches))

    def _categorize_server(self, name: str, description: str) -> MCPServerCategory:
        """Categorize a server based on its name and description."""
        name_lower = name.lower()
        desc_lower = description.lower()

        if any(
            term in name_lower or term in desc_lower
            for term in ["github", "gitlab", "git", "version"]
        ):
            return MCPServerCategory.VERSION_CONTROL
        elif any(
            term in name_lower or term in desc_lower
            for term in ["search", "brave", "google", "perplexity"]
        ):
            return MCPServerCategory.SEARCH
        elif any(
            term in name_lower or term in desc_lower
            for term in ["browser", "puppeteer", "firecrawl", "automation"]
        ):
            return MCPServerCategory.AUTOMATION
        elif any(
            term in name_lower or term in desc_lower
            for term in ["code", "serena", "ide", "coding"]
        ):
            return MCPServerCategory.CODING
        elif any(
            term in name_lower or term in desc_lower
            for term in ["context", "doc", "knowledge"]
        ):
            return MCPServerCategory.CONTEXT
        elif any(
            term in name_lower or term in desc_lower
            for term in ["zen", "router", "orchestr"]
        ):
            return MCPServerCategory.ORCHESTRATION
        else:
            return MCPServerCategory.OTHER

    def _extract_keywords(self, name: str, description: str) -> List[str]:
        """Extract keywords from server name and description."""
        keywords = []

        # Add words from name
        keywords.extend(re.findall(r"\w+", name.lower()))

        # Add important words from description
        important_words = re.findall(
            r"\b(?:api|server|client|tool|integration|search|browser|code|git|database|ai|model|context|protocol)\b",
            description.lower(),
        )
        keywords.extend(important_words)

        return list(set(keywords))

    def _decode_base64_content(self, content: str) -> str:
        """Decode base64 content from GitHub API."""
        import base64

        return base64.b64decode(content).decode("utf-8")

    def _parse_awesome_readme(
        self, readme_content: str, repo: str
    ) -> Dict[str, MCPServerWithOptions]:
        """Parse awesome README content to extract MCP servers."""
        servers = {}

        # Look for GitHub links in the README
        github_pattern = r"https://github\.com/([^/]+)/([^/)\s]+)"
        matches = re.findall(github_pattern, readme_content)

        for owner, repo_name in matches:
            if "mcp" in repo_name.lower():
                server_name = repo_name
                servers[server_name] = MCPServerWithOptions(
                    name=server_name,
                    display_name=server_name.replace("-", " ").title(),
                    description=f"Community MCP server from {owner}",
                    category=self._categorize_server(server_name, ""),
                    repository_url=f"https://github.com/{owner}/{repo_name}",
                    author=owner,
                    keywords=self._extract_keywords(server_name, ""),
                    options=[
                        MCPServerOption(
                            name="community",
                            display_name="Community",
                            install_command=f"uvx --from git+https://github.com/{owner}/{repo_name} {server_name}",
                            config_name=server_name,
                            env_vars=[],
                        )
                    ],
                )

        return servers

    async def _github_repo_to_server_info(
        self, repo: dict
    ) -> Optional[MCPServerWithOptions]:
        """Convert GitHub repository data to server info."""
        try:
            server_name = repo["name"]

            server_info = MCPServerWithOptions(
                name=server_name,
                display_name=server_name.replace("-", " ").title(),
                description=repo.get("description", "MCP Server"),
                category=self._categorize_server(
                    server_name, repo.get("description", "")
                ),
                repository_url=repo["html_url"],
                author=repo["owner"]["login"],
                license=(
                    repo.get("license", {}).get("name") if repo.get("license") else None
                ),
                created_at=datetime.fromisoformat(
                    repo["created_at"].replace("Z", "+00:00")
                ),
                updated_at=datetime.fromisoformat(
                    repo["updated_at"].replace("Z", "+00:00")
                ),
                stars=repo["stargazers_count"],
                forks=repo["forks_count"],
                issues=repo["open_issues_count"],
                keywords=self._extract_keywords(
                    server_name, repo.get("description", "")
                ),
                options=[
                    MCPServerOption(
                        name="github",
                        display_name="GitHub",
                        install_command=f"uvx --from git+{repo['clone_url']} {server_name}",
                        config_name=server_name,
                        env_vars=[],
                        repository_url=repo["html_url"],
                    )
                ],
            )

            return server_info

        except Exception as e:
            logger.warning(f"Failed to convert GitHub repo to server info: {e}")
            return None

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
