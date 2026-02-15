"""
Project initialization — bootstraps .mcp.json and .claude/settings.local.json
so that MCP servers work out of the box in any project directory.

Key design: env var values are resolved from os.environ at write time,
NOT written as "${VAR}" placeholders (which Claude Code does NOT expand).
"""

import json
import os
import platform
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .models import ProjectInitResult, ProjectServerDefinition, ProjectValidateResult

# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_SKILLS_REPO = "D:/Home/claudeSkills/Repo"


def _get_skills_repo() -> str:
    return os.environ.get("CLAUDE_SKILLS_REPO", DEFAULT_SKILLS_REPO)


def _get_python_command() -> str:
    """Returns 'py' on Windows, 'python3' on Unix."""
    return "py" if platform.system() == "Windows" else "python3"


KNOWN_PROJECT_SERVERS: Dict[str, ProjectServerDefinition] = {
    "beacon": ProjectServerDefinition(
        name="beacon",
        description="Static knowledge — hybrid BM25+semantic search across project docs",
        command=_get_python_command(),
        args=["{skills_repo}/beacon/mcp_server.py"],
        category="knowledge",
    ),
    "engram": ProjectServerDefinition(
        name="engram",
        description="Dynamic memory — decisions, patterns, reasoning traces",
        command=_get_python_command(),
        args=["{skills_repo}/engram-memory-skill/mcp_server.py"],
        env_vars={
            "ENGRAM_PROJECT_ROOT": "{project_root}",
            "MEM0_TELEMETRY": "false",
        },
        category="knowledge",
    ),
    "rlm": ProjectServerDefinition(
        name="rlm",
        description="Large-context analysis — sandboxed REPL workspace",
        command=_get_python_command(),
        args=["{skills_repo}/rlm-workspace/mcp_server.py"],
        category="knowledge",
    ),
    "llm-council": ProjectServerDefinition(
        name="llm-council",
        description="Multi-LLM council for consensus-based decisions",
        command=_get_python_command(),
        args=["{skills_repo}/llm-council/mcp_server.py"],
        required_env_from_os=[
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GOOGLE_API_KEY",
            "MINIMAX_API_KEY",
            "MOONSHOT_API_KEY",
        ],
        category="ai",
    ),
    "expert-panel": ProjectServerDefinition(
        name="expert-panel",
        description="Expert panel for multi-perspective analysis",
        command=_get_python_command(),
        args=["{skills_repo}/expert-panel/mcp_server.py"],
        category="ai",
    ),
}

