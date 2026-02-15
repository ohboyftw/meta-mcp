"""Tests for project_init module."""

import json
import os
import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from meta_mcp.project_init import (
    KNOWN_PROJECT_SERVERS,
    PROFILES,
    ProjectInitializer,
    _ensure_settings_flag,
    _get_python_command,
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


# ─── Python command ───────────────────────────────────────────────────────────

def test_get_python_command_windows():
    with patch("meta_mcp.project_init.platform") as mock_platform:
        mock_platform.system.return_value = "Windows"
        from meta_mcp.project_init import _get_python_command
        # Re-import won't re-evaluate; test the live function
        if platform.system() == "Windows":
            assert _get_python_command() == "py"
        else:
            assert _get_python_command() == "python3"


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


def test_init_creates_mcp_json(tmp_path, initializer):
    result = initializer.initialize_project(
        project_root=str(tmp_path),
        servers=["beacon"],
        validate_env=False,
    )
    assert "beacon" in result.servers_configured
    mcp_json = json.loads((tmp_path / ".mcp.json").read_text())
    assert "beacon" in mcp_json["mcpServers"]
    # Command should be resolved (no templates)
    assert "{" not in mcp_json["mcpServers"]["beacon"]["command"]


def test_init_merges_existing(tmp_path, initializer):
    # Pre-create .mcp.json with an existing server
    existing = {"mcpServers": {"my-server": {"command": "node", "args": ["server.js"]}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(existing))

    result = initializer.initialize_project(
        project_root=str(tmp_path),
        servers=["beacon"],
        validate_env=False,
    )
    mcp_json = json.loads((tmp_path / ".mcp.json").read_text())
    assert "my-server" in mcp_json["mcpServers"]  # Preserved
    assert "beacon" in mcp_json["mcpServers"]  # Added
    assert "my-server" in result.pre_existing_servers


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


def test_init_profile_resolution(tmp_path, initializer):
    result = initializer.initialize_project(
        project_root=str(tmp_path),
        profile="knowledge-stack",
        validate_env=False,
    )
    assert set(result.servers_configured) == {"beacon", "engram", "rlm"}


def test_init_env_var_validation(tmp_path, initializer):
    with patch.dict(os.environ, {}, clear=False):
        # Remove keys if present
        env = os.environ.copy()
        for key in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                     "MINIMAX_API_KEY", "MOONSHOT_API_KEY"]:
            env.pop(key, None)
        with patch.dict(os.environ, env, clear=True):
            result = initializer.initialize_project(
                project_root=str(tmp_path),
                servers=["llm-council"],
                validate_env=True,
            )
            assert "llm-council" in result.missing_env_vars
            missing = result.missing_env_vars["llm-council"]
            assert "ANTHROPIC_API_KEY" in missing


def test_init_dry_run(tmp_path, initializer):
    result = initializer.initialize_project(
        project_root=str(tmp_path),
        servers=["beacon"],
        dry_run=True,
    )
    assert "beacon" in result.servers_configured
    assert not (tmp_path / ".mcp.json").exists()
    assert any("Dry run" in w for w in result.warnings)


def test_init_unknown_server(tmp_path, initializer):
    result = initializer.initialize_project(
        project_root=str(tmp_path),
        servers=["nonexistent"],
    )
    assert "nonexistent" in result.servers_skipped
    assert any("Unknown" in w for w in result.warnings)


def test_init_settings_updated(tmp_path, initializer):
    result = initializer.initialize_project(
        project_root=str(tmp_path),
        servers=["beacon"],
        validate_env=False,
    )
    assert result.settings_updated is True
    settings = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    assert settings["permissions"]["enableAllProjectMcpServers"] is True


def test_init_engram_project_root_resolved(tmp_path, initializer):
    result = initializer.initialize_project(
        project_root=str(tmp_path),
        servers=["engram"],
        validate_env=False,
    )
    mcp_json = json.loads((tmp_path / ".mcp.json").read_text())
    env = mcp_json["mcpServers"]["engram"]["env"]
    assert env["ENGRAM_PROJECT_ROOT"] == str(tmp_path)
    assert env["MEM0_TELEMETRY"] == "false"


# ─── ProjectInitializer.validate_project ──────────────────────────────────────

def test_validate_no_mcp_json(tmp_path, initializer):
    result = initializer.validate_project(str(tmp_path))
    assert result.has_mcp_json is False
    assert result.overall_healthy is False


def test_validate_healthy_project(tmp_path, initializer):
    # Create a valid .mcp.json with a command that exists
    python_cmd = _get_python_command()
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
                "command": _get_python_command(),
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


# ─── Profiles and catalog ────────────────────────────────────────────────────

def test_profiles_reference_valid_servers():
    for profile_name, server_list in PROFILES.items():
        for server in server_list:
            assert server in KNOWN_PROJECT_SERVERS, (
                f"Profile '{profile_name}' references unknown server '{server}'"
            )


def test_known_servers_have_required_fields():
    for name, defn in KNOWN_PROJECT_SERVERS.items():
        assert defn.name == name
        assert defn.command
        assert defn.args
        assert defn.description
