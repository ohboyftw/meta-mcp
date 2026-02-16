"""
Tests for MCP tool schema generation and parameter passing.

Validates that FastMCP generates correct JSON schemas from tool signatures,
and that tool calls work with actual parameters (not a broken 'kwargs' string).

These bugs are platform-independent but affect all MCP clients:
  - Claude Code (Windows, macOS, Linux)
  - VS Code + Copilot MCP extension
  - Cursor
  - Cline
  - Roo Code
  - Antigravity / Windsurf
  - Any client using JSON-RPC over stdio
"""

import inspect
import json
from typing import Dict, List, Optional

import pytest
from mcp.server.fastmcp.utilities.func_metadata import func_metadata

from src.meta_mcp.server import MetaMCPServer
from src.meta_mcp.tools_base import Tool


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def server():
    return MetaMCPServer()


@pytest.fixture
def all_tools(server):
    return server.tools


@pytest.fixture
def tool_map(all_tools):
    """Map of tool_name -> tool_instance."""
    return {t.get_name(): t for t in all_tools}


@pytest.fixture
def wrapped_map(server):
    """Map of tool_name -> wrapped function (as registered with FastMCP)."""
    return {t.get_name(): MetaMCPServer._wrap_tool(t) for t in server.tools}


# ── Schema correctness tests ─────────────────────────────────────────


class TestSchemaGeneration:
    """Verify FastMCP generates correct schemas from wrapped tool functions."""

    def test_no_kwargs_string_param(self, wrapped_map):
        """No tool should have a 'kwargs' string parameter in its schema.

        This was the root cause of the bug: apply_ex's **kwargs was converted
        by FastMCP into a required 'kwargs: string' parameter, which broke
        every MCP client (Claude Code, Cursor, Cline, VS Code, etc.).
        """
        for name, fn in wrapped_map.items():
            meta = func_metadata(fn, skip_names=[])
            schema = meta.arg_model.model_json_schema()
            props = schema.get("properties", {})
            assert "kwargs" not in props, (
                f"Tool '{name}' has a 'kwargs' parameter in its schema — "
                f"this breaks all MCP clients. Schema: {json.dumps(schema, indent=2)}"
            )

    def test_no_log_call_param(self, wrapped_map):
        """No tool should expose internal 'log_call' or 'catch_exceptions' params."""
        for name, fn in wrapped_map.items():
            meta = func_metadata(fn, skip_names=[])
            schema = meta.arg_model.model_json_schema()
            props = schema.get("properties", {})
            assert "log_call" not in props, (
                f"Tool '{name}' exposes internal 'log_call' parameter"
            )
            assert "catch_exceptions" not in props, (
                f"Tool '{name}' exposes internal 'catch_exceptions' parameter"
            )

    def test_schema_title_not_apply_ex(self, wrapped_map):
        """Schema title should reference apply, not apply_ex."""
        for name, fn in wrapped_map.items():
            meta = func_metadata(fn, skip_names=[])
            schema = meta.arg_model.model_json_schema()
            title = schema.get("title", "")
            assert "apply_ex" not in title.lower(), (
                f"Tool '{name}' schema title references apply_ex: '{title}'"
            )

    def test_search_tool_has_query_param(self, wrapped_map):
        """SearchMcpServersTool should expose 'query' as an optional string."""
        fn = wrapped_map["search_mcp_servers"]
        meta = func_metadata(fn, skip_names=[])
        schema = meta.arg_model.model_json_schema()
        props = schema.get("properties", {})
        assert "query" in props, (
            f"search_mcp_servers missing 'query' param. Got: {list(props.keys())}"
        )

    def test_all_tools_produce_valid_schema(self, wrapped_map):
        """Every tool must produce a valid JSON schema without errors."""
        for name, fn in wrapped_map.items():
            try:
                meta = func_metadata(fn, skip_names=[])
                schema = meta.arg_model.model_json_schema()
                # Must be serializable
                json.dumps(schema)
            except Exception as e:
                pytest.fail(f"Tool '{name}' failed schema generation: {e}")


# ── Wrapper signature tests ───────────────────────────────────────────


