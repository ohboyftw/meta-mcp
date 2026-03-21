"""
Profile YAML loading for project bootstrap.

Profiles define which skills and MCP servers to install when bootstrapping
a project. They are discovered in order:
  1. Skill repo: <repo>/profiles/*.yaml
  2. Global: ~/.config/meta-mcp/profiles/*.yaml
  3. Built-in: this package's default.yaml
"""

import platform
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel


class ProfileServerEntry(BaseModel):
    """A server entry within a profile.

    Minimal profiles only need ``name`` + ``auto_install``.  Richer profiles
    can embed the full server definition so that ``project_init`` can write
    it to ``.mcp.json`` without a separate registry lookup.
    """
    name: str
    auto_install: bool = False
    # Optional server definition fields (used when present)
    command: str = ""
    args: List[str] = []
    env_vars: Dict[str, str] = {}
    required_env_from_os: List[str] = []
    description: str = ""
    category: str = "knowledge"


class ProfileConfig(BaseModel):
    """Validated profile configuration."""
    name: str
    description: str
    skills: List[str] = []
    servers: List[ProfileServerEntry] = []
    env_required: List[str] = []
    post_install: List[str] = []


class ProfileNotFoundError(FileNotFoundError):
    """Raised when a profile YAML cannot be found in any search location."""
    pass


_BUILTIN_DIR = Path(__file__).parent


def _search_dirs(extra_dirs: Optional[List[Path]] = None) -> List[Path]:
    """Return profile search directories in priority order."""
    dirs: List[Path] = []

    # 1. Extra dirs (skill repos) — append /profiles to each
    if extra_dirs:
        for d in extra_dirs:
            profiles_subdir = Path(d) / "profiles"
            if profiles_subdir.is_dir():
                dirs.append(profiles_subdir)

    # 2. Extra dirs from settings
    try:
        from ..settings import get_settings
        settings = get_settings()
        for d in settings.skills_extra_dirs:
            profiles_subdir = d / "profiles"
            if profiles_subdir.is_dir() and profiles_subdir not in dirs:
                dirs.append(profiles_subdir)
    except Exception:
        pass

    # 3. Global config dir
    if platform.system() == "Windows":
        import os
        global_profiles = Path(os.environ.get("APPDATA", "~")) / "meta-mcp" / "profiles"
    else:
        global_profiles = Path.home() / ".config" / "meta-mcp" / "profiles"
    if global_profiles.is_dir():
        dirs.append(global_profiles)

    # 4. Built-in
    dirs.append(_BUILTIN_DIR)

    return dirs


def load_profile(
    name: str,
    extra_dirs: Optional[List[Path]] = None,
) -> ProfileConfig:
    """Load a profile by name from the search path.

    Raises:
        ProfileNotFoundError: if no matching YAML found.
        ValueError: if YAML is malformed or missing required fields.
    """
    searched: List[str] = []

    for search_dir in _search_dirs(extra_dirs):
        candidate = search_dir / f"{name}.yaml"
        searched.append(str(candidate))
        if candidate.is_file():
            return _parse_profile(candidate)

    raise ProfileNotFoundError(
        f"Profile '{name}' not found. Searched:\n"
        + "\n".join(f"  - {p}" for p in searched)
    )


def list_profiles(extra_dirs: Optional[List[Path]] = None) -> List[ProfileConfig]:
    """List all available profiles across search dirs."""
    seen: set = set()
    profiles: List[ProfileConfig] = []

    for search_dir in _search_dirs(extra_dirs):
        if not search_dir.is_dir():
            continue
        for yaml_file in sorted(search_dir.glob("*.yaml")):
            name = yaml_file.stem
            if name not in seen:
                seen.add(name)
                try:
                    profiles.append(_parse_profile(yaml_file))
                except (ValueError, Exception):
                    pass  # Skip malformed profiles in listing

    return profiles


def _parse_profile(path: Path) -> ProfileConfig:
    """Parse and validate a single profile YAML file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"Profile {path} must be a YAML mapping, got {type(raw).__name__}")

    if "name" not in raw:
        raise ValueError(f"Profile {path} missing required field: name")
    if "description" not in raw:
        raise ValueError(f"Profile {path} missing required field: description")

    try:
        return ProfileConfig(**raw)
    except Exception as exc:
        raise ValueError(f"Profile validation error in {path}: {exc}") from exc
