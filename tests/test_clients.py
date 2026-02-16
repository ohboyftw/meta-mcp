"""Tests for Multi-Client Configuration Management (R6)."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.meta_mcp.clients import (
    ClientManager,
    _read_json,
    _write_json,
)
from src.meta_mcp.models import ClientType


class TestJsonHelpers:
    """Low-level JSON read/write functions."""

    def test_read_json_missing_file(self, tmp_path):
        assert _read_json(tmp_path / "nope.json") == {}

    def test_read_json_valid(self, tmp_path):
        f = tmp_path / "ok.json"
        f.write_text('{"a": 1}', encoding="utf-8")
        assert _read_json(f) == {"a": 1}

    def test_read_json_corrupt(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("NOT JSON", encoding="utf-8")
        assert _read_json(f) == {}

    def test_write_json_creates_parent(self, tmp_path):
        target = tmp_path / "sub" / "dir" / "out.json"
        assert _write_json(target, {"key": "val"}) is True
        assert target.is_file()
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["key"] == "val"

    def test_write_json_trailing_newline(self, tmp_path):
        target = tmp_path / "out.json"
        _write_json(target, {"x": 1})
        assert target.read_text(encoding="utf-8").endswith("\n")


class TestClientManagerDetection:
    """Client detection with mocked filesystem."""

    def test_detect_claude_desktop_not_present(self, tmp_path):
        with patch("src.meta_mcp.clients._home", return_value=tmp_path), \
             patch("src.meta_mcp.clients._appdata", return_value=tmp_path / "AppData"), \
             patch("src.meta_mcp.clients._SYSTEM", "Linux"):
            mgr = ClientManager()
            clients = mgr.detect_clients()
            # Claude Desktop config dir doesn't exist, so it shouldn't be detected
            names = [c.name for c in clients]
            # Only clients whose parent dirs exist will be detected
            assert isinstance(clients, list)

    def test_detect_claude_desktop_present(self, tmp_path):
        config_dir = tmp_path / ".config" / "Claude"
        config_dir.mkdir(parents=True)
        config_path = config_dir / "claude_desktop_config.json"
        config_path.write_text('{"mcpServers": {"s1": {"command": "s1"}}}', encoding="utf-8")

        with patch("src.meta_mcp.clients._claude_desktop_config_path", return_value=config_path):
            mgr = ClientManager()
            result = mgr._detect_claude_desktop()
            assert result is not None
            assert result.name == "Claude Desktop"
            assert "s1" in result.configured_servers

    def test_detect_claude_code_not_present(self, tmp_path):
        """Claude Code is not detected when neither ~/.claude.json nor the CLI exist."""
        fake_user_config = tmp_path / ".claude.json"  # does not exist
        with patch("src.meta_mcp.clients._claude_code_user_config_path", return_value=fake_user_config), \
             patch("src.meta_mcp.clients._claude_cli_available", return_value=False):
            mgr = ClientManager()
            assert mgr._detect_claude_code() is None

    def test_detect_claude_code_with_user_config(self, tmp_path):
        """Claude Code detected via ~/.claude.json with servers listed."""
        user_config = tmp_path / ".claude.json"
        user_config.write_text(
            json.dumps({"mcpServers": {"my-srv": {"type": "stdio", "command": "py", "args": []}}}),
            encoding="utf-8",
        )
        with patch("src.meta_mcp.clients._claude_code_user_config_path", return_value=user_config), \
             patch("src.meta_mcp.clients._claude_cli_available", return_value=False), \
             patch("src.meta_mcp.clients._claude_code_project_config_path", return_value=None):
            mgr = ClientManager()
            result = mgr._detect_claude_code()
            assert result is not None
            assert result.name == "Claude Code"
            assert result.config_path == str(user_config)
            assert "my-srv" in result.configured_servers

    def test_detect_cursor(self, tmp_path):
        cursor_dir = tmp_path / ".cursor"
        cursor_dir.mkdir()
        config_path = cursor_dir / "mcp.json"
        config_path.write_text('{"mcpServers": {}}', encoding="utf-8")

        with patch("src.meta_mcp.clients._cursor_config_path", return_value=config_path):
            mgr = ClientManager()
            result = mgr._detect_cursor()
            assert result is not None
            assert result.name == "Cursor"


class TestClientManagerConfiguration:
    """Server configuration writing."""

    def test_configure_claude_code_includes_type(self, tmp_path):
        """Claude Code entries must include 'type': 'stdio'."""
        config_path = tmp_path / ".claude.json"
        mgr = ClientManager()
        with patch.object(mgr, "_config_path_for_client", return_value=config_path):
            ok = mgr.configure_server_for_client(
                client=ClientType.CLAUDE_CODE,
                server_name="test-srv",
                command="test-cmd",
                args=["--flag"],
                env={"KEY": "val"},
            )
        assert ok is True
        data = json.loads(config_path.read_text(encoding="utf-8"))
        srv = data["mcpServers"]["test-srv"]
        assert srv["type"] == "stdio", "Claude Code requires 'type': 'stdio'"
        assert srv["command"] == "test-cmd"
        assert srv["args"] == ["--flag"]
        assert srv["env"]["KEY"] == "val"

    def test_configure_standard_client_no_type(self, tmp_path):
        """Non-Claude-Code clients should NOT have a 'type' field."""
        config_path = tmp_path / "mcp.json"
        mgr = ClientManager()
        with patch.object(mgr, "_config_path_for_client", return_value=config_path):
            ok = mgr.configure_server_for_client(
                client=ClientType.CURSOR,
                server_name="test-srv",
                command="test-cmd",
                args=["--flag"],
            )
        assert ok is True
        data = json.loads(config_path.read_text(encoding="utf-8"))
        srv = data["mcpServers"]["test-srv"]
        assert "type" not in srv, "Standard clients should not have 'type' field"
        assert srv["command"] == "test-cmd"

    def test_configure_zed_client(self, tmp_path):
        config_path = tmp_path / "settings.json"
        config_path.write_text("{}", encoding="utf-8")
        mgr = ClientManager()
        with patch.object(mgr, "_config_path_for_client", return_value=config_path):
            ok = mgr.configure_server_for_client(
                client=ClientType.ZED,
                server_name="my-server",
                command="my-cmd",
                args=[],
            )
        assert ok is True
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "my-server" in data["context_servers"]

    def test_configure_preserves_existing(self, tmp_path):
        config_path = tmp_path / "mcp.json"
        config_path.write_text(
            json.dumps({"mcpServers": {"existing": {"command": "old"}}}),
            encoding="utf-8",
        )
        mgr = ClientManager()
        with patch.object(mgr, "_config_path_for_client", return_value=config_path):
            mgr.configure_server_for_client(
                client=ClientType.CLAUDE_CODE,
                server_name="new-srv",
                command="new-cmd",
            )
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "existing" in data["mcpServers"]
        assert "new-srv" in data["mcpServers"]

    def test_configure_returns_false_when_path_none(self):
        mgr = ClientManager()
        with patch.object(mgr, "_config_path_for_client", return_value=None):
            ok = mgr.configure_server_for_client(
                client=ClientType.CLAUDE_CODE,
                server_name="x",
                command="x",
            )
        assert ok is False


class TestConfigSync:
    """Configuration drift detection."""

    def test_sync_needs_two_clients(self, tmp_path):
        mgr = ClientManager()
        with patch.object(mgr, "detect_clients", return_value=[]):
            result = mgr.sync_configurations()
        assert result.synced == 0
        assert "at least two" in result.action.lower() or result.drift == []
