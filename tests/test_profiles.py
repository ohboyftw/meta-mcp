"""Tests for profile YAML loading and validation."""

import pytest
from pathlib import Path
from meta_mcp.profiles import load_profile, ProfileConfig, ProfileNotFoundError


@pytest.fixture(autouse=True)
def setup_fixtures(tmp_path):
    """Create test profile fixtures under tmp_path/profiles/."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()

    # Valid profile
    (profiles_dir / "test-stack.yaml").write_text(
        "name: test-stack\n"
        "description: Test profile\n"
        "skills:\n  - beacon\n  - engram\n"
        "servers:\n  - name: beacon\n    auto_install: true\n"
        "env_required:\n  - TEST_VAR\n"
        "post_install:\n  - 'Run tests'\n"
    )

    # Minimal valid profile
    (profiles_dir / "minimal.yaml").write_text(
        "name: minimal\ndescription: Minimal test\n"
    )

    # Malformed YAML
    (profiles_dir / "bad.yaml").write_text(
        "name: bad\ndescription: [unterminated\n"
    )

    # Missing required fields
    (profiles_dir / "no-name.yaml").write_text(
        "description: No name field\n"
    )

    return tmp_path  # Return PARENT — _search_dirs appends /profiles


def test_load_valid_profile(setup_fixtures):
    profile = load_profile("test-stack", extra_dirs=[setup_fixtures])
    assert isinstance(profile, ProfileConfig)
    assert profile.name == "test-stack"
    assert profile.description == "Test profile"
    assert profile.skills == ["beacon", "engram"]
    assert len(profile.servers) == 1
    assert profile.servers[0].name == "beacon"
    assert profile.servers[0].auto_install is True
    assert profile.env_required == ["TEST_VAR"]
    assert profile.post_install == ["Run tests"]


def test_load_minimal_profile(setup_fixtures):
    profile = load_profile("minimal", extra_dirs=[setup_fixtures])
    assert profile.name == "minimal"
    assert profile.skills == []
    assert profile.servers == []


def test_load_default_profile():
    profile = load_profile("default", extra_dirs=[])
    assert profile.name == "default"
    assert profile.skills == []


def test_profile_not_found():
    with pytest.raises(ProfileNotFoundError, match="nonexistent"):
        load_profile("nonexistent", extra_dirs=[])


def test_malformed_yaml(setup_fixtures):
    with pytest.raises(ValueError, match="YAML"):
        load_profile("bad", extra_dirs=[setup_fixtures])


def test_missing_required_field(setup_fixtures):
    with pytest.raises(ValueError, match="name"):
        load_profile("no-name", extra_dirs=[setup_fixtures])


def test_discovery_order(setup_fixtures, tmp_path):
    """First match wins — extra_dirs before built-in."""
    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "default.yaml").write_text(
        "name: default\ndescription: Overridden default\n"
    )
    profile = load_profile("default", extra_dirs=[setup_fixtures])
    assert profile.description == "Overridden default"
