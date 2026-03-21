"""Tests for Live Server Orchestration (R8)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.meta_mcp.orchestration import (
    ServerOrchestrator,
    _build_jsonrpc_request,
)
from src.meta_mcp.models import (
    MCPServerStatus,
)


# -- Helpers -----------------------------------------------------------------

def _jsonrpc_response(result=None, error=None, req_id=1):
    """Build a JSON-RPC 2.0 response as a byte line."""
    msg = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result or {}
    return (json.dumps(msg) + "\n").encode("utf-8")


def _mock_process(returncode=None, stdout_lines=None, stderr=b""):
    """Create a mock subprocess with configurable stdout readline."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.pid = 99

    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()

    lines = list(stdout_lines or [])
    line_iter = iter(lines)

    async def _readline():
        try:
            return next(line_iter)
        except StopIteration:
            return b""

    proc.stdout = MagicMock()
    proc.stdout.readline = AsyncMock(side_effect=_readline)

    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(return_value=stderr)

    proc.communicate = AsyncMock(return_value=(b"", stderr))
    proc.wait = AsyncMock(return_value=0)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()

    return proc


# -- Tests: _build_jsonrpc_request ------------------------------------------

class TestBuildJsonrpcRequest:
    """Serialize JSON-RPC 2.0 requests."""

    def test_basic_request(self):
        raw = _build_jsonrpc_request("initialize", request_id=1)
        msg = json.loads(raw.decode("utf-8").strip())
        assert msg["jsonrpc"] == "2.0"
        assert msg["method"] == "initialize"
        assert msg["id"] == 1

    def test_request_with_params(self):
        raw = _build_jsonrpc_request(
            "tools/call",
            params={"name": "my-tool", "arguments": {"q": "test"}},
            request_id=42,
        )
        msg = json.loads(raw.decode("utf-8").strip())
        assert msg["params"]["name"] == "my-tool"
        assert msg["id"] == 42

    def test_request_without_params(self):
        raw = _build_jsonrpc_request("tools/list", request_id=5)
        msg = json.loads(raw.decode("utf-8").strip())
        assert "params" not in msg

    def test_trailing_newline(self):
        raw = _build_jsonrpc_request("test")
        assert raw.endswith(b"\n")


# -- Tests: _extract_tool_output -------------------------------------------

class TestExtractToolOutput:
    """Collapse MCP content lists."""

    def test_single_text_content(self):
        data = {"content": [{"type": "text", "text": "hello"}]}
        assert ServerOrchestrator._extract_tool_output(data) == "hello"

    def test_multiple_text_content(self):
        data = {"content": [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b"},
        ]}
        result = ServerOrchestrator._extract_tool_output(data)
        assert isinstance(result, list)
        assert "a" in result
        assert "b" in result

    def test_non_dict_passthrough(self):
        assert ServerOrchestrator._extract_tool_output("plain") == "plain"

    def test_no_content_key(self):
        data = {"something": "else"}
        assert ServerOrchestrator._extract_tool_output(data) == data

    def test_non_list_content(self):
        data = {"content": "not-a-list"}
        assert ServerOrchestrator._extract_tool_output(data) == data

    def test_mixed_content_types(self):
        data = {"content": [
            {"type": "text", "text": "hello"},
            {"type": "image", "data": "base64..."},
        ]}
        result = ServerOrchestrator._extract_tool_output(data)
        assert isinstance(result, list)


# -- Tests: ServerOrchestrator.start_server --------------------------------

