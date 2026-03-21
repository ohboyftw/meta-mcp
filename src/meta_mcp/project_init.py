"""
Project initialization — bootstraps .mcp.json and .claude/settings.local.json
so that MCP servers work out of the box in any project directory.

Key design: env var values are resolved from os.environ at write time,
NOT written as "${VAR}" placeholders (which Claude Code does NOT expand).
"""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .models import ProjectInitResult, ProjectServerDefinition, ProjectValidateResult
from .profiles import load_profile, list_profiles, ProfileNotFoundError

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

def _get_skills_repo() -> str:
    """Return the skills repo path from env var, config file, or empty string."""
    env_val = os.environ.get("CLAUDE_SKILLS_REPO", "").strip()
    if env_val:
        return env_val
    from .settings import get_settings

    settings = get_settings()
    if settings.skills_extra_dirs:
        return str(settings.skills_extra_dirs[0])
    return ""


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

        # Load profile configuration
        profile_name = profile or "default"
        try:
            profile_config = load_profile(profile_name)
        except ProfileNotFoundError:
            logger.warning("Profile '%s' not found, falling back to empty config", profile_name)
            profile_config = None

        # Check env_required from profile and warn for missing vars
        if profile_config and profile_config.env_required and validate_env:
            missing = [v for v in profile_config.env_required if not os.environ.get(v)]
            if missing:
                result.missing_env_vars["_profile"] = missing

        # Determine server list
        if servers:
            server_names = servers
        else:
            server_names = self._resolve_server_list(profile_name)

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
            if name in existing_servers:
                result.servers_skipped.append(name)
                continue

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

        # Append post_install messages from profile
        if profile_config and profile_config.post_install:
            result.warnings.extend(profile_config.post_install)

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

    def _resolve_server_list(self, profile: Optional[str] = None) -> List[str]:
        """Resolve which servers to install from a profile name."""
        if not profile:
            profile = "default"
        try:
            config = load_profile(profile)
            return [s.name for s in config.servers if s.auto_install]
        except ProfileNotFoundError:
            logger.warning("Profile '%s' not found, using empty list", profile)
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
