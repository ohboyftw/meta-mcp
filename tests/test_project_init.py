"""Tests for project_init module."""

import json
import logging
import platform
from pathlib import Path
from unittest.mock import patch

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


def test_resolve_template_missing_key_warns(caplog):
    """Unresolved template variables produce a warning."""
    with caplog.at_level(logging.WARNING, logger="meta_mcp.project_init"):
        result = _resolve_template("{typo_var}/path", {"project_root": "/tmp"})
    assert "{typo_var}" in result
    assert "typo_var" in caplog.text


def test_resolve_template_missing_key_no_warn():
    """warn_missing=False suppresses the warning."""
    result = _resolve_template("{typo_var}/path", {"project_root": "/tmp"}, warn_missing=False)
    assert "{typo_var}" in result


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


def _write_profile(tmp_path, name="test", servers=None):
    """Helper: write a profile YAML that ``load_profile`` can find."""
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir(exist_ok=True)
    servers_yaml = ""
    for s in (servers or []):
        servers_yaml += f"""
  - name: {s["name"]}
    auto_install: {str(s.get("auto_install", False)).lower()}
    command: "{s.get("command", "")}"
    args: {json.dumps(s.get("args", []))}
"""
    (profile_dir / f"{name}.yaml").write_text(
        f"name: {name}\ndescription: test profile\nservers:{servers_yaml}\n"
    )
    return profile_dir


def test_init_skips_existing_server(tmp_path, initializer):
    existing = {"mcpServers": {"beacon": {"command": "old-beacon"}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(existing))

    profile_dir = _write_profile(tmp_path, name="myprof", servers=[
        {"name": "beacon", "auto_install": True, "command": "py", "args": ["-m", "beacon"]},
    ])

    with patch("meta_mcp.project_init.load_profile") as mock_lp:
        from meta_mcp.profiles import load_profile as _real_load
        mock_lp.side_effect = lambda name, **kw: _real_load(name, extra_dirs=[profile_dir.parent])
        result = initializer.initialize_project(
            project_root=str(tmp_path),
            servers=["beacon"],
            profile="myprof",
            validate_env=False,
        )
    assert "beacon" in result.servers_skipped
    assert "beacon" not in result.servers_configured
    # Original entry preserved
    mcp_json = json.loads((tmp_path / ".mcp.json").read_text())
    assert mcp_json["mcpServers"]["beacon"]["command"] == "old-beacon"


def test_init_writes_new_server_to_mcp_json(tmp_path, initializer):
    """Core regression: new servers must actually appear in .mcp.json."""
    profile_dir = _write_profile(tmp_path, name="myprof", servers=[
        {"name": "beacon", "auto_install": True, "command": "py", "args": ["-m", "beacon_mcp"]},
    ])

    with patch("meta_mcp.project_init.load_profile") as mock_lp:
        from meta_mcp.profiles import load_profile as _real_load
        mock_lp.side_effect = lambda name, **kw: _real_load(name, extra_dirs=[profile_dir.parent])
        result = initializer.initialize_project(
            project_root=str(tmp_path),
            servers=["beacon"],
            profile="myprof",
            validate_env=False,
        )

    assert "beacon" in result.servers_configured
    mcp_json = json.loads((tmp_path / ".mcp.json").read_text())
    assert "beacon" in mcp_json["mcpServers"]
    assert mcp_json["mcpServers"]["beacon"]["command"] == "py"
    assert mcp_json["mcpServers"]["beacon"]["args"] == ["-m", "beacon_mcp"]


def test_init_warns_when_no_command(tmp_path, initializer):
    """Servers without a command in the profile produce a warning."""
    result = initializer.initialize_project(
        project_root=str(tmp_path),
        servers=["unknown-server"],
        validate_env=False,
    )
    assert "unknown-server" not in result.servers_configured
    assert any("no command defined" in w for w in result.warnings)


def test_init_dry_run(tmp_path, initializer):
    profile_dir = _write_profile(tmp_path, name="myprof", servers=[
        {"name": "beacon", "auto_install": True, "command": "py", "args": ["-m", "beacon_mcp"]},
    ])

    with patch("meta_mcp.project_init.load_profile") as mock_lp:
        from meta_mcp.profiles import load_profile as _real_load
        mock_lp.side_effect = lambda name, **kw: _real_load(name, extra_dirs=[profile_dir.parent])
        result = initializer.initialize_project(
            project_root=str(tmp_path),
            servers=["beacon"],
            profile="myprof",
            dry_run=True,
        )
    assert "beacon" in result.servers_configured
    assert not (tmp_path / ".mcp.json").exists()
    assert any("Dry run" in w for w in result.warnings)


def test_init_settings_updated(tmp_path, initializer):
    profile_dir = _write_profile(tmp_path, name="myprof", servers=[
        {"name": "beacon", "auto_install": True, "command": "py", "args": ["-m", "beacon_mcp"]},
    ])

    with patch("meta_mcp.project_init.load_profile") as mock_lp:
        from meta_mcp.profiles import load_profile as _real_load
        mock_lp.side_effect = lambda name, **kw: _real_load(name, extra_dirs=[profile_dir.parent])
        result = initializer.initialize_project(
            project_root=str(tmp_path),
            servers=["beacon"],
            profile="myprof",
            validate_env=False,
        )
    assert result.settings_updated is True
    settings = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    assert settings["permissions"]["enableAllProjectMcpServers"] is True


# ─── ProjectInitializer.validate_project ──────────────────────────────────────

def test_init_resolves_env_vars(tmp_path, initializer):
    """required_env_from_os values are resolved from os.environ at write time."""
    profile_dir = _write_profile(tmp_path, servers=[
        {"name": "my-srv", "auto_install": True, "command": "node", "args": ["server.js"]},
    ])

    with (
        patch("meta_mcp.project_init.load_profile") as mock_lp,
        patch.dict("os.environ", {"MY_API_KEY": "secret123"}),
    ):
        from meta_mcp.profiles import load_profile as _real_load, ProfileConfig, ProfileServerEntry

        # Build a profile with required_env_from_os
        def _patched_load(name, **kw):
            return ProfileConfig(
                name="test",
                description="test",
                servers=[ProfileServerEntry(
                    name="my-srv",
                    auto_install=True,
                    command="node",
                    args=["server.js"],
                    required_env_from_os=["MY_API_KEY"],
                )],
            )
        mock_lp.side_effect = _patched_load
        result = initializer.initialize_project(
            project_root=str(tmp_path),
            servers=["my-srv"],
            validate_env=True,
        )

    mcp_json = json.loads((tmp_path / ".mcp.json").read_text())
    assert mcp_json["mcpServers"]["my-srv"]["env"]["MY_API_KEY"] == "secret123"
    assert "my-srv" not in result.missing_env_vars


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


