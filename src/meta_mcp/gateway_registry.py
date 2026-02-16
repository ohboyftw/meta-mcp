"""
Gateway Backend Registry.

Maps backend names to their startup commands. Loaded from
~/.mcp-manager/backends.json (user-configurable, not checked into git).
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY_PATH = Path.home() / ".mcp-manager" / "backends.json"


class BackendConfig(BaseModel):
    """Configuration for a single backend MCP server."""

    command: str = Field(description="Command to execute (e.g. 'py', 'npx')")
    args: List[str] = Field(default_factory=list, description="Command arguments")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    auto_activate: bool = Field(
        False,
        description="Start automatically on gateway init (lightweight servers only)",
    )
    description: str = Field("", description="Human-readable description")
    estimated_tokens: int = Field(
        500,
        description="Estimated token cost when active (for context budget)",
    )


class GatewayRegistry:
    """Manages the mapping from backend names to their startup configurations.

    Reads from ``~/.mcp-manager/backends.json`` on init.  Falls back to an
    empty registry if the file doesn't exist.
    """

    def __init__(self, registry_path: Optional[Path] = None) -> None:
        self._path = registry_path or _DEFAULT_REGISTRY_PATH
        self._backends: Dict[str, BackendConfig] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            logger.info("No backend registry at %s — starting empty", self._path)
            return

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for name, cfg in raw.items():
                try:
                    self._backends[name] = BackendConfig(**cfg)
                except Exception:
                    logger.warning("Skipping invalid backend config for '%s'", name)
            logger.info(
                "Loaded %d backend(s) from %s", len(self._backends), self._path
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to read backend registry: %s", exc)

    def save(self) -> None:
        """Persist current backends to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: cfg.model_dump() for name, cfg in self._backends.items()}
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info("Saved %d backend(s) to %s", len(self._backends), self._path)

    @property
    def backends(self) -> Dict[str, BackendConfig]:
        return dict(self._backends)

    def get(self, name: str) -> Optional[BackendConfig]:
        return self._backends.get(name)

    def add(self, name: str, config: BackendConfig) -> None:
        self._backends[name] = config

    def remove(self, name: str) -> bool:
        return self._backends.pop(name, None) is not None

    def auto_activate_backends(self) -> List[str]:
        """Return names of backends marked for auto-activation."""
        return [name for name, cfg in self._backends.items() if cfg.auto_activate]

    def list_summary(self) -> List[Dict[str, Any]]:
        """Return a summary list for display."""
        return [
            {
                "name": name,
                "command": cfg.command,
                "auto_activate": cfg.auto_activate,
                "description": cfg.description,
                "estimated_tokens": cfg.estimated_tokens,
            }
            for name, cfg in sorted(self._backends.items())
        ]
