"""Tests for project_init module."""

import json
import platform
from pathlib import Path

import pytest

from meta_mcp.project_init import (
    ProjectInitializer,
    _ensure_settings_flag,
    _resolve_template,
)


# ─── Template resolution ─────────────────────────────────────────────────────

def test_resolve_template_basic():
    assert _resolve_template("{project_root}/foo", {"project_root": "/tmp/proj"}) == "/tmp/proj/foo"


def test_resolve_template_multiple():
    ctx = {"project_root": "/proj", "skills_repo": "/skills"}
    assert _resolve_template("{skills_repo}/{project_root}", ctx) == "/skills//proj"


def test_resolve_template_missing_key():
    # Missing keys are left as-is (no crash)
    result = _resolve_template("{unknown}/path", {"project_root": "/tmp"})
    assert "{unknown}" in result


# ─── Settings flag ────────────────────────────────────────────────────────────

def test_ensure_settings_flag_creates_new(tmp_path):
    result = _ensure_settings_flag(tmp_path)
    assert result is True
    settings = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    assert settings["permissions"]["enableAllProjectMcpServers"] is True


def test_ensure_settings_flag_preserves_existing(tmp_path):
    (tmp_path / ".claude").mkdir()
    settings_file = tmp_path / ".claude" / "settings.local.json"
    settings_file.write_text(json.dumps({
        "permissions": {"enableAllProjectMcpServers": True},
        "other": "value",
    }))
    result = _ensure_settings_flag(tmp_path)
    assert result is False  # No change needed
    settings = json.loads(settings_file.read_text())
    assert settings["other"] == "value"


def test_ensure_settings_flag_updates_existing(tmp_path):
    (tmp_path / ".claude").mkdir()
    settings_file = tmp_path / ".claude" / "settings.local.json"
    settings_file.write_text(json.dumps({"permissions": {}, "custom": 42}))
    result = _ensure_settings_flag(tmp_path)
    assert result is True
    settings = json.loads(settings_file.read_text())
    assert settings["permissions"]["enableAllProjectMcpServers"] is True
    assert settings["custom"] == 42


# ─── ProjectInitializer.initialize_project ────────────────────────────────────

@pytest.fixture
def initializer():
    return ProjectInitializer()


def test_init_skips_existing_server(tmp_path, initializer):
    existing = {"mcpServers": {"beacon": {"command": "old-beacon"}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(existing))

    result = initializer.initialize_project(
        project_root=str(tmp_path),
        servers=["beacon"],
        validate_env=False,
    )
    assert "beacon" in result.servers_skipped
    assert "beacon" not in result.servers_configured
    # Original entry preserved
    mcp_json = json.loads((tmp_path / ".mcp.json").read_text())
    assert mcp_json["mcpServers"]["beacon"]["command"] == "old-beacon"


def test_init_dry_run(tmp_path, initializer):
    result = initializer.initialize_project(
        project_root=str(tmp_path),
        servers=["beacon"],
        dry_run=True,
    )
    assert "beacon" in result.servers_configured
    assert not (tmp_path / ".mcp.json").exists()
    assert any("Dry run" in w for w in result.warnings)


def test_init_settings_updated(tmp_path, initializer):
    result = initializer.initialize_project(
        project_root=str(tmp_path),
        servers=["beacon"],
        validate_env=False,
    )
    assert result.settings_updated is True
    settings = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    assert settings["permissions"]["enableAllProjectMcpServers"] is True


# ─── ProjectInitializer.validate_project ──────────────────────────────────────

def test_validate_no_mcp_json(tmp_path, initializer):
    result = initializer.validate_project(str(tmp_path))
    assert result.has_mcp_json is False
    assert result.overall_healthy is False


def test_validate_healthy_project(tmp_path, initializer):
    # Create a valid .mcp.json with a command that exists
    python_cmd = "py" if platform.system() == "Windows" else "python3"
    config = {
        "mcpServers": {
            "test-server": {
                "command": python_cmd,
                "args": ["-c", "print('hello')"],
                "env": {"FOO": "bar"},
            }
        }
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(config))

    # Create settings
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.local.json").write_text(json.dumps({
        "permissions": {"enableAllProjectMcpServers": True}
    }))

    result = initializer.validate_project(str(tmp_path))
    assert result.has_mcp_json is True
    assert result.has_settings_flag is True
    assert "test-server" in result.healthy_servers
    assert result.overall_healthy is True


def test_validate_unhealthy_empty_env(tmp_path, initializer):
    config = {
        "mcpServers": {
            "bad-server": {
                "command": "py" if platform.system() == "Windows" else "python3",
                "args": [],
                "env": {"API_KEY": ""},
            }
        }
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(config))
    _ensure_settings_flag(tmp_path)

    result = initializer.validate_project(str(tmp_path))
    assert "bad-server" in result.unhealthy_servers
    assert "Empty env vars" in result.unhealthy_servers["bad-server"]


def test_validate_unhealthy_missing_command(tmp_path, initializer):
    config = {
        "mcpServers": {
            "ghost": {
                "command": "nonexistent_binary_xyz_12345",
                "args": [],
            }
        }
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(config))
    _ensure_settings_flag(tmp_path)

    result = initializer.validate_project(str(tmp_path))
    assert "ghost" in result.unhealthy_servers
    assert "not found" in result.unhealthy_servers["ghost"]