class TestStartServer:
    """Server process lifecycle."""

    async def test_start_server_success(self):
        orch = ServerOrchestrator()
        proc = _mock_process(returncode=None)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc), \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=proc):
            model = await orch.start_server("test-srv", "echo")

        assert model.server_name == "test-srv"
        assert model.status == MCPServerStatus.RUNNING
        assert model.pid == 99

    async def test_start_already_running(self):
        orch = ServerOrchestrator()
        proc = _mock_process(returncode=None)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc), \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=proc):
            await orch.start_server("srv", "echo")
            # Start again -- should return existing
            model = await orch.start_server("srv", "echo")

        assert model.status == MCPServerStatus.RUNNING

    async def test_start_command_not_found(self):
        orch = ServerOrchestrator()

        async def _raise_fnf(*args, **kwargs):
            raise FileNotFoundError("not found")

        with patch("asyncio.wait_for", side_effect=_raise_fnf):
            with pytest.raises(RuntimeError, match="Command not found"):
                await orch.start_server("bad", "nonexistent")

        assert orch.running_servers["bad"].status == MCPServerStatus.ERROR

    async def test_start_timeout(self):
        orch = ServerOrchestrator()

        async def _raise_timeout(*args, **kwargs):
            raise asyncio.TimeoutError()

        with patch("asyncio.wait_for", side_effect=_raise_timeout):
            with pytest.raises(RuntimeError, match="Timed out"):
                await orch.start_server("slow", "cmd")


# -- Tests: ServerOrchestrator.stop_server ---------------------------------

class TestStopServer:
    """Server stop with graceful + forced shutdown."""

    async def test_stop_unknown_raises(self):
        orch = ServerOrchestrator()
        with pytest.raises(KeyError, match="No server tracked"):
            await orch.stop_server("nonexistent")

    async def test_stop_already_exited(self):
        orch = ServerOrchestrator()
        proc = _mock_process(returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc), \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=proc):
            await orch.start_server("srv", "echo")
            # Simulate process already exited
            proc.returncode = 0
            model = await orch.stop_server("srv")

        assert model.status == MCPServerStatus.STOPPED

    async def test_stop_graceful(self):
        orch = ServerOrchestrator()
        proc = _mock_process(returncode=None)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc), \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=proc):
            await orch.start_server("srv", "echo")

        # Make wait return quickly (graceful shutdown)
        proc.wait = AsyncMock(return_value=0)
        with patch("asyncio.wait_for", new_callable=AsyncMock, return_value=0):
            model = await orch.stop_server("srv")

        assert model.status == MCPServerStatus.STOPPED
        proc.terminate.assert_called()


# -- Tests: ServerOrchestrator.restart_server ------------------------------

class TestRestartServer:
    """Restart = stop + start."""

    async def test_restart_unknown_raises(self):
        orch = ServerOrchestrator()
        with pytest.raises(KeyError, match="No server tracked"):
            await orch.restart_server("nonexistent")


# -- Tests: discover_server_tools -----------------------------------------

class TestDiscoverServerTools:
    """Tool discovery via temp process."""

    async def test_discover_command_not_found(self):
        orch = ServerOrchestrator()

        async def _raise_fnf(*args, **kwargs):
            raise FileNotFoundError("nope")

        with patch("asyncio.wait_for", side_effect=_raise_fnf):
            result = await orch.discover_server_tools("srv", "nonexistent")

        assert result.server == "srv"
        assert result.tools == []

    async def test_discover_timeout(self):
        orch = ServerOrchestrator()

        async def _raise_timeout(*args, **kwargs):
            raise asyncio.TimeoutError()

        with patch("asyncio.wait_for", side_effect=_raise_timeout):
            result = await orch.discover_server_tools("srv", "cmd")

        assert result.tools == []


# -- Tests: request ID allocation -----------------------------------------

class TestRequestIdAllocation:
    """Monotonically increasing request IDs."""

    def test_ids_increment(self):
        orch = ServerOrchestrator()
        id1 = orch._alloc_request_id()
        id2 = orch._alloc_request_id()
        id3 = orch._alloc_request_id()
        assert id1 < id2 < id3

    def test_starts_at_one(self):
        orch = ServerOrchestrator()
        assert orch._alloc_request_id() == 1


# -- Tests: running_servers property ---------------------------------------

class TestRunningServers:
    """Snapshot of server registry."""

    def test_empty_initially(self):
        orch = ServerOrchestrator()
        assert orch.running_servers == {}

    async def test_after_start(self):
        orch = ServerOrchestrator()
        proc = _mock_process(returncode=None)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc), \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=proc):
            await orch.start_server("my-srv", "echo")

        servers = orch.running_servers
        assert "my-srv" in servers
        assert servers["my-srv"].status == MCPServerStatus.RUNNING