class TestWrapperSignature:
    """Verify that _wrap_tool preserves the apply() method's signature."""

    def test_wrapper_matches_apply_signature(self, all_tools):
        """Wrapper's signature must match apply() exactly."""
        for tool in all_tools:
            wrapper = MetaMCPServer._wrap_tool(tool)
            wrapper_sig = inspect.signature(wrapper)
            apply_sig = inspect.signature(tool.apply)
            assert wrapper_sig == apply_sig, (
                f"Tool '{tool.get_name()}': wrapper sig {wrapper_sig} != "
                f"apply sig {apply_sig}"
            )

    def test_wrapper_has_no_self_param(self, all_tools):
        """Wrapper should not expose 'self' parameter."""
        for tool in all_tools:
            wrapper = MetaMCPServer._wrap_tool(tool)
            sig = inspect.signature(wrapper)
            assert "self" not in sig.parameters, (
                f"Tool '{tool.get_name()}' wrapper exposes 'self' parameter"
            )


# ── Tool invocation tests ────────────────────────────────────────────


class TestToolInvocation:
    """Verify that tools can be called with proper keyword arguments."""

    def test_search_with_query_kwarg(self, wrapped_map):
        """search_mcp_servers(query="test") should work, not raise TypeError."""
        fn = wrapped_map["search_mcp_servers"]
        result = fn(query="web scraping")
        assert isinstance(result, str)
        assert "Error" not in result or "MCP servers" in result

    def test_get_manager_stats_no_args(self, wrapped_map):
        """get_manager_stats() with no args should work."""
        fn = wrapped_map["get_manager_stats"]
        result = fn()
        assert isinstance(result, str)

    def test_list_installed_no_args(self, wrapped_map):
        """list_installed_servers() with no args should work."""
        fn = wrapped_map["list_installed_servers"]
        result = fn()
        assert isinstance(result, str)

    def test_error_handling_returns_string(self, wrapped_map):
        """Tools that error should return error string, not raise."""
        fn = wrapped_map["get_server_info"]
        # Pass a server that doesn't exist
        result = fn(server_name="nonexistent_server_xyz_12345")
        assert isinstance(result, str)


# ── Regression: the exact bug scenario ───────────────────────────────


class TestKwargsRegressions:
    """Reproduce the exact error patterns seen across MCP clients.

    The original bug manifested as:
        Error executing tool search_mcp_servers:
        SearchMcpServersTool.apply() got an unexpected keyword argument 'kwargs'

    This happened because FastMCP converted **kwargs to a literal 'kwargs: str'
    parameter, and every client (Claude Code, Cursor, Cline, VS Code, etc.)
    would call: search_mcp_servers(kwargs='query="test"')
    """

    def test_old_apply_ex_schema_has_kwargs_bug(self, tool_map):
        """Demonstrate the bug: apply_ex produces a broken schema."""
        tool = tool_map["search_mcp_servers"]
        meta = func_metadata(tool.apply_ex, skip_names=[])
        schema = meta.arg_model.model_json_schema()
        # This is the broken behavior we're protecting against
        assert "kwargs" in schema.get("properties", {}), (
            "apply_ex should have the kwargs bug (this test documents the problem)"
        )
        assert "kwargs" in schema.get("required", []), (
            "apply_ex's kwargs should be required (documenting the bug)"
        )

    def test_new_wrapper_schema_no_kwargs_bug(self, tool_map):
        """Verify the fix: wrapper does NOT have the kwargs bug."""
        tool = tool_map["search_mcp_servers"]
        wrapper = MetaMCPServer._wrap_tool(tool)
        meta = func_metadata(wrapper, skip_names=[])
        schema = meta.arg_model.model_json_schema()
        assert "kwargs" not in schema.get("properties", {}), (
            "Wrapper should NOT have kwargs in schema"
        )
        assert "kwargs" not in schema.get("required", []), (
            "Wrapper should NOT require kwargs"
        )

    def test_calling_with_kwargs_string_fails_correctly(self, tool_map):
        """If a client somehow still sends kwargs="...", it should fail gracefully."""
        tool = tool_map["search_mcp_servers"]
        wrapper = MetaMCPServer._wrap_tool(tool)
        # Simulate what a buggy client might send
        result = wrapper(kwargs='query="test"')
        # Should return an error string (caught by wrapper), not crash
        assert isinstance(result, str)
        assert "Error" in result


# ── FastMCP server integration test ──────────────────────────────────


class TestFastMCPIntegration:
    """Test that the full FastMCP server registers tools correctly."""

    def test_server_creates_without_error(self, server):
        mcp = server.create_fastmcp_server()
        assert mcp is not None

    def test_all_tools_registered(self, server):
        mcp = server.create_fastmcp_server()
        # FastMCP stores tools internally; check via list_tools
        # We just verify no exception during registration
        assert len(server.tools) > 0
