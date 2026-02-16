"""
Pytest configuration and shared fixtures for Meta MCP tests.
"""

import json
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp_path = tempfile.mkdtemp()
    yield Path(temp_path)
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def mock_config_paths(temp_dir):
    """Create mock configuration paths in temporary directory."""
    claude_config = temp_dir / "claude_desktop_config.json"
    local_config = temp_dir / ".mcp.json"
    gemini_config = temp_dir / "gemini_config.json"

    # Create directories
    claude_config.parent.mkdir(parents=True, exist_ok=True)
    local_config.parent.mkdir(parents=True, exist_ok=True)
    gemini_config.parent.mkdir(parents=True, exist_ok=True)

    return {
        "claude_desktop": claude_config,
        "local_mcp_json": local_config,
        "gemini": gemini_config,
    }


@pytest.fixture
def sample_server_definitions():
    """Sample server definitions for testing."""
    return {
        "coding": {
            "test-server": {
                "name": "Test Server",
                "description": "A test MCP server",
                "repository_url": "https://github.com/test/server",
                "author": "Test Author",
                "category": "coding",
                "options": {
                    "official": {
                        "install": "echo test-install",
                        "verify_install": "echo test-verify",
                        "integrations": {
                            "claude_desktop": {
                                "config_path": "~/test/claude_desktop_config.json",
                                "config_template": {
                                    "mcpServers": {
                                        "test-server": {
                                            "command": "test-server",
                                            "args": [],
                                            "env": {},
                                        }
                                    }
                                },
                                "restart_required": True,
                                "instructions": "Restart Claude Desktop",
                            },
                            "local_mcp_json": {
                                "config_path": "./.mcp.json",
                                "config_template": {
                                    "mcpServers": {
                                        "test-server": {
                                            "command": "test-server",
                                            "args": [],
                                            "env": {},
                                        }
                                    }
                                },
                                "restart_required": False,
                                "instructions": "Local configuration",
                            },
                        },
                        "env_vars": [
                            {
                                "name": "TEST_API_KEY",
                                "description": "Test API key for authentication",
                                "required": True,
                                "example": "test-key-123",
                            }
                        ],
                        "prerequisites": ["test-dependency"],
                        "platform_support": {
                            "windows": True,
                            "macos": True,
                            "linux": True,
                        },
                    }
                },
            }
        }
    }


@pytest.fixture
def mock_installation_result():
    """Create a mock successful installation result."""
    from src.meta_mcp.models import MCPInstallationResult

    return MCPInstallationResult(
        success=True,
        server_name="test-server",
        option_name="official",
        config_name="test-server-official",
        message="Installation successful",
    )


@pytest.fixture
def memory_file(temp_dir):
    """Create a temporary memory file path for testing."""
    return temp_dir / "memory.json"


@pytest.fixture
def sample_mcp_config():
    """Sample MCP configuration dict for testing."""
    return {
        "mcpServers": {
            "test-server": {
                "command": "npx",
                "args": ["-y", "@test/mcp-server"],
                "env": {"TEST_KEY": "test-value"},
            },
            "another-server": {
                "command": "uvx",
                "args": ["another-server"],
            },
        }
    }


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx.AsyncClient for registry tests."""
    client = AsyncMock()
    client.get = AsyncMock()
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def sample_project_dir(temp_dir):
    """Create a sample project directory with common files."""
    # Create basic project structure
    (temp_dir / "package.json").write_text(
        json.dumps({"name": "test-project", "dependencies": {"react": "^18.0.0"}}),
        encoding="utf-8",
    )
    (temp_dir / ".git").mkdir()
    (temp_dir / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/test/project.git\n',
        encoding="utf-8",
    )
    (temp_dir / ".env.example").write_text(
        "DATABASE_URL=postgres://localhost/test\nAPI_KEY=your-key\n",
        encoding="utf-8",
    )
    return temp_dir


@pytest.fixture
def make_mock_process():
    """Factory fixture for creating mock asyncio subprocess processes."""

    def _make(returncode=0, stdout=b"", stderr=b""):
        process = MagicMock()
        process.returncode = returncode
        process.pid = 12345
        process.stdin = MagicMock()
        process.stdin.write = MagicMock()
        process.stdin.drain = AsyncMock()
        process.stdin.close = MagicMock()
        process.stdout = MagicMock()
        process.stdout.readline = AsyncMock(return_value=b"")
        process.stderr = MagicMock()
        process.stderr.read = AsyncMock(return_value=stderr)
        process.communicate = AsyncMock(return_value=(stdout, stderr))
        process.wait = AsyncMock(return_value=returncode)
        process.terminate = MagicMock()
        process.kill = MagicMock()
        return process

    return _make


@pytest.fixture
def mock_platform_system():
    """Mock platform.system() to return consistent results."""
    with patch("platform.system", return_value="Linux"):
        yield


@pytest.fixture
async def async_mock():
    """Create an async mock for testing async functions."""
    return AsyncMock()


# Pytest configuration
def pytest_configure(config):
    """Configure pytest settings."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (may be slow)"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers."""
    for item in items:
        # Mark integration tests
        if "integration" in item.nodeid.lower():
            item.add_marker(pytest.mark.integration)

        # Mark slow tests
        if any(
            keyword in item.nodeid.lower()
            for keyword in ["integration", "workflow", "end_to_end"]
        ):
            item.add_marker(pytest.mark.slow)
