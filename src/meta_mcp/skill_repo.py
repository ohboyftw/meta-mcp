"""
Skill Repository Management (R9 extension).

This module enables meta-mcp to discover, index, and install skills and MCP
servers from a local or remote skill repository.

A *skill repository* is a directory containing:

    skill-repo/
    ├── INDEX.md                  # Optional: catalog/documentation
    ├── servers.json              # Optional: MCP server definitions
    └── <skill-name>/
         ├── SKILL.md             # Required: skill definition
         └── (other files)        # Optional: scripts, templates, etc.

The repository can also contain MCP servers co-located with their skills:

    <skill-name>/
    ├── SKILL.md
    ├── mcp_server.py             # MCP server entry point
    └── (other server files)

Discovery order for servers.json:
    1. Root of the repo (servers.json or mcpServers.json)
    2. Any subdirectory named servers.json / mcpServers.json
    3. Any JSON file whose name matches its containing directory
       (e.g. code-graph/code-graph.json)

Usage::

    from meta_mcp.skill_repo import SkillRepo, SkillRepoManager

    # Initialize with your skills repo
    manager = SkillRepoManager()
    manager.add_repo("D:/Home/claudeSkills/repo")

    # List available skills
    repos = manager.list_available_skills()
    for r in repos:
        print(f"{r.name}: {r.description}")

    # Install a skill + its MCP server (if any)
    manager.install_from_repo("code-graph")

    # Batch install from repo
    manager.batch_install(["beacon", "code-graph"], install_servers=True)
"""

import json
import logging
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .models import (
    AgentSkill,
    MCPServerCategory,
    MCPServerOption,
    MCPServerWithOptions,
    SkillScope,
)
from ._parsing import (
    FRONTMATTER_DELIMITER,
    coerce_list,
    normalise_name,
    parse_skill_md,
)

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

GLOBAL_SKILLS_DIR = Path.home() / ".claude" / "skills"
PROJECT_SKILLS_DIR_NAME = ".claude/skills"

# File names that indicate an MCP server definition
_SERVERS_FILENAMES = frozenset({"servers.json", "mcpServers.json", "mcp_servers.json"})


# ─── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class RepoSkillInfo:
    """Metadata for a skill discovered inside a repository."""

    name: str = ""
    description: str = ""
    repo_path: Path = field(default_factory=Path)
    skill_dir: Path = field(default_factory=Path)
    skill_file: Path = field(default_factory=Path)
    has_mcp_server: bool = False
    mcp_server_file: Optional[Path] = None
    mcp_command: Optional[str] = None
    mcp_args: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    required_servers: List[str] = field(default_factory=list)
    source: str = ""

    @property
    def install_source(self) -> str:
        """Return the source path to pass to SkillsManager.install_skill."""
        return str(self.skill_dir)


@dataclass
class RepoServerInfo:
    """An MCP server definition parsed from servers.json in a repo."""

    name: str = ""
    display_name: str = ""
    description: str = ""
    category: MCPServerCategory = MCPServerCategory.OTHER
    repository_url: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    install_command: Optional[str] = None
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env_vars: List[str] = field(default_factory=list)
    skill_name: Optional[str] = None
    repo_path: Path = field(default_factory=Path)

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.name.replace("-", " ").replace("_", " ").title()

    @classmethod
    def from_dict(cls, data: Dict[str, Any], repo_path: Path) -> "RepoServerInfo":
        name = data.get("name", "")
        return cls(
            name=name,
            display_name=name.replace("-", " ").replace("_", " ").title(),
            description=data.get("description", ""),
            category=MCPServerCategory(data.get("category", "other")),
            repository_url=data.get("repository_url"),
            keywords=data.get("keywords", []),
            install_command=data.get("install_command"),
            command=data.get("command"),
            args=data.get("args", []),
            env_vars=data.get("env_vars", []),
            skill_name=data.get("skill_name"),
            repo_path=repo_path,
        )

    def to_mcp_server_with_options(self) -> MCPServerWithOptions:
        """Convert to the discovery-layer model."""
        options: List[MCPServerOption] = []
        if self.install_command:
            options.append(
                MCPServerOption(
                    name="repo",
                    display_name="From Skill Repo",
                    description="Installed from local skill repository",
                    install_command=self.install_command,
                    config_name=self.name,
                    env_vars=self.env_vars,
                    recommended=True,
                )
            )
        elif self.command:
            options.append(
                MCPServerOption(
                    name="repo",
                    display_name="From Skill Repo",
                    description="MCP server from local skill repository",
                    install_command=f"{self.command} {' '.join(self.args)}",
                    config_name=self.name,
                    env_vars=self.env_vars,
                    recommended=True,
                )
            )

        return MCPServerWithOptions(
            name=self.name,
            display_name=self.display_name,
            description=self.description,
            category=self.category,
            repository_url=self.repository_url,
            keywords=self.keywords,
            options=options,
        )


