"""
Tests for the Gateway Server mode.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from meta_mcp.gateway import GatewayServer, _TOKENS_PER_TOOL_ESTIMATE
from meta_mcp.gateway_registry import BackendConfig, GatewayRegistry
from meta_mcp.models import DiscoveredTool, ServerToolsResult


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestGatewayRegistry:
    def test_empty_registry_when_file_missing(self, temp_dir):
        path = temp_dir / "missing" / "backends.json"
        reg = GatewayRegistry(registry_path=path)
        assert reg.backends == {}

    def test_load_from_file(self, temp_dir):
        path = temp_dir / "backends.json"
        path.write_text(
            json.dumps(
                {
                    "engram": {
                        "command": "py",
                        "args": ["-m", "engram_mcp"],
                        "auto_activate": True,
                        "description": "Memory server",
                    },
                    "firecrawl": {
                        "command": "npx",
                        "args": ["-y", "firecrawl-mcp"],
                        "env": {"FIRECRAWL_API_KEY": "test-key"},
                    },
                }
            ),
            encoding="utf-8",
        )
        reg = GatewayRegistry(registry_path=path)
        assert len(reg.backends) == 2
        assert reg.get("engram").auto_activate is True
        assert reg.get("firecrawl").command == "npx"

    def test_save_and_reload(self, temp_dir):
        path = temp_dir / "backends.json"
        reg = GatewayRegistry(registry_path=path)
        reg.add("test", BackendConfig(command="echo", args=["hello"]))
        reg.save()

        reg2 = GatewayRegistry(registry_path=path)
        assert "test" in reg2.backends
        assert reg2.get("test").command == "echo"

    def test_auto_activate_backends(self, temp_dir):
        path = temp_dir / "backends.json"
        path.write_text(
            json.dumps(
                {
                    "a": {"command": "a", "auto_activate": True},
                    "b": {"command": "b", "auto_activate": False},
                    "c": {"command": "c", "auto_activate": True},
                }
            ),
            encoding="utf-8",
        )
        reg = GatewayRegistry(registry_path=path)
        assert sorted(reg.auto_activate_backends()) == ["a", "c"]

    def test_remove(self, temp_dir):
        path = temp_dir / "backends.json"
        reg = GatewayRegistry(registry_path=path)
        reg.add("x", BackendConfig(command="x"))
        assert reg.remove("x") is True
        assert reg.remove("x") is False
        assert reg.get("x") is None

    def test_list_summary(self, temp_dir):
        path = temp_dir / "backends.json"
        reg = GatewayRegistry(registry_path=path)
        reg.add("foo", BackendConfig(command="foo", description="Foo server"))
        summary = reg.list_summary()
        assert len(summary) == 1
        assert summary[0]["name"] == "foo"
        assert summary[0]["description"] == "Foo server"


# ---------------------------------------------------------------------------
# Gateway server tests
# ---------------------------------------------------------------------------


def _make_registry(temp_dir, backends=None):
    """Helper to create a registry with test data."""
    path = temp_dir / "backends.json"
    if backends:
        path.write_text(json.dumps(backends), encoding="utf-8")
    return GatewayRegistry(registry_path=path)


class TestGatewayServer:
    def test_starts_with_minimal_tools(self, temp_dir):
        reg = _make_registry(temp_dir)
        gw = GatewayServer(registry=reg)

        tool_names = gw._get_gateway_tool_names()
        # Should have gateway tools + 3 core meta-mcp tools
        assert "activate_backend" in tool_names
        assert "deactivate_backend" in tool_names
        assert "list_backends" in tool_names
        assert "context_budget" in tool_names
        assert "register_backend" in tool_names
        # Core meta-mcp tools
        assert "search_mcp_servers" in tool_names
        assert "install_mcp_server" in tool_names
        assert "detect_capability_gaps" in tool_names
        # Should NOT have 30+ tools
        assert len(tool_names) <= 10

    def test_list_backends_empty(self, temp_dir):
        reg = _make_registry(temp_dir)
        gw = GatewayServer(registry=reg)
        result = gw._list_backends()
        assert "No backends registered" in result

    def test_list_backends_with_entries(self, temp_dir):
        reg = _make_registry(
            temp_dir,
            {
                "engram": {
                    "command": "py",
                    "args": ["-m", "engram_mcp"],
                    "auto_activate": True,
                    "description": "Memory",
                },
                "firecrawl": {
                    "command": "npx",
                    "args": ["-y", "firecrawl-mcp"],
                    "description": "Web scraping",
                },
            },
        )
        gw = GatewayServer(registry=reg)
        result = gw._list_backends()
        assert "engram" in result
        assert "firecrawl" in result
        assert "inactive" in result
        assert "[auto]" in result

    def test_context_budget_baseline(self, temp_dir):
        reg = _make_registry(temp_dir)
        gw = GatewayServer(registry=reg)
        result = gw._context_budget()
        assert "Context Budget Report" in result
        assert "Gateway tools" in result
        assert "Proxied backend tools" in result

    @pytest.mark.asyncio
    async def test_activate_unknown_backend(self, temp_dir):
        reg = _make_registry(temp_dir)
        gw = GatewayServer(registry=reg)
        result = await gw._activate_backend("nonexistent")
        assert "Unknown backend" in result

    @pytest.mark.asyncio
    async def test_deactivate_inactive_backend(self, temp_dir):
        reg = _make_registry(temp_dir)
        gw = GatewayServer(registry=reg)
        result = await gw._deactivate_backend("nothing")
        assert "not active" in result

    @pytest.mark.asyncio
    async def test_activate_already_active(self, temp_dir):
        reg = _make_registry(
            temp_dir,
            {"test": {"command": "echo"}},
        )
        gw = GatewayServer(registry=reg)
        # Manually mark as active
        gw.active_backends["test"] = ServerToolsResult(
            server="test",
            tools=[DiscoveredTool(name="hello", description="Say hello", parameters={})],
        )
        result = await gw._activate_backend("test")
        assert "already active" in result
        assert "test_hello" in result

    @pytest.mark.asyncio
    async def test_activate_and_register_tools(self, temp_dir):
        """Test that activate_backend discovers tools and registers proxies."""
        reg = _make_registry(
            temp_dir,
            {"myserver": {"command": "echo", "args": ["test"]}},
        )
        gw = GatewayServer(registry=reg)

        discovered = ServerToolsResult(
            server="myserver",
            tools=[
                DiscoveredTool(name="tool_a", description="Tool A", parameters={}),
                DiscoveredTool(name="tool_b", description="Tool B", parameters={}),
            ],
        )

        with patch.object(gw.orchestrator, "start_server", new_callable=AsyncMock):
            with patch.object(gw.orchestrator, "_perform_handshake", new_callable=AsyncMock):
                with patch.object(
                    gw.orchestrator,
                    "discover_server_tools",
                    new_callable=AsyncMock,
                    return_value=discovered,
                ):
                    gw.orchestrator._processes["myserver"] = MagicMock()
                    result = await gw._activate_backend("myserver")

        assert "Activated" in result
        assert "myserver_tool_a" in result
        assert "myserver_tool_b" in result
        assert "myserver" in gw.active_backends
        assert "myserver_tool_a" in gw._proxy_tool_map
        assert "myserver_tool_b" in gw._proxy_tool_map

    @pytest.mark.asyncio
    async def test_deactivate_removes_tools(self, temp_dir):
        """Test that deactivate_backend removes proxied tools."""
        reg = _make_registry(
            temp_dir,
            {"myserver": {"command": "echo"}},
        )
        gw = GatewayServer(registry=reg)

        # Simulate active backend
        gw.active_backends["myserver"] = ServerToolsResult(
            server="myserver",
            tools=[
                DiscoveredTool(name="tool_a", description="Tool A", parameters={}),
            ],
        )
        gw._proxy_tool_map["myserver_tool_a"] = ("myserver", "tool_a")

        with patch.object(gw.orchestrator, "stop_server", new_callable=AsyncMock):
            result = await gw._deactivate_backend("myserver")

        assert "Deactivated" in result
        assert "myserver" not in gw.active_backends
        assert "myserver_tool_a" not in gw._proxy_tool_map

    def test_register_backend(self, temp_dir):
        reg = _make_registry(temp_dir)
        gw = GatewayServer(registry=reg)
        result = gw._register_backend(
            name="new-server",
            command="npx",
            args='["-y", "new-server-mcp"]',
            env='{"API_KEY": "test"}',
            auto_activate=False,
            description="A new server",
        )
        assert "Registered" in result
        assert "new-server" in result
        assert reg.get("new-server") is not None
        assert reg.get("new-server").command == "npx"

    def test_register_backend_invalid_args(self, temp_dir):
        reg = _make_registry(temp_dir)
        gw = GatewayServer(registry=reg)
        result = gw._register_backend(
            name="bad",
            command="echo",
            args="not-json",
            env="{}",
            auto_activate=False,
            description="",
        )
        assert "Invalid args JSON" in result

    def test_make_proxy_returns_callable(self, temp_dir):
        reg = _make_registry(temp_dir)
        gw = GatewayServer(registry=reg)
        proxy = gw._make_proxy("server", "tool")
        assert callable(proxy)
        assert proxy.__name__ == "server_tool"

    @pytest.mark.asyncio
    async def test_proxy_forwards_call(self, temp_dir):
        reg = _make_registry(temp_dir)
        gw = GatewayServer(registry=reg)

        with patch.object(
            gw.orchestrator,
            "forward_tool_call",
            new_callable=AsyncMock,
            return_value="proxied result",
        ) as mock_forward:
            proxy = gw._make_proxy("mybackend", "mytool")
            result = await proxy(arg1="value1")

        mock_forward.assert_called_once_with(
            server_name="mybackend",
            tool_name="mytool",
            arguments={"arg1": "value1"},
        )
        assert result == "proxied result"

    @pytest.mark.asyncio
    async def test_proxy_returns_json_for_non_string(self, temp_dir):
        reg = _make_registry(temp_dir)
        gw = GatewayServer(registry=reg)

        with patch.object(
            gw.orchestrator,
            "forward_tool_call",
            new_callable=AsyncMock,
            return_value={"key": "value"},
        ):
            proxy = gw._make_proxy("s", "t")
            result = await proxy()

        assert json.loads(result) == {"key": "value"}

    def test_context_budget_with_active_backends(self, temp_dir):
        reg = _make_registry(
            temp_dir,
            {
                "a": {"command": "a", "estimated_tokens": 500},
                "b": {"command": "b", "estimated_tokens": 4500},
            },
        )
        gw = GatewayServer(registry=reg)

        # Simulate one active backend
        gw.active_backends["a"] = ServerToolsResult(
            server="a",
            tools=[
                DiscoveredTool(name="t1", description="", parameters={}),
                DiscoveredTool(name="t2", description="", parameters={}),
            ],
        )
        gw._proxy_tool_map["a_t1"] = ("a", "t1")
        gw._proxy_tool_map["a_t2"] = ("a", "t2")

        result = gw._context_budget()
        assert "a: 2 tools" in result
        assert "Savings" in result


# ---------------------------------------------------------------------------
# Orchestrator forward_tool_call tests
# ---------------------------------------------------------------------------


class TestForwardToolCall:
    @pytest.mark.asyncio
    async def test_forward_success(self):
        from meta_mcp.orchestration import ServerOrchestrator

        orch = ServerOrchestrator()

        # Create a mock process
        proc = MagicMock()
        proc.returncode = None
        proc.stdin = MagicMock()
        proc.stdin.write = MagicMock()
        proc.stdin.drain = AsyncMock()
        proc.stdout = MagicMock()

        # Simulate JSON-RPC response
        response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [{"type": "text", "text": "hello world"}],
            },
        }) + "\n"
        proc.stdout.readline = AsyncMock(return_value=response.encode("utf-8"))

        orch._processes["test"] = proc
        orch._servers["test"] = MagicMock(command="echo", status="running")

        result = await orch.forward_tool_call("test", "greet", {"name": "world"})
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_forward_error(self):
        from meta_mcp.orchestration import ServerOrchestrator

        orch = ServerOrchestrator()

        proc = MagicMock()
        proc.returncode = None
        proc.stdin = MagicMock()
        proc.stdin.write = MagicMock()
        proc.stdin.drain = AsyncMock()
        proc.stdout = MagicMock()

        response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -1, "message": "tool not found"},
        }) + "\n"
        proc.stdout.readline = AsyncMock(return_value=response.encode("utf-8"))

        orch._processes["test"] = proc
        orch._servers["test"] = MagicMock(command="echo", status="running")

        with pytest.raises(RuntimeError, match="tool not found"):
            await orch.forward_tool_call("test", "missing", {})
