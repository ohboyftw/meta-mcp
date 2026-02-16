"""
Agent Skills and Capability Stack Management (R9).

This module handles discovering, installing, managing, and analyzing agent skills
(SKILL.md files) for Claude Code. Skills extend agent capabilities beyond raw
MCP tools by encoding reusable workflows, procedures, and domain knowledge.

Skill directories:
  - Global:  ~/.claude/skills/
  - Project: .claude/skills/ (relative to project root)
"""

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import yaml

from .models import (
    AgentSkill,
    CapabilitySearchResult,
    GeneratedSkill,
    MCPPrompt,
    SkillListResult,
    SkillScope,
    SkillSearchResult,
    SkillTrustResult,
)

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

GLOBAL_SKILLS_DIR = Path.home() / ".claude" / "skills"
PROJECT_SKILLS_DIR_NAME = ".claude/skills"

# Extra skill directories via environment variable (path-separator-delimited).
# Example: META_MCP_SKILLS_DIRS=D:/Home/claudeSkills;D:/Home/other-skills
EXTRA_SKILLS_ENV_VAR = "META_MCP_SKILLS_DIRS"

FRONTMATTER_DELIMITER = "---"

# Dangerous patterns used during skill trust analysis.  Each entry is a tuple
# of (compiled regex, human-readable description, severity weight 0-30).
_DANGEROUS_PATTERNS: List[tuple] = [
    (
        re.compile(r"ignore\s+(all\s+)?(previous|prior|system)\s+(instructions|prompts)", re.IGNORECASE),
        "Attempts to override system prompts",
        30,
    ),
    (
        re.compile(r"(disregard|forget)\s+(everything|all|any)\s+(above|before|prior)", re.IGNORECASE),
        "Attempts to disregard prior context",
        30,
    ),
    (
        re.compile(r"base64[._\-]?(decode|encode)|atob\s*\(|btoa\s*\(", re.IGNORECASE),
        "Contains encoded/obfuscated content references",
        20,
    ),
    (
        re.compile(r"eval\s*\(|exec\s*\(|os\.system\s*\(|subprocess\.", re.IGNORECASE),
        "References direct code execution primitives",
        25,
    ),
    (
        re.compile(r"curl\s+.*\|\s*(ba)?sh", re.IGNORECASE),
        "Pipe-to-shell download pattern",
        25,
    ),
    (
        re.compile(r"rm\s+-rf\s+[/~]", re.IGNORECASE),
        "Destructive filesystem command",
        20,
    ),
    (
        re.compile(r"(password|secret|token|api.key)\s*[:=]", re.IGNORECASE),
        "Hard-coded credential pattern",
        15,
    ),
    (
        re.compile(r"<script|javascript:", re.IGNORECASE),
        "Embedded script content",
        20,
    ),
]

# Official / well-known skill sources treated as higher-trust origins.
_OFFICIAL_SOURCES = frozenset({
    "anthropic",
    "anthropics",
    "modelcontextprotocol",
})

# ─── Built-in Skill Registry ─────────────────────────────────────────────────
# A curated, hard-coded knowledge base of popular skills.  This acts as the
# canonical search index when no remote registry is available.

_BUILTIN_SKILL_REGISTRY: List[Dict[str, Any]] = [
    {
        "name": "anthropics/skills/code-review",
        "description": "Structured code review procedure with checklist-driven analysis",
        "provides": "Automated code review with security, performance, and style checks",
        "source": "anthropic_official",
        "trust_score": 95,
        "tags": ["code-review", "quality", "security"],
    },
    {
        "name": "anthropics/skills/create-document",
        "description": "Document creation skill for technical writing and documentation",
        "provides": "Structured document generation with templates and formatting",
        "source": "anthropic_official",
        "trust_score": 95,
        "tags": ["documentation", "writing", "templates"],
    },
    {
        "name": "engineering-workflow-plugin",
        "description": "Full software development workflow from planning to deployment",
        "provides": "End-to-end engineering workflow: plan, implement, test, deploy",
        "source": "community",
        "trust_score": 72,
        "tags": ["engineering", "workflow", "devops", "planning"],
    },
    {
        "name": "database-query-optimization",
        "description": "SQL query analysis and optimisation with index recommendations",
        "provides": "Database query optimization, EXPLAIN analysis, and index suggestions",
        "source": "community",
        "trust_score": 68,
        "tags": ["database", "sql", "optimization", "performance"],
    },
    {
        "name": "competitive-research",
        "description": "Market research workflow combining search and analysis",
        "provides": "Competitive research pipeline: gather, analyze, summarize market data",
        "source": "community",
        "trust_score": 65,
        "tags": ["research", "market", "analysis", "competitive"],
    },
]

