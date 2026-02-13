"""
Multi-Client Configuration Management (R6).

Detects installed MCP clients, writes per-client configuration, and synchronises
server entries across all detected clients so they stay in lock-step.

Supported clients
-----------------
* Claude Desktop  (macOS / Linux / Windows)
* Claude Code     (.mcp.json in project tree)
* Cursor          (~/.cursor/mcp.json)
* VS Code         (~/.vscode/mcp.json  OR  {workspace}/.vscode/mcp.json)
* Windsurf        (~/.windsurf/mcp.json  OR  ~/.codeium/windsurf/mcp.json)
* Zed             (~/.config/zed/settings.json  -- ``context_servers`` key)
"""

from __future__ import annotations

import json
import logging
import os
import platform
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    ClientType,
    ConfigDrift,
    ConfigSyncResult,
    DetectedClient,
    MCPConfigEntry,
    MCPConfiguration,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _home() -> Path:
    """Return the user home directory as a *Path*."""
    return Path.home()


def _appdata() -> Path:
    """Return the Windows ``%APPDATA%`` directory (falls back to home)."""
    raw = os.environ.get("APPDATA")
    if raw:
        return Path(raw)
    return _home() / "AppData" / "Roaming"


def _read_json(path: Path) -> Dict[str, Any]:
    """Read a JSON file and return its contents as a dictionary.

    Returns an empty dict when the file does not exist or cannot be parsed.
    """
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return {}


