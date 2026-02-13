"""
R4: Project Context Awareness.

Scans a project directory to detect language, framework, services, VCS, CI/CD,
Docker usage, existing MCP configuration, and AGENTS.md presence. Based on the
detected context, recommends relevant MCP servers for the project.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    ProjectContext,
    ContextualRecommendation,
    ProjectAnalysisResult,
    MCPServerCategory,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env-var masking helper
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE
)


def _mask_value(value: str) -> str:
    """Mask a potentially sensitive value, keeping only the first four characters."""
    if len(value) <= 4:
        return "****"
    return value[:4] + "****"


# ---------------------------------------------------------------------------
# Safe file-reading helpers
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> Optional[str]:
    """Read a text file, returning ``None`` on any failure."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.debug("Could not read %s: %s", path, exc)
        return None


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    """Read and parse a JSON file, returning ``None`` on any failure."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.debug("Could not parse JSON %s: %s", path, exc)
        return None


def _read_yaml(path: Path) -> Optional[Any]:
    """Read and parse a YAML file, returning ``None`` on any failure."""
    try:
        import yaml  # optional dependency – graceful fallback

        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except ImportError:
        logger.debug("PyYAML not installed; skipping YAML parsing for %s", path)
        return None
    except Exception as exc:
        logger.debug("Could not parse YAML %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# ProjectAnalyzer
# ---------------------------------------------------------------------------


class ProjectAnalyzer:
    """Analyze a project directory and produce context-aware recommendations."""

    def __init__(self) -> None:
        # Mapping of marker files -> language identifier
        self._language_markers: List[Tuple[str, str]] = [
            ("package.json", "node"),
            ("tsconfig.json", "typescript"),
            ("pyproject.toml", "python"),
            ("setup.py", "python"),
            ("setup.cfg", "python"),
            ("requirements.txt", "python"),
            ("Pipfile", "python"),
            ("Cargo.toml", "rust"),
            ("go.mod", "go"),
            ("pom.xml", "java"),
            ("build.gradle", "java"),
            ("build.gradle.kts", "kotlin"),
            ("Gemfile", "ruby"),
            ("mix.exs", "elixir"),
            ("composer.json", "php"),
            ("pubspec.yaml", "dart"),
        ]

        # Patterns to detect frameworks inside package.json dependencies
        self._node_framework_markers: Dict[str, str] = {
            "react": "react",
            "next": "next",
            "nuxt": "nuxt",
            "vue": "vue",
            "angular": "angular",
            "express": "express",
            "fastify": "fastify",
            "svelte": "svelte",
            "nest": "nestjs",
            "remix": "remix",
        }

        # Patterns to detect Python frameworks inside pyproject.toml / requirements
        self._python_framework_markers: Dict[str, str] = {
            "fastapi": "fastapi",
            "django": "django",
            "flask": "flask",
            "starlette": "starlette",
            "tornado": "tornado",
            "sanic": "sanic",
            "pyramid": "pyramid",
            "aiohttp": "aiohttp",
        }

        # Docker-compose service names -> canonical service name
        self._service_markers: Dict[str, str] = {
            "postgres": "postgres",
            "postgresql": "postgres",
            "pg": "postgres",
            "redis": "redis",
            "mongo": "mongodb",
            "mongodb": "mongodb",
            "mysql": "mysql",
            "mariadb": "mariadb",
            "rabbitmq": "rabbitmq",
            "elasticsearch": "elasticsearch",
            "opensearch": "opensearch",
            "kafka": "kafka",
            "minio": "minio",
            "memcached": "memcached",
            "dynamodb": "dynamodb",
            "cassandra": "cassandra",
            "neo4j": "neo4j",
            "clickhouse": "clickhouse",
        }

        # Env-var URL patterns -> service name
        self._env_service_markers: Dict[str, str] = {
            "DATABASE_URL": "postgres",
            "POSTGRES_URL": "postgres",
            "PGHOST": "postgres",
            "REDIS_URL": "redis",
            "REDIS_HOST": "redis",
            "MONGO_URL": "mongodb",
            "MONGODB_URI": "mongodb",
            "MYSQL_HOST": "mysql",
            "RABBITMQ_URL": "rabbitmq",
            "ELASTICSEARCH_URL": "elasticsearch",
            "KAFKA_BROKERS": "kafka",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_project(self, path: str) -> ProjectAnalysisResult:
        """Scan *path* and return a full project analysis with recommendations."""
        root = Path(path).resolve()
        if not root.is_dir():
            logger.warning("Path is not a directory: %s", root)
            return ProjectAnalysisResult(
                project=ProjectContext(project_root=str(root)),
                recommendations=[],
                agents_md=None,
                one_command_setup="Directory not found.",
            )

        logger.info("Analyzing project at %s", root)

        language = self._detect_language(root)
        framework = self._detect_framework(root, language)
        services = self._detect_services(root)
        vcs, vcs_provider = self._detect_vcs(root)
        ci_cd = self._detect_ci_cd(root)
        has_docker = self._detect_docker(root)
        has_mcp_config = (root / ".mcp.json").is_file()
        env_vars = self._detect_env_vars(root)
        agents_md = self._read_agents_md(root)

        context = ProjectContext(
            language=language,
            framework=framework,
            services=services,
            vcs=vcs,
            ci_cd=ci_cd,
            has_docker=has_docker,
            has_mcp_config=has_mcp_config,
            detected_env_vars=env_vars,
            project_root=str(root),
        )

        recommendations = self.get_contextual_recommendations(context, vcs_provider)
        one_cmd = self._build_one_command_setup(context, recommendations)

        logger.info(
            "Analysis complete: lang=%s framework=%s services=%s vcs=%s ci=%s docker=%s recs=%d",
            language,
            framework,
            services,
            vcs,
            ci_cd,
            has_docker,
            len(recommendations),
        )

        return ProjectAnalysisResult(
            project=context,
            recommendations=recommendations,
            agents_md=agents_md,
            one_command_setup=one_cmd,
        )

    def get_contextual_recommendations(
        self,
        context: ProjectContext,
        vcs_provider: Optional[str] = None,
    ) -> List[ContextualRecommendation]:
        """Map a ``ProjectContext`` to a ranked list of recommended MCP servers."""
        recs: List[ContextualRecommendation] = []

        # --- Language / framework recommendations ---
        if context.language in ("python", "node", "typescript", "rust", "go", "java"):
            recs.append(
                ContextualRecommendation(
                    server="serena",
                    reason=f"Code-intelligence server for {context.language} projects",
                    priority="high",
                    category=MCPServerCategory.CODING,
                )
            )
            recs.append(
                ContextualRecommendation(
                    server="context7",
                    reason=f"Documentation and API context for {context.language} development",
                    priority="high",
                    category=MCPServerCategory.CONTEXT,
                )
            )

        # --- VCS recommendations ---
        if vcs_provider == "github" or context.vcs == "git":
            recs.append(
                ContextualRecommendation(
                    server="github",
                    reason="GitHub integration for issues, PRs, and repository management",
                    priority="high" if vcs_provider == "github" else "medium",
                    category=MCPServerCategory.VERSION_CONTROL,
                )
            )

        if vcs_provider == "gitlab":
            recs.append(
                ContextualRecommendation(
                    server="gitlab",
                    reason="GitLab integration for issues, merge requests, and CI pipelines",
                    priority="high",
                    category=MCPServerCategory.VERSION_CONTROL,
                )
            )

        if vcs_provider == "bitbucket":
            recs.append(
                ContextualRecommendation(
                    server="bitbucket",
                    reason="Bitbucket integration for repository and pipeline management",
                    priority="medium",
                    category=MCPServerCategory.VERSION_CONTROL,
                )
            )

        # --- Service-specific recommendations ---
        for svc in context.services:
            if svc == "postgres":
                recs.append(
                    ContextualRecommendation(
                        server="server-postgres",
                        reason="Direct PostgreSQL access for queries and schema inspection",
                        priority="high",
                        category=MCPServerCategory.DATABASE,
                    )
                )
            elif svc == "mysql":
                recs.append(
                    ContextualRecommendation(
                        server="server-mysql",
                        reason="Direct MySQL access for queries and schema inspection",
                        priority="high",
                        category=MCPServerCategory.DATABASE,
                    )
                )
            elif svc == "mongodb":
                recs.append(
                    ContextualRecommendation(
                        server="server-mongodb",
                        reason="MongoDB integration for document queries and collection management",
                        priority="high",
                        category=MCPServerCategory.DATABASE,
                    )
                )
            elif svc == "redis":
                # No dedicated Redis MCP server yet; note it for awareness
                logger.info("Redis detected but no dedicated MCP server available yet")
            elif svc == "elasticsearch":
                recs.append(
                    ContextualRecommendation(
                        server="server-elasticsearch",
                        reason="Elasticsearch integration for index and query management",
                        priority="medium",
                        category=MCPServerCategory.DATABASE,
                    )
                )

        # --- Docker recommendations ---
        if context.has_docker:
            recs.append(
                ContextualRecommendation(
                    server="desktop-commander",
                    reason="Container management and command execution for Docker-based workflows",
                    priority="medium",
                    category=MCPServerCategory.AUTOMATION,
                )
            )

        # --- CI/CD recommendations ---
        if context.ci_cd:
            if context.ci_cd in ("github_actions", "github-actions"):
                recs.append(
                    ContextualRecommendation(
                        server="github",
                        reason="GitHub Actions CI/CD workflow management",
                        priority="medium",
                        category=MCPServerCategory.VERSION_CONTROL,
                    )
                )
            elif context.ci_cd == "gitlab_ci":
                recs.append(
                    ContextualRecommendation(
                        server="gitlab",
                        reason="GitLab CI pipeline management",
                        priority="medium",
                        category=MCPServerCategory.VERSION_CONTROL,
                    )
                )

        # --- Always-useful recommendations ---
        recs.append(
            ContextualRecommendation(
                server="brave-search",
                reason="Web search for documentation, error resolution, and research",
                priority="medium",
                category=MCPServerCategory.SEARCH,
            )
        )

        # De-duplicate by server name, keeping the highest-priority entry
        return self._deduplicate_recommendations(recs)

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _detect_language(self, root: Path) -> Optional[str]:
        """Return the primary language identifier or ``None``."""
        for marker, lang in self._language_markers:
            if (root / marker).is_file():
                logger.debug("Language marker found: %s -> %s", marker, lang)
                # Prefer typescript over plain node when tsconfig exists
                if lang == "node" and (root / "tsconfig.json").is_file():
                    return "typescript"
                return lang
        return None

    def _detect_framework(self, root: Path, language: Optional[str]) -> Optional[str]:
        """Detect the primary framework from dependency files."""
        if language in ("node", "typescript"):
            return self._detect_node_framework(root)
        if language == "python":
            return self._detect_python_framework(root)
        return None

    def _detect_node_framework(self, root: Path) -> Optional[str]:
        """Inspect package.json for known frameworks."""
        pkg = _read_json(root / "package.json")
        if not pkg:
            return None

        all_deps: Dict[str, str] = {}
        all_deps.update(pkg.get("dependencies", {}))
        all_deps.update(pkg.get("devDependencies", {}))

        for dep_prefix, framework_name in self._node_framework_markers.items():
            for dep_key in all_deps:
                if dep_key == dep_prefix or dep_key.startswith(f"@{dep_prefix}/"):
                    logger.debug("Node framework detected via dep %s: %s", dep_key, framework_name)
                    return framework_name
        return None

    def _detect_python_framework(self, root: Path) -> Optional[str]:
        """Inspect Python dependency files for known frameworks."""
        # Gather dependency text from multiple sources
        sources: List[str] = []

        req_txt = _read_text(root / "requirements.txt")
        if req_txt:
            sources.append(req_txt)

        pyproject = _read_text(root / "pyproject.toml")
        if pyproject:
            sources.append(pyproject)

        pipfile = _read_text(root / "Pipfile")
        if pipfile:
            sources.append(pipfile)

        setup_py = _read_text(root / "setup.py")
        if setup_py:
            sources.append(setup_py)

        combined = "\n".join(sources).lower()

        for marker, framework_name in self._python_framework_markers.items():
            if marker in combined:
                logger.debug("Python framework detected: %s", framework_name)
                return framework_name
        return None

    def _detect_services(self, root: Path) -> List[str]:
        """Detect external services from docker-compose and env files."""
        services: List[str] = []
        seen: set = set()

        # --- docker-compose ---
        for compose_name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
            compose_data = _read_yaml(root / compose_name)
            if compose_data and isinstance(compose_data, dict):
                svc_section = compose_data.get("services", {})
                if isinstance(svc_section, dict):
                    for svc_name, svc_def in svc_section.items():
                        canonical = self._match_service_name(svc_name)
                        if canonical and canonical not in seen:
                            services.append(canonical)
                            seen.add(canonical)
                        # Also check the image field
                        if isinstance(svc_def, dict):
                            image = svc_def.get("image", "")
                            if isinstance(image, str):
                                canonical = self._match_service_name(image.split(":")[0].split("/")[-1])
                                if canonical and canonical not in seen:
                                    services.append(canonical)
                                    seen.add(canonical)

        # --- Environment variable files ---
        env_vars = self._scan_env_files(root)
        for var_name in env_vars:
            canonical = self._env_service_markers.get(var_name.upper())
            if canonical and canonical not in seen:
                services.append(canonical)
                seen.add(canonical)

        return services

    def _match_service_name(self, name: str) -> Optional[str]:
        """Return a canonical service name if *name* matches a known service."""
        name_lower = name.lower()
        for marker, canonical in self._service_markers.items():
            if marker in name_lower:
                return canonical
        return None

    def _detect_vcs(self, root: Path) -> Tuple[Optional[str], Optional[str]]:
        """Return (vcs_type, provider) e.g. ('git', 'github')."""
        if not (root / ".git").exists():
            return None, None

        provider: Optional[str] = None

        # Try to parse remote URL from .git/config
        git_config_path = root / ".git" / "config"
        content = _read_text(git_config_path)
        if content:
            remote_match = re.search(
                r'url\s*=\s*(?:https?://|git@)([^/:\s]+)', content
            )
            if remote_match:
                host = remote_match.group(1).lower()
                if "github" in host:
                    provider = "github"
                elif "gitlab" in host:
                    provider = "gitlab"
                elif "bitbucket" in host:
                    provider = "bitbucket"
                else:
                    provider = host

        return "git", provider

    def _detect_ci_cd(self, root: Path) -> Optional[str]:
        """Detect CI/CD system in use."""
        if (root / ".github" / "workflows").is_dir():
            return "github_actions"
        if (root / ".gitlab-ci.yml").is_file():
            return "gitlab_ci"
        if (root / "Jenkinsfile").is_file():
            return "jenkins"
        if (root / ".circleci").is_dir():
            return "circleci"
        if (root / ".travis.yml").is_file():
            return "travis"
        if (root / "azure-pipelines.yml").is_file():
            return "azure_devops"
        if (root / "bitbucket-pipelines.yml").is_file():
            return "bitbucket_pipelines"
        return None

    def _detect_docker(self, root: Path) -> bool:
        """Return ``True`` if Docker files are present."""
        docker_files = [
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
            ".dockerignore",
        ]
        return any((root / f).is_file() for f in docker_files)

    def _detect_env_vars(self, root: Path) -> Dict[str, str]:
        """Scan env files and return detected variables with masked values."""
        env_vars: Dict[str, str] = {}
        raw = self._scan_env_files(root)

        for key, value in raw.items():
            if _SENSITIVE_PATTERNS.search(key):
                env_vars[key] = _mask_value(value)
            else:
                env_vars[key] = value

        return env_vars

    def _scan_env_files(self, root: Path) -> Dict[str, str]:
        """Parse .env-style files and return raw key-value pairs."""
        result: Dict[str, str] = {}
        env_files = [".env", ".env.local", ".env.development", ".env.example"]

        for env_name in env_files:
            content = _read_text(root / env_name)
            if not content:
                continue
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key:
                        result[key] = value

        return result

    def _read_agents_md(self, root: Path) -> Optional[str]:
        """Return the contents of AGENTS.md if it exists."""
        for name in ("AGENTS.md", "agents.md", "AGENTS.MD"):
            content = _read_text(root / name)
            if content is not None:
                logger.debug("Found %s", name)
                return content
        return None

    # ------------------------------------------------------------------
    # Recommendation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate_recommendations(
        recs: List[ContextualRecommendation],
    ) -> List[ContextualRecommendation]:
        """Remove duplicate server entries, keeping the highest-priority one."""
        priority_order = {"high": 0, "medium": 1, "low": 2}
        best: Dict[str, ContextualRecommendation] = {}

        for rec in recs:
            existing = best.get(rec.server)
            if existing is None:
                best[rec.server] = rec
            else:
                if priority_order.get(rec.priority, 2) < priority_order.get(
                    existing.priority, 2
                ):
                    best[rec.server] = rec

        # Sort: high first, then medium, then low
        result = sorted(
            best.values(), key=lambda r: priority_order.get(r.priority, 2)
        )
        return result

    @staticmethod
    def _build_one_command_setup(
        context: ProjectContext,
        recommendations: List[ContextualRecommendation],
    ) -> str:
        """Build a human-readable summary of recommended actions."""
        if not recommendations:
            return "No specific MCP servers recommended for this project."

        high = [r for r in recommendations if r.priority == "high"]
        medium = [r for r in recommendations if r.priority == "medium"]

        parts: List[str] = []
        if high:
            names = ", ".join(r.server for r in high)
            parts.append(f"Install priority servers: {names}")
        if medium:
            names = ", ".join(r.server for r in medium)
            parts.append(f"Also recommended: {names}")

        if context.has_mcp_config:
            parts.append("Existing .mcp.json detected -- review before overwriting.")

        return " | ".join(parts)