# Intent-to-category mapping used by search_skills to broaden matches.
_INTENT_CATEGORY_MAP: Dict[str, List[str]] = {
    "review": ["code-review", "quality", "security"],
    "code review": ["code-review", "quality", "security"],
    "document": ["documentation", "writing", "templates"],
    "write": ["documentation", "writing", "templates"],
    "workflow": ["engineering", "workflow", "devops", "planning"],
    "develop": ["engineering", "workflow", "devops"],
    "database": ["database", "sql", "optimization"],
    "sql": ["database", "sql", "optimization"],
    "optimize": ["optimization", "performance", "database"],
    "research": ["research", "market", "analysis", "competitive"],
    "market": ["research", "market", "competitive"],
    "deploy": ["devops", "workflow", "engineering"],
    "test": ["testing", "quality", "engineering"],
    "security": ["security", "code-review", "quality"],
}

# Known prompt patterns for common MCP servers (used by discover_prompts).
_KNOWN_SERVER_PROMPTS: Dict[str, List[Dict[str, Any]]] = {
    "github": [
        {
            "name": "github-pr-review",
            "description": "Review a GitHub pull request",
            "arguments": ["owner", "repo", "pull_number"],
        },
        {
            "name": "github-issue-triage",
            "description": "Triage and label a GitHub issue",
            "arguments": ["owner", "repo", "issue_number"],
        },
    ],
    "postgres": [
        {
            "name": "postgres-query",
            "description": "Execute a read-only SQL query",
            "arguments": ["query"],
        },
    ],
    "brave-search": [
        {
            "name": "brave-web-search",
            "description": "Search the web via Brave Search API",
            "arguments": ["query", "count"],
        },
    ],
    "filesystem": [
        {
            "name": "fs-read-file",
            "description": "Read a file from the allowed directory",
            "arguments": ["path"],
        },
    ],
    "puppeteer": [
        {
            "name": "puppeteer-navigate",
            "description": "Navigate to a URL in the browser",
            "arguments": ["url"],
        },
        {
            "name": "puppeteer-screenshot",
            "description": "Take a screenshot of the current page",
            "arguments": [],
        },
    ],
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_skill_md(path: Path) -> Optional[Dict[str, Any]]:
    """Parse a SKILL.md file, returning frontmatter dict and body text.

    Returns ``None`` when the file cannot be read or parsed.  The returned
    dict always contains at minimum ``_body`` (the markdown below the
    frontmatter) and ``_path`` (the resolved file path).
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot read skill file %s: %s", path, exc)
        return None

    frontmatter: Dict[str, Any] = {}
    body = content

    stripped = content.strip()
    if stripped.startswith(FRONTMATTER_DELIMITER):
        parts = stripped.split(FRONTMATTER_DELIMITER, 2)
        # parts[0] is empty string before first ---, parts[1] is YAML, parts[2] is body
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError as exc:
                logger.warning("Invalid YAML frontmatter in %s: %s", path, exc)
                frontmatter = {}
            body = parts[2].strip()

    frontmatter["_body"] = body
    frontmatter["_path"] = str(path.resolve())
    return frontmatter


def _coerce_list(value: Any) -> List[str]:
    """Coerce a value to a list of strings (handles comma-separated strings)."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _skill_from_frontmatter(data: Dict[str, Any], scope: SkillScope) -> AgentSkill:
    """Build an ``AgentSkill`` model from parsed frontmatter."""
    return AgentSkill(
        name=data.get("name", Path(data.get("_path", "unknown")).parent.name),
        description=data.get("description", ""),
        path=data.get("_path"),
        source=data.get("source", "local"),
        version=data.get("version"),
        auto_invocation=not data.get("disable-model-invocation", False),
        allowed_tools=_coerce_list(data.get("allowed-tools", [])),
        scope=scope,
        required_servers=_coerce_list(data.get("required-servers", [])),
        tags=_coerce_list(data.get("tags", [])),
    )


def _resolve_project_skills_dir(project_path: Optional[str] = None) -> Path:
    """Return the project-level skills directory."""
    root = Path(project_path) if project_path else Path.cwd()
    return root / PROJECT_SKILLS_DIR_NAME


def _resolve_extra_skills_dirs() -> List[Path]:
    """Return extra skill directories from Settings (config file + env var).

    The ``META_MCP_SKILLS_DIRS`` env var overrides the config file value
    when set.  See :mod:`meta_mcp.settings` for details.
    """
    from .settings import get_settings

    return list(get_settings().skills_extra_dirs)


def _generate_frontmatter(
    name: str,
    description: str,
    version: str = "1.0.0",
    disable_model_invocation: bool = False,
    allowed_tools: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    required_servers: Optional[List[str]] = None,
) -> str:
    """Render YAML frontmatter block for a SKILL.md file."""
    meta: Dict[str, Any] = {
        "name": name,
        "description": description,
        "version": version,
        "disable-model-invocation": disable_model_invocation,
    }
    if allowed_tools:
        meta["allowed-tools"] = allowed_tools
    if tags:
        meta["tags"] = tags
    if required_servers:
        meta["required-servers"] = required_servers

    yaml_block = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
    return f"{FRONTMATTER_DELIMITER}\n{yaml_block}\n{FRONTMATTER_DELIMITER}"


# ─── SkillsManager ───────────────────────────────────────────────────────────

class SkillsManager:
    """Manages agent skills across global and project scopes.

    Provides search, install, uninstall, update, trust analysis, and
    workflow-to-skill generation capabilities.
    """

    def __init__(self, project_path: Optional[str] = None) -> None:
        self.project_path = project_path
        self.global_dir = GLOBAL_SKILLS_DIR
        self.project_dir = _resolve_project_skills_dir(project_path)
        self.extra_dirs = _resolve_extra_skills_dirs()
        logger.debug(
            "SkillsManager initialised: global=%s  project=%s  extra=%s",
            self.global_dir,
            self.project_dir,
            [str(d) for d in self.extra_dirs],
        )

    # ── Search ────────────────────────────────────────────────────────────

    def search_skills(self, intent: str) -> List[SkillSearchResult]:
        """Search for skills matching *intent* against the built-in registry.

        The search considers:
        1. Direct substring match on name/description/provides.
        2. Tag overlap via the intent-to-category mapping.
        """
        intent_lower = intent.lower().strip()
        if not intent_lower:
            return []

        # Determine expanded tags from intent
        expanded_tags: set = set()
        for keyword, categories in _INTENT_CATEGORY_MAP.items():
            if keyword in intent_lower:
                expanded_tags.update(categories)

        scored: List[tuple] = []
        for entry in _BUILTIN_SKILL_REGISTRY:
            score = 0

            name_lower = entry["name"].lower()
            desc_lower = entry["description"].lower()
            provides_lower = entry["provides"].lower()

            # Direct text matching
            if intent_lower in name_lower:
                score += 50
            if intent_lower in desc_lower:
                score += 30
            if intent_lower in provides_lower:
                score += 20

            # Word-level matching
            for word in intent_lower.split():
                if len(word) < 3:
                    continue
                if word in name_lower:
                    score += 15
                if word in desc_lower:
                    score += 10
                if word in provides_lower:
                    score += 8

            # Tag overlap
            entry_tags = set(t.lower() for t in entry.get("tags", []))
            overlap = entry_tags & expanded_tags
            score += len(overlap) * 12

            if score > 0:
                scored.append((score, entry))

        # Sort descending by score
        scored.sort(key=lambda t: t[0], reverse=True)

        results: List[SkillSearchResult] = []
        for _score, entry in scored:
            results.append(
                SkillSearchResult(
                    name=entry["name"],
                    skill_type="skill",
                    provides=entry["provides"],
                    source=entry["source"],
                    trust_score=entry.get("trust_score"),
                )
            )

        logger.info("search_skills(%r) returned %d results", intent, len(results))
        return results

    # ── List ──────────────────────────────────────────────────────────────

    def list_skills(self) -> SkillListResult:
        """List installed skills from global, project, and extra directories."""
        global_skills = self._scan_directory(self.global_dir, SkillScope.GLOBAL)
        project_skills = self._scan_directory(self.project_dir, SkillScope.PROJECT)

        extra_skills: List[AgentSkill] = []
        for extra_dir in self.extra_dirs:
            extra_skills.extend(self._scan_directory(extra_dir, SkillScope.GLOBAL))

        all_skills = global_skills + project_skills + extra_skills
        total = len(all_skills)
        auto_invocable = sum(1 for s in all_skills if s.auto_invocation)

        logger.info(
            "list_skills: %d global, %d project, %d extra, %d auto-invocable",
            len(global_skills),
            len(project_skills),
            len(extra_skills),
            auto_invocable,
        )
        return SkillListResult(
            global_skills=global_skills + extra_skills,
            project_skills=project_skills,
            total=total,
            auto_invocable=auto_invocable,
        )

    def _scan_directory(self, directory: Path, scope: SkillScope) -> List[AgentSkill]:
        """Scan *directory* for SKILL.md files and parse each one."""
        skills: List[AgentSkill] = []
        if not directory.is_dir():
            return skills

        for child in sorted(directory.iterdir()):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.is_file():
                continue
            data = _parse_skill_md(skill_file)
            if data is not None:
                skills.append(_skill_from_frontmatter(data, scope))

        return skills

    # ── Install ───────────────────────────────────────────────────────────

    def install_skill(
        self,
        name: str,
        source: str,
        scope: SkillScope = SkillScope.PROJECT,
    ) -> AgentSkill:
        """Install a skill from *source*.

        *source* may be:
        - A local directory path containing a SKILL.md -- the directory is
          copied into the target scope.
        - A GitHub URL (https://github.com/...) -- the repository is cloned
          into the skill directory with all assets preserved.
        - A registry name -- looked up in the built-in registry and a
          placeholder SKILL.md is created.

        Returns the installed ``AgentSkill``.
        """
        target_dir = self._scope_dir(scope)
        skill_dir = target_dir / self._normalise_name(name)
        skill_file = skill_dir / "SKILL.md"

        if skill_file.exists():
            logger.info("Skill %r already installed at %s", name, skill_dir)
            data = _parse_skill_md(skill_file)
            if data is not None:
                return _skill_from_frontmatter(data, scope)

        skill_dir.mkdir(parents=True, exist_ok=True)

        # Detect source type: local path, GitHub URL, or registry name
        source_path = Path(source).expanduser().resolve()
        parsed_url = urlparse(source)
        is_url = parsed_url.scheme in ("http", "https")

        if source_path.is_dir():
            self._install_from_local(source_path, skill_dir, skill_file)
        elif is_url and "github.com" in (parsed_url.hostname or ""):
            self._install_from_github(source, skill_dir, skill_file)
        else:
            self._install_from_registry(name, source, skill_dir, skill_file)

        # Parse the newly written SKILL.md to return a model
        data = _parse_skill_md(skill_file)
        if data is None:
            raise RuntimeError(f"Failed to parse newly installed skill at {skill_file}")

        skill = _skill_from_frontmatter(data, scope)
        logger.info("Installed skill %r (%s) at %s", name, scope.value, skill_dir)
        return skill

    def _install_from_local(
        self, source_dir: Path, skill_dir: Path, skill_file: Path
    ) -> None:
        """Copy a local skill directory into *skill_dir*.

        All contents (SKILL.md, scripts, assets) are copied so that
        relative-path references in the skill instructions keep working.
        """
        source_skill = source_dir / "SKILL.md"
        if not source_skill.is_file():
            raise RuntimeError(
                f"Local path {source_dir} does not contain a SKILL.md"
            )

        # Copy all contents from source into skill_dir
        for item in source_dir.iterdir():
            dest = skill_dir / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(str(dest))
                else:
                    dest.unlink()
            if item.is_dir():
                shutil.copytree(str(item), str(dest))
            else:
                shutil.copy2(str(item), str(dest))

        logger.info("Copied local skill from %s to %s", source_dir, skill_dir)

    def _install_from_github(
        self, url: str, skill_dir: Path, skill_file: Path
    ) -> None:
        """Clone a GitHub repository directly into *skill_dir*.

        All repo contents (scripts, assets, configs) are preserved so that
        SKILL.md instructions referencing relative paths keep working.
        If the repo lacks a SKILL.md, one is generated from the README.
        """
        try:
            import git  # GitPython

            # Clone into a temp location, then move everything into skill_dir
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                clone_target = Path(tmp) / "repo"
                logger.info("Cloning %s", url)
                git.Repo.clone_from(url, str(clone_target), depth=1)

                # Remove .git to save space — we don't need history
                git_dir = clone_target / ".git"
                if git_dir.exists():
                    shutil.rmtree(str(git_dir), ignore_errors=True)

                # Copy all repo contents into skill_dir
                for item in clone_target.iterdir():
                    dest = skill_dir / item.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(str(dest))
                        else:
                            dest.unlink()
                    if item.is_dir():
                        shutil.copytree(str(item), str(dest))
                    else:
                        shutil.copy2(str(item), str(dest))

            # If the repo didn't ship a SKILL.md, generate one
            if not skill_file.is_file():
                repo_name = Path(urlparse(url).path).stem
                content = _generate_frontmatter(
                    name=repo_name,
                    description=f"Skill cloned from {url}",
                    allowed_tools=["Bash", "Read"],
                    tags=["community", "github"],
                )
                readme_path = skill_dir / "README.md"
                body = ""
                if readme_path.is_file():
                    try:
                        body = readme_path.read_text(encoding="utf-8")[:2000]
                    except OSError:
                        pass
                if not body:
                    body = f"# {repo_name}\n\nSkill imported from {url}."
                skill_file.write_text(
                    f"{content}\n\n{body}\n", encoding="utf-8"
                )

        except ImportError:
            logger.error("GitPython is required to install skills from GitHub URLs")
            raise RuntimeError(
                "GitPython is not installed. Add 'GitPython>=3.1.0' to dependencies."
            )
        except Exception as exc:
            logger.error("Failed to clone skill from %s: %s", url, exc)
            raise RuntimeError(f"GitHub clone failed for {url}: {exc}") from exc

    def _install_from_registry(
        self,
        name: str,
        source: str,
        skill_dir: Path,
        skill_file: Path,
    ) -> None:
        """Create a SKILL.md from the built-in registry entry for *name*."""
        # Attempt to find the skill in the built-in registry
        registry_entry: Optional[Dict[str, Any]] = None
        for entry in _BUILTIN_SKILL_REGISTRY:
            if entry["name"] == name or entry["name"] == source:
                registry_entry = entry
                break

        if registry_entry:
            description = registry_entry["description"]
            tags = registry_entry.get("tags", [])
            provides = registry_entry.get("provides", description)
        else:
            description = f"Skill '{name}' installed from source: {source}"
            tags = ["custom"]
            provides = description

        content = _generate_frontmatter(
            name=name,
            description=description,
            allowed_tools=["Bash", "Read"],
            tags=tags,
        )
        body = f"# {name}\n\n{provides}\n"
        skill_file.write_text(f"{content}\n\n{body}\n", encoding="utf-8")

    # ── Uninstall ─────────────────────────────────────────────────────────

    def uninstall_skill(self, name: str, scope: SkillScope = SkillScope.PROJECT) -> bool:
        """Remove a skill by name.  Returns ``True`` if the skill was found and removed."""
        target_dir = self._scope_dir(scope)
        skill_dir = target_dir / self._normalise_name(name)

        if not skill_dir.is_dir():
            logger.warning("Skill %r not found in %s scope", name, scope.value)
            return False

        shutil.rmtree(str(skill_dir))
        logger.info("Uninstalled skill %r from %s scope", name, scope.value)
        return True

    # ── Update ────────────────────────────────────────────────────────────

    def update_skills(self) -> List[str]:
        """Update all installed skills from their sources.

        Returns a list of skill names that were updated.  Currently, updates
        are supported only for skills whose SKILL.md frontmatter includes a
        ``source`` field pointing to a GitHub URL.
        """
        updated: List[str] = []

        for scope, directory in [
            (SkillScope.GLOBAL, self.global_dir),
            (SkillScope.PROJECT, self.project_dir),
        ]:
            if not directory.is_dir():
                continue
            for child in sorted(directory.iterdir()):
                if not child.is_dir():
                    continue
                skill_file = child / "SKILL.md"
                if not skill_file.is_file():
                    continue
                data = _parse_skill_md(skill_file)
                if data is None:
                    continue

                source = data.get("source", "")
                if isinstance(source, str) and "github.com" in source:
                    try:
                        self._install_from_github(source, child, skill_file)
                        updated.append(data.get("name", child.name))
                        logger.info("Updated skill %s from %s", child.name, source)
                    except Exception as exc:
                        logger.warning(
                            "Failed to update skill %s: %s", child.name, exc
                        )

        logger.info("update_skills: %d skills updated", len(updated))
        return updated

    # ── Discover Prompts ──────────────────────────────────────────────────

    async def discover_prompts(
        self, servers_config: Dict[str, Any]
    ) -> List[MCPPrompt]:
        """Discover MCP prompts from configured servers.

        Since actually connecting to running servers requires the orchestration
        module, this method returns *known prompt patterns* for common server
        names found in *servers_config*.
        """
        prompts: List[MCPPrompt] = []

        for server_name in servers_config:
            # Normalise the configured server name for lookup
            normalised = server_name.lower().replace("_", "-").replace(" ", "-")
            for known_name, known_prompts in _KNOWN_SERVER_PROMPTS.items():
                if known_name in normalised:
                    for prompt_data in known_prompts:
                        prompts.append(
                            MCPPrompt(
                                name=prompt_data["name"],
                                description=prompt_data["description"],
                                arguments=prompt_data.get("arguments", []),
                                server=server_name,
                            )
                        )
                    break

        logger.info(
            "discover_prompts: found %d prompts for %d servers",
            len(prompts),
            len(servers_config),
        )
        return prompts

    # ── Generate Workflow Skill ────────────────────────────────────────────

    def generate_workflow_skill(
        self,
        name: str,
        workflow_steps: List[Dict[str, str]],
        project_path: Optional[str] = None,
    ) -> GeneratedSkill:
        """Generate a SKILL.md encoding *workflow_steps*.

        Each step is expected to be a dict with keys ``server``, ``tool``,
        and ``description``.  The generated SKILL.md is saved under the
        project skills directory.

        Returns a ``GeneratedSkill`` model.
        """
        target_dir = _resolve_project_skills_dir(project_path or self.project_path)
        skill_dir = target_dir / self._normalise_name(name)
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"

        # Collect required servers
        required_servers: List[str] = list(
            dict.fromkeys(step.get("server", "") for step in workflow_steps if step.get("server"))
        )
        allowed_tools: List[str] = list(
            dict.fromkeys(step.get("tool", "") for step in workflow_steps if step.get("tool"))
        )
        step_descriptions: List[str] = []
        for idx, step in enumerate(workflow_steps, 1):
            desc = step.get("description", "")
            server = step.get("server", "unknown")
            tool = step.get("tool", "unknown")
            step_descriptions.append(
                f"{idx}. **[{server}:{tool}]** {desc}"
            )

        frontmatter = _generate_frontmatter(
            name=name,
            description=f"Auto-generated workflow skill with {len(workflow_steps)} steps",
            allowed_tools=allowed_tools or ["Bash", "Read"],
            tags=["workflow", "generated"],
            required_servers=required_servers,
        )

        body_lines = [
            f"# {name}",
            "",
            "This skill was auto-generated from a workflow definition.",
            "",
            "## Workflow Steps",
            "",
        ]
        body_lines.extend(step_descriptions)
        body_lines.append("")
        body_lines.append("## Execution Notes")
        body_lines.append("")
        body_lines.append(
            "Execute the steps in order. If a step fails, report the error "
            "and skip to the next step unless it is marked as required."
        )

        content = f"{frontmatter}\n\n" + "\n".join(body_lines) + "\n"
        skill_file.write_text(content, encoding="utf-8")

        logger.info("Generated workflow skill %r at %s", name, skill_file)
        return GeneratedSkill(
            name=name,
            path=str(skill_file.resolve()),
            workflow_steps=[s.get("description", "") for s in workflow_steps],
            required_servers=required_servers,
        )

    # ── Trust Analysis ────────────────────────────────────────────────────

    def analyze_skill_trust(self, skill_path: str) -> SkillTrustResult:
        """Perform a security analysis of the skill at *skill_path*.

        Checks include:
        - Dangerous instruction patterns (prompt injection, code execution).
        - Source reputation (official vs. unknown).
        - Allowed-tools scope breadth.

        Returns a ``SkillTrustResult`` with a score (0-100) and warnings.
        """
        path = Path(skill_path)
        if path.is_dir():
            path = path / "SKILL.md"

        data = _parse_skill_md(path)
        if data is None:
            return SkillTrustResult(
                skill_name=path.parent.name,
                trust_score=0,
                warnings=["Could not read or parse SKILL.md"],
                recommendation="Unable to analyse -- treat as untrusted.",
            )

        skill_name = data.get("name", path.parent.name)
        warnings: List[str] = []
        deductions = 0

        # --- Dangerous pattern scan ---
        full_text = data.get("_body", "")
        for pattern, description, weight in _DANGEROUS_PATTERNS:
            if pattern.search(full_text):
                warnings.append(f"DANGEROUS: {description}")
                deductions += weight

        # --- Source reputation ---
        source = data.get("source", "unknown")
        source_lower = str(source).lower()
        is_official = any(org in source_lower for org in _OFFICIAL_SOURCES)
        name_lower = skill_name.lower()
        is_official = is_official or any(org in name_lower for org in _OFFICIAL_SOURCES)

        if not is_official:
            if source_lower in ("unknown", "local", "custom", ""):
                warnings.append("Source is unknown or unverified")
                deductions += 10
            else:
                warnings.append(f"Source '{source}' is not in the official trust list")
                deductions += 5

        # --- Allowed-tools scope ---
        allowed_tools = data.get("allowed-tools", [])
        high_risk_tools = {"Bash", "bash", "shell", "Shell", "terminal", "Terminal"}
        risky = set(allowed_tools) & high_risk_tools
        if risky:
            warnings.append(
                f"Skill requests access to high-risk tools: {', '.join(sorted(risky))}"
            )
            deductions += 10
        if len(allowed_tools) > 8:
            warnings.append(
                f"Skill requests a broad tool set ({len(allowed_tools)} tools)"
            )
            deductions += 5

        # --- Compute final score ---
        score = max(0, 100 - deductions)
        if is_official and deductions < 30:
            # Boost official skills back up unless they have severe issues
            score = min(100, score + 15)

        # --- Recommendation ---
        if score >= 80:
            recommendation = "Skill appears safe to use."
        elif score >= 50:
            recommendation = "Review the warnings before enabling this skill."
        elif score >= 25:
            recommendation = "This skill has significant trust concerns -- use with caution."
        else:
            recommendation = "This skill is untrusted and potentially dangerous. Do NOT enable."

        logger.info(
            "analyze_skill_trust(%s): score=%d, warnings=%d",
            skill_name,
            score,
            len(warnings),
        )
        return SkillTrustResult(
            skill_name=skill_name,
            trust_score=score,
            warnings=warnings,
            recommendation=recommendation,
        )

    # ── AGENTS.md ─────────────────────────────────────────────────────────

    def read_agents_md(self, project_path: Optional[str] = None) -> Optional[str]:
        """Read the AGENTS.md file from the project root.

        Returns the file content as a string, or ``None`` if the file does
        not exist.
        """
        root = Path(project_path) if project_path else Path.cwd()
        agents_file = root / "AGENTS.md"

        if not agents_file.is_file():
            logger.debug("No AGENTS.md found at %s", agents_file)
            return None

        try:
            content = agents_file.read_text(encoding="utf-8")
            logger.info("Read AGENTS.md from %s (%d bytes)", agents_file, len(content))
            return content
        except OSError as exc:
            logger.warning("Failed to read AGENTS.md: %s", exc)
            return None

    def suggest_agents_md_update(
        self,
        installed_servers: List[str],
        installed_skills: List[str],
    ) -> str:
        """Generate suggested AGENTS.md content based on current capabilities.

        This produces a Markdown document that can be saved as AGENTS.md in
        the project root.
        """
        now = datetime.now().strftime("%Y-%m-%d")

        lines: List[str] = [
            "# AGENTS.md",
            "",
            f"*Auto-generated on {now} by meta-mcp.*",
            "",
            "## Available MCP Servers",
            "",
        ]
        if installed_servers:
            for server in sorted(installed_servers):
                lines.append(f"- **{server}**")
        else:
            lines.append("_No MCP servers installed._")

        lines.extend([
            "",
            "## Installed Skills",
            "",
        ])
        if installed_skills:
            for skill in sorted(installed_skills):
                lines.append(f"- {skill}")
        else:
            lines.append("_No skills installed._")

        lines.extend([
            "",
            "## Agent Guidelines",
            "",
            "1. Prefer using MCP server tools over shell commands when available.",
            "2. Check skill instructions before starting a task covered by an installed skill.",
            "3. Respect allowed-tools restrictions defined in each SKILL.md.",
            "4. When a required MCP server is not running, report the gap rather than "
            "working around it silently.",
            "",
            "## Capability Gaps",
            "",
            "If you identify a task that cannot be completed with the current set of "
            "servers and skills, note it here so the team can evaluate adding new "
            "capabilities.",
            "",
        ])

        content = "\n".join(lines)
        logger.info(
            "suggest_agents_md_update: generated %d bytes with %d servers, %d skills",
            len(content),
            len(installed_servers),
            len(installed_skills),
        )
        return content

    # ── Unified Capability Search ─────────────────────────────────────────

    def search_capabilities(self, intent: str) -> CapabilitySearchResult:
        """Search across skills, known prompts, and the built-in registry.

        Returns a ``CapabilitySearchResult`` aggregating hits from all
        capability layers.
        """
        skill_results = self.search_skills(intent)

        # Prompt search (synchronous approximation)
        prompt_results: List[MCPPrompt] = []
        intent_lower = intent.lower()
        for server_name, prompts in _KNOWN_SERVER_PROMPTS.items():
            for prompt_data in prompts:
                if (
                    intent_lower in prompt_data["name"].lower()
                    or intent_lower in prompt_data["description"].lower()
                ):
                    prompt_results.append(
                        MCPPrompt(
                            name=prompt_data["name"],
                            description=prompt_data["description"],
                            arguments=prompt_data.get("arguments", []),
                            server=server_name,
                        )
                    )

        # Recommendation summary
        parts: List[str] = []
        if skill_results:
            parts.append(f"{len(skill_results)} skill(s)")
        if prompt_results:
            parts.append(f"{len(prompt_results)} prompt(s)")
        if parts:
            recommendation = f"Found {' and '.join(parts)} matching '{intent}'."
        else:
            recommendation = (
                f"No capabilities found matching '{intent}'. "
                "Consider installing additional MCP servers or skills."
            )

        return CapabilitySearchResult(
            mcp_servers=[],
            agent_skills=skill_results,
            mcp_prompts=prompt_results,
            recommendation=recommendation,
        )

    # ── Private Helpers ───────────────────────────────────────────────────

    def _scope_dir(self, scope: SkillScope) -> Path:
        """Return the base directory for *scope*."""
        if scope == SkillScope.GLOBAL:
            return self.global_dir
        elif scope == SkillScope.ENTERPRISE:
            # Enterprise scope falls back to global for now
            return self.global_dir
        return self.project_dir

    @staticmethod
    def _normalise_name(name: str) -> str:
        """Normalise a skill name to a filesystem-safe directory name."""
        # Strip common path prefixes (e.g. "anthropics/skills/code-review")
        basename = name.rsplit("/", 1)[-1] if "/" in name else name
        # Replace non-alphanumeric characters with hyphens
        safe = re.sub(r"[^a-zA-Z0-9_-]", "-", basename)
        # Collapse repeated hyphens and strip leading/trailing ones
        safe = re.sub(r"-+", "-", safe).strip("-")
        return safe.lower() or "unnamed-skill"