class RepoIndex:
    """Index of all discoverable items in a skill repository."""

    repo_path: Path
    repo_name: str
    skills: List[RepoSkillInfo]
    servers: List[RepoServerInfo]
    index_md_path: Optional[Path]
    servers_json_path: Optional[Path]

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path.resolve()
        self.repo_name = self.repo_path.name
        self.skills = []
        self.servers = []
        self.index_md_path = None
        self.servers_json_path = None

    # ─── Parsing ──────────────────────────────────────────────────────────

    def discover(self) -> "RepoIndex":
        """Scan the repository and populate skills and servers lists."""
        if not self.repo_path.is_dir():
            logger.warning("Repo path does not exist: %s", self.repo_path)
            return self

        self._discover_servers_json()
        self._discover_skill_dirs()
        self._enrich_servers_with_skills()
        self._discover_colocated_servers()

        logger.info(
            "RepoIndex(%s): discovered %d skills, %d servers",
            self.repo_name,
            len(self.skills),
            len(self.servers),
        )
        return self

    def _discover_servers_json(self) -> None:
        """Find servers.json at repo root or in subdirectories."""
        for servers_file in _SERVERS_FILENAMES:
            root_path = self.repo_path / servers_file
            if root_path.is_file():
                self.servers_json_path = root_path
                self._parse_servers_json(root_path)
                return

            # Also check subdirectories
            for child in self.repo_path.iterdir():
                if not child.is_dir():
                    continue
                sub_path = child / servers_file
                if sub_path.is_file():
                    self.servers_json_path = sub_path
                    self._parse_servers_json(sub_path)
                    return

    def _parse_servers_json(self, path: Path) -> None:
        """Parse a servers.json file."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))

            # Support both mcpServers and servers top-level keys
            entries = data.get("mcpServers") or data.get("servers") or {}
            if not isinstance(entries, dict):
                entries = {}

            for name, cfg in entries.items():
                if isinstance(cfg, dict):
                    cfg["name"] = name
                    self.servers.append(RepoServerInfo.from_dict(cfg, self.repo_path))
                elif isinstance(cfg, str):
                    # Simple string form: just the command
                    self.servers.append(
                        RepoServerInfo(
                            name=name,
                            display_name=name.replace("-", " ").title(),
                            description=f"MCP server: {name}",
                            category=MCPServerCategory.OTHER,
                            repository_url=None,
                            keywords=[],
                            install_command=cfg,
                            command=None,
                            args=[],
                            env_vars=[],
                            skill_name=None,
                            repo_path=self.repo_path,
                        )
                    )

            logger.debug("Parsed %d servers from %s", len(entries), path)
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", path, exc)

    def _discover_skill_dirs(self) -> None:
        """Find all directories containing SKILL.md."""
        for child in sorted(self.repo_path.iterdir()):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.is_file():
                continue

            data = parse_skill_md(skill_file)
            if data is None:
                continue

            has_mcp = (child / "mcp_server.py").is_file()

            skill_info = RepoSkillInfo(
                name=data.get("name", child.name),
                description=data.get("description", ""),
                repo_path=self.repo_path,
                skill_dir=child,
                skill_file=skill_file,
                has_mcp_server=has_mcp,
                mcp_server_file=child / "mcp_server.py" if has_mcp else None,
                mcp_command=None,
                mcp_args=[],
                tags=coerce_list(data.get("tags", [])),
                required_servers=coerce_list(data.get("required-servers", [])),
                source=f"repo:{self.repo_name}",
            )

            # Infer MCP server command if co-located
            if has_mcp:
                skill_info.mcp_command, skill_info.mcp_args = _infer_mcp_command(
                    child, skill_info.name
                )

            self.skills.append(skill_info)

    def _enrich_servers_with_skills(self) -> None:
        """For servers parsed from servers.json, enrich them with MCP command
        info from their co-located skill (if any)."""
        skill_map = {s.name: s for s in self.skills}
        for server in self.servers:
            if server.install_command:
                continue  # Already has an install command
            if server.skill_name:
                skill = skill_map.get(server.skill_name)
            else:
                skill = skill_map.get(server.name)
            if skill and skill.has_mcp_server and skill.mcp_command:
                server.command = skill.mcp_command
                server.args = skill.mcp_args or []
                server.install_command = f"{skill.mcp_command} {' '.join(skill.mcp_args or [])}"

    def _discover_colocated_servers(self) -> None:
        """For skills that have mcp_server.py but no servers.json entry,
        create a RepoServerInfo from the skill's metadata."""
        server_names = {s.name for s in self.servers}

        for skill in self.skills:
            if skill.name not in server_names and skill.has_mcp_server:
                cmd, args = skill.mcp_command, skill.mcp_args
                self.servers.append(
                    RepoServerInfo(
                        name=skill.name,
                        display_name=skill.name.replace("-", " ").title(),
                        description=skill.description,
                        category=MCPServerCategory.OTHER,
                        repository_url=None,
                        keywords=skill.tags,
                        install_command=f"{cmd} {' '.join(args)}" if cmd else None,
                        command=cmd,
                        args=args or [],
                        env_vars=[],
                        skill_name=skill.name,
                        repo_path=self.repo_path,
                    )
                )

    # ─── Lookup ───────────────────────────────────────────────────────────

    def get_skill(self, name: str) -> Optional[RepoSkillInfo]:
        """Find a skill by name (fuzzy match on normalised name)."""
        norm = normalise_name(name)
        for s in self.skills:
            if normalise_name(s.name) == norm:
                return s
        # Fallback: substring
        for s in self.skills:
            if norm in normalise_name(s.name) or normalise_name(s.name) in norm:
                return s
        return None

    def get_server(self, name: str) -> Optional[RepoServerInfo]:
        """Find a server definition by name."""
        norm = normalise_name(name)
        for s in self.servers:
            if normalise_name(s.name) == norm:
                return s
        return None


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _infer_mcp_command(skill_dir: Path, skill_name: str) -> tuple:
    """Infer the command to run an mcp_server.py co-located with a skill.

    Returns (command, args) tuple.
    """
    server_file = skill_dir / "mcp_server.py"
    if not server_file.is_file():
        return None, []

    py_cmd = "py" if platform.system() == "Windows" else "python3"
    return py_cmd, [str(server_file)]