def _write_json(path: Path, data: Dict[str, Any]) -> bool:
    """Atomically write *data* as pretty-printed JSON to *path*.

    Creates parent directories as needed.  Returns ``True`` on success.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        return True
    except OSError as exc:
        logger.error("Failed to write %s: %s", path, exc)
        return False


# ---------------------------------------------------------------------------
# Client path resolution
# ---------------------------------------------------------------------------

_SYSTEM = platform.system()  # "Darwin", "Linux", "Windows"


def _claude_desktop_config_path() -> Path:
    """Return the expected Claude Desktop config path for this platform."""
    if _SYSTEM == "Darwin":
        return _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if _SYSTEM == "Windows":
        return _appdata() / "Claude" / "claude_desktop_config.json"
    # Linux (and other POSIX)
    return _home() / ".config" / "Claude" / "claude_desktop_config.json"


def _claude_code_config_path() -> Optional[Path]:
    """Walk from cwd upward looking for ``.mcp.json``; return the first hit."""
    current = Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / ".mcp.json"
        if candidate.is_file():
            return candidate
    return None


def _cursor_config_path() -> Path:
    return _home() / ".cursor" / "mcp.json"


def _vscode_config_paths() -> List[Path]:
    """Return candidate VS Code config paths (global + workspace)."""
    paths: List[Path] = [_home() / ".vscode" / "mcp.json"]
    # Workspace-local path
    workspace_candidate = Path.cwd() / ".vscode" / "mcp.json"
    if workspace_candidate.is_file():
        paths.insert(0, workspace_candidate)
    return paths


def _windsurf_config_paths() -> List[Path]:
    """Return candidate Windsurf config paths."""
    return [
        _home() / ".windsurf" / "mcp.json",
        _home() / ".codeium" / "windsurf" / "mcp.json",
    ]


def _zed_settings_path() -> Path:
    return _home() / ".config" / "zed" / "settings.json"


# ---------------------------------------------------------------------------
# ClientManager
# ---------------------------------------------------------------------------

class ClientManager:
    """Detect MCP clients, write per-client configuration, and sync drift.

    All public methods are **synchronous** (pathlib + json) -- they can be
    called from both sync and async contexts without an event loop.
    """

    # Display names used in ``DetectedClient.name``
    _DISPLAY_NAMES: Dict[ClientType, str] = {
        ClientType.CLAUDE_DESKTOP: "Claude Desktop",
        ClientType.CLAUDE_CODE: "Claude Code",
        ClientType.CURSOR: "Cursor",
        ClientType.VSCODE: "VS Code",
        ClientType.WINDSURF: "Windsurf",
        ClientType.ZED: "Zed",
    }

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect_clients(self) -> List[DetectedClient]:
        """Detect which MCP clients are installed on this machine.

        A client is considered *installed* when its expected configuration
        file (or parent directory) exists on disk.
        """
        detected: List[DetectedClient] = []

        for client_type, resolver in self._client_resolvers().items():
            try:
                result = resolver()
                if result is not None:
                    detected.append(result)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error detecting %s: %s", client_type.value, exc)

        logger.info(
            "Detected %d MCP client(s): %s",
            len(detected),
            ", ".join(c.name for c in detected),
        )
        return detected

    def _client_resolvers(self) -> Dict[ClientType, Any]:
        """Map each ``ClientType`` to a callable that returns
        ``DetectedClient | None``."""
        return {
            ClientType.CLAUDE_DESKTOP: self._detect_claude_desktop,
            ClientType.CLAUDE_CODE: self._detect_claude_code,
            ClientType.CURSOR: self._detect_cursor,
            ClientType.VSCODE: self._detect_vscode,
            ClientType.WINDSURF: self._detect_windsurf,
            ClientType.ZED: self._detect_zed,
        }

    # -- individual detectors ------------------------------------------

    def _detect_claude_desktop(self) -> Optional[DetectedClient]:
        path = _claude_desktop_config_path()
        if not path.exists() and not path.parent.is_dir():
            return None
        servers = self._servers_from_mcp_format(path)
        return DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            name=self._DISPLAY_NAMES[ClientType.CLAUDE_DESKTOP],
            config_path=str(path),
            installed=path.is_file(),
            configured_servers=servers,
        )

    def _detect_claude_code(self) -> Optional[DetectedClient]:
        path = _claude_code_config_path()
        if path is None:
            return None
        servers = self._servers_from_mcp_format(path)
        return DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            name=self._DISPLAY_NAMES[ClientType.CLAUDE_CODE],
            config_path=str(path),
            installed=True,
            configured_servers=servers,
        )

    def _detect_cursor(self) -> Optional[DetectedClient]:
        path = _cursor_config_path()
        if not path.exists() and not path.parent.is_dir():
            return None
        servers = self._servers_from_mcp_format(path)
        return DetectedClient(
            client_type=ClientType.CURSOR,
            name=self._DISPLAY_NAMES[ClientType.CURSOR],
            config_path=str(path),
            installed=path.is_file() or path.parent.is_dir(),
            configured_servers=servers,
        )

    def _detect_vscode(self) -> Optional[DetectedClient]:
        for path in _vscode_config_paths():
            if path.is_file() or path.parent.is_dir():
                servers = self._servers_from_mcp_format(path)
                return DetectedClient(
                    client_type=ClientType.VSCODE,
                    name=self._DISPLAY_NAMES[ClientType.VSCODE],
                    config_path=str(path),
                    installed=path.is_file() or path.parent.is_dir(),
                    configured_servers=servers,
                )
        return None

    def _detect_windsurf(self) -> Optional[DetectedClient]:
        for path in _windsurf_config_paths():
            if path.is_file() or path.parent.is_dir():
                servers = self._servers_from_mcp_format(path)
                return DetectedClient(
                    client_type=ClientType.WINDSURF,
                    name=self._DISPLAY_NAMES[ClientType.WINDSURF],
                    config_path=str(path),
                    installed=path.is_file() or path.parent.is_dir(),
                    configured_servers=servers,
                )
        return None

    def _detect_zed(self) -> Optional[DetectedClient]:
        path = _zed_settings_path()
        if not path.exists() and not path.parent.is_dir():
            return None
        data = _read_json(path)
        servers = list(data.get("context_servers", {}).keys())
        return DetectedClient(
            client_type=ClientType.ZED,
            name=self._DISPLAY_NAMES[ClientType.ZED],
            config_path=str(path),
            installed=path.is_file() or path.parent.is_dir(),
            configured_servers=servers,
        )

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure_server_for_client(
        self,
        client: ClientType,
        server_name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Write a server entry into the configuration file for *client*.

        The method reads any existing config, merges the new server entry,
        and writes back -- preserving all other settings.

        Returns ``True`` on success, ``False`` on failure.
        """
        args = args or []
        env = env or {}

        config_path = self._config_path_for_client(client)
        if config_path is None:
            logger.error("Cannot resolve config path for client %s", client.value)
            return False

        logger.info(
            "Configuring server '%s' for %s at %s",
            server_name,
            client.value,
            config_path,
        )

        if client == ClientType.ZED:
            return self._configure_zed(config_path, server_name, command, args, env)

        return self._configure_standard(config_path, server_name, command, args, env)

    # -- standard mcpServers format ------------------------------------

    def _configure_standard(
        self,
        config_path: Path,
        server_name: str,
        command: str,
        args: List[str],
        env: Dict[str, str],
    ) -> bool:
        """Add/update a server in the standard ``mcpServers`` format."""
        data = _read_json(config_path)
        data.setdefault("mcpServers", {})

        entry: Dict[str, Any] = {"command": command, "args": args}
        if env:
            entry["env"] = env
        data["mcpServers"][server_name] = entry

        ok = _write_json(config_path, data)
        if ok:
            logger.info("Server '%s' written to %s", server_name, config_path)
        return ok

    # -- Zed settings.json (context_servers) ---------------------------

    def _configure_zed(
        self,
        config_path: Path,
        server_name: str,
        command: str,
        args: List[str],
        env: Dict[str, str],
    ) -> bool:
        """Add/update a server inside Zed's ``context_servers`` key.

        We take care **not** to clobber any other settings in the file.
        """
        data = _read_json(config_path)
        data.setdefault("context_servers", {})

        entry: Dict[str, Any] = {"command": command, "args": args}
        if env:
            entry["env"] = env
        data["context_servers"][server_name] = entry

        ok = _write_json(config_path, data)
        if ok:
            logger.info("Server '%s' written to Zed settings at %s", server_name, config_path)
        return ok

    # ------------------------------------------------------------------
    # Config drift detection and synchronisation
    # ------------------------------------------------------------------

    def sync_configurations(self, sync: bool = False) -> ConfigSyncResult:
        """Detect configuration drift and optionally repair it.

        1. Detect all installed clients.
        2. Build a union of every server name across all clients.
        3. For each server, note which clients have it and which do not.
        4. If *sync* is ``True``, copy the missing entries from a client
           that has the server to each client that lacks it.

        Returns a :class:`ConfigSyncResult` summarising the outcome.
        """
        clients = self.detect_clients()

        if len(clients) < 2:
            return ConfigSyncResult(
                drift=[],
                synced=0,
                action="Need at least two detected clients to check drift.",
            )

        # Map: server_name -> {client_type_value: "configured" | "missing"}
        # Also keep the full config payload keyed by server_name from any
        # client that *has* it, so we can replicate later.
        all_servers: Dict[str, Dict[str, str]] = {}
        server_configs: Dict[str, Dict[str, Any]] = {}

        for client in clients:
            config_data = _read_json(Path(client.config_path))
            if client.client_type == ClientType.ZED:
                client_servers = config_data.get("context_servers", {})
            else:
                client_servers = config_data.get("mcpServers", {})

            # Seed every known server with "missing" for all clients
            for srv_name in client_servers:
                if srv_name not in all_servers:
                    all_servers[srv_name] = {
                        c.client_type.value: "missing" for c in clients
                    }
                # Keep the first config payload we encounter
                if srv_name not in server_configs:
                    server_configs[srv_name] = deepcopy(client_servers[srv_name])

            # Mark servers present in *this* client
            for srv_name in client_servers:
                all_servers[srv_name][client.client_type.value] = "configured"

        # Ensure all servers have entries for every detected client
        for srv_name in all_servers:
            for client in clients:
                all_servers[srv_name].setdefault(client.client_type.value, "missing")

        # Build drift list (only servers that are *not* present everywhere)
        drift: List[ConfigDrift] = []
        for srv_name, status_map in sorted(all_servers.items()):
            if "missing" in status_map.values():
                drift.append(ConfigDrift(server=srv_name, status=status_map))

        synced_count = 0

        if sync and drift:
            synced_count = self._apply_sync(clients, drift, server_configs)

        if not drift:
            action = "All clients are in sync."
        elif sync:
            action = f"Synced {synced_count} server configuration(s) across clients."
        else:
            action = (
                f"Found {len(drift)} server(s) with configuration drift. "
                "Re-run with sync=True to repair."
            )

        logger.info(
            "Drift check complete: %d drifted, %d synced", len(drift), synced_count
        )
        return ConfigSyncResult(drift=drift, synced=synced_count, action=action)

    def _apply_sync(
        self,
        clients: List[DetectedClient],
        drift: List[ConfigDrift],
        server_configs: Dict[str, Dict[str, Any]],
    ) -> int:
        """Push missing server entries to clients that lack them.

        Returns the number of individual writes performed.
        """
        synced = 0
        client_map = {c.client_type.value: c for c in clients}

        for item in drift:
            srv_name = item.server
            cfg = server_configs.get(srv_name)
            if cfg is None:
                logger.warning("No source config found for server '%s'; skipping", srv_name)
                continue

            command = cfg.get("command", "")
            args = cfg.get("args", [])
            env = cfg.get("env", {})

            for client_key, status in item.status.items():
                if status == "missing":
                    client = client_map.get(client_key)
                    if client is None:
                        continue
                    ok = self.configure_server_for_client(
                        ClientType(client_key),
                        srv_name,
                        command,
                        args,
                        env,
                    )
                    if ok:
                        synced += 1
                    else:
                        logger.warning(
                            "Failed to sync server '%s' to %s",
                            srv_name,
                            client_key,
                        )
        return synced

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _servers_from_mcp_format(self, path: Path) -> List[str]:
        """Extract server names from a standard ``mcpServers`` config file."""
        data = _read_json(path)
        return list(data.get("mcpServers", {}).keys())

    def _config_path_for_client(self, client: ClientType) -> Optional[Path]:
        """Resolve the configuration file path for the given *client*."""
        if client == ClientType.CLAUDE_DESKTOP:
            return _claude_desktop_config_path()

        if client == ClientType.CLAUDE_CODE:
            path = _claude_code_config_path()
            # If nothing found, default to cwd/.mcp.json
            return path if path is not None else Path.cwd() / ".mcp.json"

        if client == ClientType.CURSOR:
            return _cursor_config_path()

        if client == ClientType.VSCODE:
            paths = _vscode_config_paths()
            # Prefer an existing file; otherwise fall back to global location
            for p in paths:
                if p.is_file():
                    return p
            return paths[-1]

        if client == ClientType.WINDSURF:
            paths = _windsurf_config_paths()
            for p in paths:
                if p.is_file():
                    return p
            return paths[0]

        if client == ClientType.ZED:
            return _zed_settings_path()

        logger.error("Unknown client type: %s", client)
        return None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_default_manager: Optional[ClientManager] = None


def _get_manager() -> ClientManager:
    global _default_manager  # noqa: PLW0603
    if _default_manager is None:
        _default_manager = ClientManager()
    return _default_manager


def detect_clients() -> List[DetectedClient]:
    """Detect which MCP clients are installed on this machine."""
    return _get_manager().detect_clients()


def configure_server_for_client(
    client: ClientType,
    server_name: str,
    command: str,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
) -> bool:
    """Write a server entry into *client*'s config file."""
    return _get_manager().configure_server_for_client(
        client, server_name, command, args, env
    )


def sync_configurations(sync: bool = False) -> ConfigSyncResult:
    """Detect configuration drift across all clients, optionally repairing."""
    return _get_manager().sync_configurations(sync=sync)
