"""
Central settings for Meta MCP.

Reads configuration from ``~/.config/meta-mcp/config.toml`` (POSIX) or
``%APPDATA%/meta-mcp/config.toml`` (Windows).  Environment variables
override config-file values for backward compatibility.

Usage::

    from .settings import get_settings
    settings = get_settings()
    print(settings.registry_extra_dirs)
"""

import logging
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Use stdlib tomllib on 3.11+, fall back to tomli on older versions
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


def _default_config_dir() -> Path:
    """Return the platform-appropriate config directory."""
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata) / "meta-mcp"
    return Path.home() / ".config" / "meta-mcp"


def _default_config_path() -> Path:
    return _default_config_dir() / "config.toml"


@dataclass
class Settings:
    """Resolved meta-mcp settings (config file + env var overrides)."""

    # [registry]
    registry_extra_dirs: List[Path] = field(default_factory=list)

    # [skills]
    skills_extra_dirs: List[Path] = field(default_factory=list)

    # [github]
    github_token: str = ""

    # [install]
    install_default_clients: List[str] = field(default_factory=lambda: ["claude_code"])

    # Path to the config file that was loaded (empty string if none)
    _config_file: str = ""


# Module-level singleton
_settings: Optional[Settings] = None


def _parse_path_list(raw: object) -> List[Path]:
    """Convert a TOML list of strings to a list of resolved Paths."""
    if not isinstance(raw, list):
        return []
    dirs: List[Path] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            continue
        p = Path(entry.strip()).expanduser().resolve()
        if p.is_dir():
            dirs.append(p)
        else:
            logger.debug("configured directory does not exist, skipping: %s", p)
    return dirs


def _parse_env_path_list(env_var: str) -> List[Path]:
    """Parse a path-separator-delimited env var into a list of Paths."""
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return []
    dirs: List[Path] = []
    for entry in raw.split(os.pathsep):
        entry = entry.strip()
        if not entry:
            continue
        p = Path(entry).expanduser().resolve()
        if p.is_dir():
            dirs.append(p)
        else:
            logger.debug("env var directory does not exist, skipping: %s", p)
    return dirs


def load_settings(config_path: Optional[Path] = None) -> Settings:
    """Load settings from config file, then apply env var overrides."""
    settings = Settings()
    path = config_path or _default_config_path()

    # --- Read config file ---
    if path.is_file() and tomllib is not None:
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            settings._config_file = str(path)

            registry = data.get("registry", {})
            settings.registry_extra_dirs = _parse_path_list(registry.get("extra_dirs"))

            skills = data.get("skills", {})
            settings.skills_extra_dirs = _parse_path_list(skills.get("extra_dirs"))

            github = data.get("github", {})
            settings.github_token = str(github.get("token", "")).strip()

            install = data.get("install", {})
            clients = install.get("default_clients")
            if isinstance(clients, list):
                settings.install_default_clients = [str(c) for c in clients]

            logger.debug("Loaded settings from %s", path)
        except Exception:
            logger.warning("Failed to parse config file %s", path, exc_info=True)
    elif path.is_file() and tomllib is None:
        logger.warning(
            "Config file %s exists but tomli is not installed "
            "(install `tomli` for Python <3.11 support)",
            path,
        )

    # --- Env var overrides (take priority over config file) ---
    env_registry = os.environ.get("META_MCP_REGISTRY_DIRS", "").strip()
    if env_registry:
        settings.registry_extra_dirs = _parse_env_path_list("META_MCP_REGISTRY_DIRS")

    env_skills = os.environ.get("META_MCP_SKILLS_DIRS", "").strip()
    if env_skills:
        settings.skills_extra_dirs = _parse_env_path_list("META_MCP_SKILLS_DIRS")

    env_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if env_token:
        settings.github_token = env_token

    return settings


def get_settings() -> Settings:
    """Return the cached Settings singleton, loading on first call."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    """Reset the singleton so the next ``get_settings()`` reloads from disk."""
    global _settings
    _settings = None


# ---------------------------------------------------------------------------
# Default config template (used by install scripts)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_TOML = """\
# Meta MCP configuration
# Docs: https://github.com/<owner>/meta-mcp#configuration

[registry]
# Extra directories containing server definitions (.mcp.json, servers.json, or per-server .json)
extra_dirs = []

[skills]
# Extra directories containing SKILL.md skill folders
extra_dirs = []

[github]
# GitHub token for higher API rate limits during discovery
token = ""

[install]
# Default target clients for install_mcp_server
default_clients = ["claude_code"]
"""
