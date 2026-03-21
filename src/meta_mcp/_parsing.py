"""
Shared parsing helpers for skill and repository modules.

Centralises SKILL.md parsing, name normalisation, and list coercion so that
``skills.py`` and ``skill_repo.py`` share one canonical implementation.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

FRONTMATTER_DELIMITER = "---"


def parse_skill_md(path: Path) -> Optional[Dict[str, Any]]:
    """Parse a SKILL.md file, returning frontmatter dict and body text.

    Returns ``None`` when the file cannot be read or parsed.  The returned
    dict always contains at minimum ``_body`` (the markdown below the
    frontmatter) and ``_path`` (the resolved file path).
    """
    import logging

    logger = logging.getLogger(__name__)

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


def coerce_list(value: Any) -> List[str]:
    """Coerce a value to a list of strings (handles comma-separated strings)."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if v]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def normalise_name(name: str) -> str:
    """Normalise a skill/server name to a filesystem-safe, lowercase form."""
    basename = name.rsplit("/", 1)[-1] if "/" in name else name
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", basename)
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe.lower() or "unnamed-skill"
