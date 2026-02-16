"""Tests for Post-Install Verification Loop (R3)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.meta_mcp.verification import (
    ServerVerifier,
)
from src.meta_mcp.models import HealthStatus, MCPConfigEntry


# -- Helpers -----------------------------------------------------------------

def _make_jsonrpc_response(result=None, error=None, req_id=1):
    """Build a JSON-RPC 2.0 response as bytes."""
    msg = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result or {}
    return (json.dumps(msg) + "\n").encode("utf-8")


def _make_mock_process(
    returncode=None,
    stdout_lines=None,
    stderr=b"",
):
    """Create a mock subprocess with configurable stdout lines."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.pid = 42

    # stdin
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()

    # stdout — returns lines in order, then EOF
    lines = list(stdout_lines or [])
    line_iter = iter(lines)

    async def _readline():
        try:
            return next(line_iter)
        except StopIteration:
            return b""

    proc.stdout = MagicMock()
    proc.stdout.readline = AsyncMock(side_effect=_readline)

    # stderr
    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(return_value=stderr)

    proc.communicate = AsyncMock(return_value=(b"", stderr))
    proc.wait = AsyncMock(return_value=0)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()

    return proc


# -- Tests -------------------------------------------------------------------


class TestBuildResult:
    """Verdict logic in _build_result."""

    def test_fully_operational(self):
        v = ServerVerifier()
        r = v._build_result(
            process_started=True,
            mcp_handshake=True,
            tools_discovered=["tool1"],
            smoke_test=None,
            errors=[],
        )
        assert r.verdict == "fully_operational"

    def test_failed_no_process(self):
        v = ServerVerifier()
        r = v._build_result(
            process_started=False,
            mcp_handshake=False,
            tools_discovered=[],
            smoke_test=None,
            errors=["spawn failed"],
        )
        assert r.verdict == "failed"

    def test_failed_no_handshake(self):
        v = ServerVerifier()
        r = v._build_result(
            process_started=True,
            mcp_handshake=False,
            tools_discovered=[],
            smoke_test=None,
            errors=["handshake failed"],
        )
        assert r.verdict == "failed"

    def test_partially_working_with_errors(self):
        v = ServerVerifier()
        r = v._build_result(
            process_started=True,
            mcp_handshake=True,
            tools_discovered=["t1"],
            smoke_test=None,
            errors=["minor issue"],
        )
        assert r.verdict == "partially_working"


class TestSelfHeal:
    """Self-heal pattern matching and suggestions."""

    async def test_missing_binary_match(self):
        v = ServerVerifier()
        result = await v.self_heal("srv", "ENOENT: not found", "missing-cmd")
        assert result["category"] == "missing_binary"
        assert result["suggestion"]

    async def test_permission_match(self):
        v = ServerVerifier()
        result = await v.self_heal("srv", "EACCES: Permission denied", "cmd")
        assert result["category"] == "permission"

    async def test_missing_module_match(self):
        v = ServerVerifier()
        result = await v.self_heal("srv", "Cannot find module '@mcp/server'", "npx")
        assert result["category"] == "missing_node_module"

    async def test_missing_credentials_match(self):
        v = ServerVerifier()
        result = await v.self_heal("srv", "Unauthorized: API key missing", "cmd")
        assert result["category"] == "missing_credentials"

    async def test_unknown_error(self):
        v = ServerVerifier()
        result = await v.self_heal("srv", "something completely random xyzzy", "cmd")
        assert result["category"] == "unknown"
        assert "unrecognised" in result["suggestion"].lower()

    async def test_port_conflict(self):
        v = ServerVerifier()
        result = await v.self_heal("srv", "EADDRINUSE: address already in use", "cmd")
        assert result["category"] == "port_conflict"

    async def test_timeout_error(self):
        v = ServerVerifier()
        result = await v.self_heal("srv", "ETIMEDOUT during startup", "cmd")
        assert result["category"] == "timeout"


class TestPickSimpleTool:
    """Tool selection for smoke testing."""

    def test_prefers_zero_params(self):
        v = ServerVerifier()
        tools = [
            {"name": "complex", "inputSchema": {"properties": {"x": {"type": "string"}}, "required": ["x"]}},
            {"name": "simple", "inputSchema": {"properties": {}, "required": []}},
        ]
        picked = v._pick_simple_tool(tools)
        assert picked["name"] == "simple"

    def test_accepts_simple_string_param(self):
        v = ServerVerifier()
        tools = [
            {"name": "query", "inputSchema": {
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            }},
        ]
        picked = v._pick_simple_tool(tools)
        assert picked["name"] == "query"

    def test_empty_tools_returns_none(self):
        v = ServerVerifier()
        assert v._pick_simple_tool([]) is None

    def test_fallback_to_first_tool(self):
        v = ServerVerifier()
        tools = [
            {"name": "complex", "inputSchema": {
                "properties": {"obj": {"type": "object"}, "arr": {"type": "array"}},
                "required": ["obj", "arr", "extra"],
            }},
        ]
        picked = v._pick_simple_tool(tools)
        assert picked["name"] == "complex"


class TestBuildTestInput:
    """Test input generation for different parameter types."""

    def test_string_param(self):
        v = ServerVerifier()
        tool = {"inputSchema": {
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }}
        inp = v._build_test_input(tool)
        assert inp == {"q": "test"}

    def test_integer_param(self):
        v = ServerVerifier()
        tool = {"inputSchema": {
            "properties": {"n": {"type": "integer"}},
            "required": ["n"],
        }}
        inp = v._build_test_input(tool)
        assert inp == {"n": 1}

    def test_boolean_param(self):
        v = ServerVerifier()
        tool = {"inputSchema": {
            "properties": {"flag": {"type": "boolean"}},
            "required": ["flag"],
        }}
        inp = v._build_test_input(tool)
        assert inp == {"flag": True}

    def test_no_required_params(self):
        v = ServerVerifier()
        tool = {"inputSchema": {"properties": {"opt": {"type": "string"}}}}
        inp = v._build_test_input(tool)
        assert inp == {}


class TestEcosystemHealth:
    """Ecosystem-wide health check."""

    async def test_empty_config(self):
        v = ServerVerifier()
        result = await v.check_ecosystem_health({})
        assert result.summary["healthy"] == 0
        assert result.summary["unhealthy"] == 0
        assert len(result.servers) == 0

    async def test_health_check_with_failed_server(self):
        v = ServerVerifier(timeout=1)
        config = {
            "fake-server": MCPConfigEntry(
                command="nonexistent-binary-xyz",
                args=[],
            ),
        }
        with patch("shutil.which", return_value=None):
            result = await v.check_ecosystem_health(config)
        assert len(result.servers) == 1
        assert result.servers[0].status in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED)