# ─── RepoManager ──────────────────────────────────────────────────────────────


class SkillRepoManager:
    """Manages one or more skill repositories.

    Repositories can be added via:
    - A local directory path (``add_repo("/path/to/repo")``)
    - An environment variable (``META_MCP_SKILLS_DIRS``)
    - The config file (``[skills]`` / ``extra_dirs``)

    The manager discovers skills and servers from all registered repos,
    and can install them into the global or project skills directory.
    """

    def __init__(self) -> None:
        from .settings import get_settings

        self._repos: List[RepoIndex] = []
        self._extra_dirs: List[Path] = list(get_settings().skills_extra_dirs)

        # Auto-discover repos from extra_dirs
        for d in self._extra_dirs:
            self.add_repo(str(d))

    # ─── Repo Registration ─────────────────────────────────────────────────

    def add_repo(self, path: str) -> RepoIndex:
        """Register a local skill repository.

        Returns the populated RepoIndex.
        """
        repo_path = Path(path).expanduser().resolve()
        if not repo_path.is_dir():
            logger.warning("Skipping non-existent repo path: %s", repo_path)
            raise ValueError(f"Repository path does not exist: {path}")

        # Avoid duplicates
        for existing in self._repos:
            if existing.repo_path == repo_path:
                logger.debug("Repo already registered: %s", repo_path)
                return existing

        index = RepoIndex(repo_path).discover()
        self._repos.append(index)
        logger.info("Registered skill repo: %s (%d skills, %d servers)", repo_path, len(index.skills), len(index.servers))
        return index

    def remove_repo(self, path: str) -> bool:
        """Deregister a repository by path."""
        repo_path = Path(path).expanduser().resolve()
        self._repos = [r for r in self._repos if r.repo_path != repo_path]
        return True

    # ─── Discovery ────────────────────────────────────────────────────────

    def list_available_skills(self) -> List[RepoSkillInfo]:
        """Return all discoverable skills across all registered repos."""
        skills: List[RepoSkillInfo] = []
        for repo in self._repos:
            skills.extend(repo.skills)
        return skills

    def list_available_servers(self) -> List[RepoServerInfo]:
        """Return all discoverable MCP servers across all registered repos."""
        servers: List[RepoServerInfo] = []
        for repo in self._repos:
            servers.extend(repo.servers)
        return servers

    def search_skills(self, intent: str) -> List[RepoSkillInfo]:
        """Search skills by intent (name/description/tag match)."""
        intent_lower = intent.lower().strip()
        if not intent_lower:
            return []

        results: List[tuple] = []
        for repo in self._repos:
            for skill in repo.skills:
                score = 0
                name_lower = skill.name.lower()
                desc_lower = skill.description.lower()

                if intent_lower in name_lower:
                    score += 50
                if intent_lower in desc_lower:
                    score += 30
                for tag in skill.tags:
                    if intent_lower in tag.lower():
                        score += 15

                for word in intent_lower.split():
                    if len(word) < 3:
                        continue
                    if word in name_lower:
                        score += 10
                    if word in desc_lower:
                        score += 5

                if score > 0:
                    results.append((score, skill))

        results.sort(key=lambda t: t[0], reverse=True)
        return [s for _, s in results]

    def search_servers(self, intent: str) -> List[RepoServerInfo]:
        """Search servers by intent."""
        intent_lower = intent.lower().strip()
        if not intent_lower:
            return []

        results: List[tuple] = []
        for repo in self._repos:
            for server in repo.servers:
                score = 0
                name_lower = server.name.lower()
                desc_lower = server.description.lower()

                if intent_lower in name_lower:
                    score += 50
                if intent_lower in desc_lower:
                    score += 30
                for kw in server.keywords:
                    if intent_lower in kw.lower():
                        score += 15

                if score > 0:
                    results.append((score, server))

        results.sort(key=lambda t: t[0], reverse=True)
        return [s for _, s in results]

    def get_skill(self, name: str) -> Optional[RepoSkillInfo]:
        """Find a skill by name across all repos."""
        for repo in self._repos:
            found = repo.get_skill(name)
            if found:
                return found
        return None

    def get_server(self, name: str) -> Optional[RepoServerInfo]:
        """Find a server by name across all repos."""
        for repo in self._repos:
            found = repo.get_server(name)
            if found:
                return found
        return None

    # ─── Installation ─────────────────────────────────────────────────────

    def _do_install_skill(
        self,
        name: str,
        scope: SkillScope = SkillScope.PROJECT,
        install_server: bool = True,
    ) -> tuple[bool, str]:
        """Internal install returning (success, message)."""
        skill = self.get_skill(name)
        if skill is None:
            return False, f"Skill '{name}' not found in any registered repository."

        try:
            from .skills import SkillsManager

            sm = SkillsManager()
            sm.install_skill(
                name=skill.name,
                source=skill.install_source,
                scope=scope,
            )
        except Exception as exc:
            logger.error("Failed to install skill %s: %s", name, exc)
            return False, f"Failed to install skill '{name}': {exc}"

        messages = [f"Installed skill '{skill.name}' from {skill.repo_path}"]

        if install_server and skill.has_mcp_server:
            server_msg = self._install_mcp_server_for_skill(skill)
            messages.append(server_msg)

        return True, "\n".join(messages)

    def install_skill(
        self,
        name: str,
        scope: SkillScope = SkillScope.PROJECT,
        install_server: bool = True,
    ) -> str:
        """Install a skill from a registered repo. Returns human-readable status."""
        _ok, msg = self._do_install_skill(name, scope=scope, install_server=install_server)
        return msg

    def _install_mcp_server_for_skill(self, skill: RepoSkillInfo) -> str:
        """Install the MCP server co-located with a skill."""
        if not skill.has_mcp_server or not skill.mcp_server_file:
            return ""

        from .installer import MCPInstaller

        installer = MCPInstaller()

        # Create an installation request
        from .models import MCPInstallationRequest

        request = MCPInstallationRequest(
            server_name=skill.name,
            option_name="repo",
            source_path=str(skill.skill_dir),
            auto_configure=True,
        )

        try:
            from .tools import run_async_safely

            result = run_async_safely(installer.install_server(request))
            if result.success:
                return f"Installed MCP server '{skill.name}' (command: {skill.mcp_command})"
            else:
                return f"MCP server '{skill.name}' install failed: {result.message}"
        except Exception as exc:
            return f"MCP server install error: {exc}"

    def install_server(
        self,
        name: str,
        auto_configure: bool = True,
    ) -> str:
        """Install an MCP server defined in a registered repo's servers.json."""
        server = self.get_server(name)
        if server is None:
            return f"Server '{name}' not found in any registered repository."

        from .installer import MCPInstaller
        from .models import MCPInstallationRequest

        installer = MCPInstaller()

        request = MCPInstallationRequest(
            server_name=server.name,
            option_name="repo",
            source_path=None,
            env_vars={var: f"<YOUR_{var}>" for var in server.env_vars},
            auto_configure=auto_configure,
        )

        try:
            from .tools import run_async_safely

            result = run_async_safely(installer.install_server(request))
            if result.success:
                return f"Installed server '{server.name}': {result.message}"
            else:
                return f"Server '{server.name}' install failed: {result.message}"
        except Exception as exc:
            return f"Server install error: {exc}"

    def batch_install(
        self,
        names: List[str],
        scope: SkillScope = SkillScope.PROJECT,
        install_servers: bool = True,
    ) -> str:
        """Install multiple skills (and their MCP servers) in one call.

        Names that don't match a known skill are skipped with a warning.
        """
        results: List[str] = []
        succeeded: List[str] = []
        failed: List[str] = []

        for name in names:
            ok, msg = self._do_install_skill(name, scope=scope, install_server=install_servers)
            if ok:
                succeeded.append(name)
                results.append(f"[OK] {name}")
            else:
                failed.append(name)
                results.append(f"[FAIL] {name}: {msg}")

        lines = [
            f"# Batch Install Results ({len(succeeded)}/{len(names)} succeeded)",
            "",
        ]
        lines.extend(results)
        if failed:
            lines.append("")
            lines.append(f"**Failed:** {', '.join(failed)}")
            lines.append("Tip: Use `search_repo` to find available skills and servers.")

        return "\n".join(lines)

    # ─── Reporting ─────────────────────────────────────────────────────────

    def list_repos(self) -> List[Dict[str, Any]]:
        """Return a summary of all registered repositories."""
        return [
            {
                "name": r.repo_name,
                "path": str(r.repo_path),
                "skills_count": len(r.skills),
                "servers_count": len(r.servers),
            }
            for r in self._repos
        ]

    def full_catalog(self) -> Dict[str, Any]:
        """Return a complete catalog of all repos, skills, and servers."""
        return {
            "repos": self.list_repos(),
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "repo": s.repo_path.name,
                    "has_mcp_server": s.has_mcp_server,
                    "tags": s.tags,
                }
                for s in self.list_available_skills()
            ],
            "servers": [
                {
                    "name": s.name,
                    "description": s.description,
                    "repo": s.repo_path.name,
                    "category": s.category.value,
                    "install_command": s.install_command,
                }
                for s in self.list_available_servers()
            ],
        }