PROFILES: Dict[str, List[str]] = {
    "knowledge-stack": ["beacon", "engram", "rlm"],
    "knowledge-stack-full": ["beacon", "engram", "rlm", "llm-council"],
    "full": ["beacon", "engram", "rlm", "llm-council", "expert-panel"],
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_template(value: str, context: Dict[str, str]) -> str:
    """Resolve {template} variables in a string using str.format_map."""
    try:
        return value.format_map(context)
    except KeyError:
        return value


def _ensure_settings_flag(project_root: Path) -> bool:
    """Create/update .claude/settings.local.json with enableAllProjectMcpServers: true.

    Returns True if the file was created or modified.
    """
    settings_dir = project_root / ".claude"
    settings_file = settings_dir / "settings.local.json"

    existing: Dict = {}
    if settings_file.exists():
        try:
            existing = json.loads(settings_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    if existing.get("permissions", {}).get("enableAllProjectMcpServers") is True:
        return False

    existing.setdefault("permissions", {})["enableAllProjectMcpServers"] = True

    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return True


# ─── ProjectInitializer ──────────────────────────────────────────────────────

class ProjectInitializer:
    """Bootstraps a project's MCP environment in one call."""

    def initialize_project(
        self,
        project_root: str = ".",
        servers: Optional[List[str]] = None,
        profile: Optional[str] = None,
        include_knowledge_stack: bool = True,
        validate_env: bool = True,
        dry_run: bool = False,
    ) -> ProjectInitResult:
        root = Path(project_root).resolve()
        result = ProjectInitResult()

        # Determine server list
        server_names = self._resolve_server_list(servers, profile, include_knowledge_stack)

        # Build template context
        context = {
            "project_root": str(root),
            "skills_repo": _get_skills_repo(),
            "home": str(Path.home()),
        }

        # Load existing .mcp.json (merge, don't overwrite)
        mcp_json_path = root / ".mcp.json"
        existing_config: Dict = {}
        if mcp_json_path.exists():
            try:
                existing_config = json.loads(mcp_json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                result.warnings.append("Existing .mcp.json was invalid JSON — starting fresh")

        existing_servers = existing_config.get("mcpServers", {})
        result.pre_existing_servers = list(existing_servers.keys())

        # Process each server
        new_servers: Dict = {}
        for name in server_names:
            defn = KNOWN_PROJECT_SERVERS.get(name)
            if defn is None:
                result.warnings.append(f"Unknown server '{name}' — skipped")
                result.servers_skipped.append(name)
                continue

            if name in existing_servers:
                result.servers_skipped.append(name)
                continue

            # Build server entry
            entry = self._build_server_entry(defn, context, validate_env, result)
            new_servers[name] = entry
            result.servers_configured.append(name)

        if not dry_run:
            # Merge and write .mcp.json
            merged = {**existing_servers, **new_servers}
            existing_config["mcpServers"] = merged
            mcp_json_path.write_text(
                json.dumps(existing_config, indent=2) + "\n", encoding="utf-8"
            )

            # Ensure settings flag
            result.settings_updated = _ensure_settings_flag(root)
        else:
            result.warnings.append("Dry run — no files written")

        return result

    def validate_project(self, project_root: str = ".") -> ProjectValidateResult:
        root = Path(project_root).resolve()
        result = ProjectValidateResult()

        # Check .mcp.json
        mcp_json_path = root / ".mcp.json"
        if mcp_json_path.exists():
            try:
                config = json.loads(mcp_json_path.read_text(encoding="utf-8"))
                result.has_mcp_json = True
            except (json.JSONDecodeError, OSError):
                result.unhealthy_servers["_mcp_json"] = "Invalid JSON"
                return result
        else:
            return result

        # Check settings flag
        settings_file = root / ".claude" / "settings.local.json"
        if settings_file.exists():
            try:
                settings = json.loads(settings_file.read_text(encoding="utf-8"))
                result.has_settings_flag = settings.get("permissions", {}).get(
                    "enableAllProjectMcpServers", False
                )
            except (json.JSONDecodeError, OSError):
                pass

        # Check each server
        servers = config.get("mcpServers", {})
        for name, entry in servers.items():
            command = entry.get("command", "")
            if not command:
                result.unhealthy_servers[name] = "No command specified"
                continue

            if not shutil.which(command):
                result.unhealthy_servers[name] = f"Command '{command}' not found on PATH"
                continue

            # Check env vars are non-empty
            env = entry.get("env", {})
            empty_vars = [k for k, v in env.items() if not v]
            if empty_vars:
                result.unhealthy_servers[name] = f"Empty env vars: {', '.join(empty_vars)}"
                continue

            result.healthy_servers.append(name)

        result.overall_healthy = (
            result.has_mcp_json
            and result.has_settings_flag
            and len(result.unhealthy_servers) == 0
            and len(result.healthy_servers) > 0
        )
        return result

    # ─── Internal helpers ─────────────────────────────────────────────────

    def _resolve_server_list(
        self,
        servers: Optional[List[str]],
        profile: Optional[str],
        include_knowledge_stack: bool,
    ) -> List[str]:
        if servers:
            return servers
        if profile:
            return PROFILES.get(profile, PROFILES["knowledge-stack"])
        if include_knowledge_stack:
            return PROFILES["knowledge-stack"]
        return []

    def _build_server_entry(
        self,
        defn: ProjectServerDefinition,
        context: Dict[str, str],
        validate_env: bool,
        result: ProjectInitResult,
    ) -> Dict:
        """Build a single .mcp.json server entry from a definition."""
        entry: Dict = {
            "command": _resolve_template(defn.command, context),
            "args": [_resolve_template(a, context) for a in defn.args],
        }

        # Resolve template env vars
        env: Dict[str, str] = {}
        for key, val in defn.env_vars.items():
            env[key] = _resolve_template(val, context)

        # Resolve required_env_from_os — read actual values from os.environ
        missing: List[str] = []
        for key in defn.required_env_from_os:
            value = os.environ.get(key, "")
            env[key] = value
            if not value:
                missing.append(key)

        if missing and validate_env:
            result.missing_env_vars[defn.name] = missing

        if env:
            entry["env"] = env

        return entry
