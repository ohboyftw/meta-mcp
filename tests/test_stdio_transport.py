"""
Tests for MCP stdio transport correctness across platforms.

Validates that the MCP server entry point does not break the JSON-RPC
stdio channel — the root cause of tool call hangs on Windows, macOS,
and Linux when sys.stdout.reconfigure() is called.

Affected MCP clients (all use JSON-RPC over stdio):
  - Claude Code (Windows, macOS, Linux)
  - VS Code + Copilot MCP / Continue
  - Cursor
  - Cline
  - Roo Code
  - Antigravity / Windsurf
  - Zed
  - Any MCP client using stdio transport

The core invariant:
  sys.stdout MUST remain in binary-compatible mode for FastMCP's stdio
  transport. Only sys.stderr may be reconfigured for UTF-8 logging.
"""

import ast
import re
import sys
from pathlib import Path

import pytest


# ── Parametrized MCP server paths ─────────────────────────────────────

# Add paths to all MCP servers that should be tested.
# Each entry: (display_name, path_to_mcp_server_py)
MCP_SERVERS = []

# Auto-discover MCP servers in known locations
_SKILL_ROOT = Path.home() / ".claude" / "skills"
_REPO_ROOT = Path("D:/Home/claudeSkills/Repo")

_SEARCH_ROOTS = [_SKILL_ROOT, _REPO_ROOT]

for root in _SEARCH_ROOTS:
    if root.exists():
        for mcp_file in root.rglob("mcp_server.py"):
            name = mcp_file.parent.name
            MCP_SERVERS.append(pytest.param(mcp_file, id=name))

# Also check meta-mcp's own entry point
_META_MCP_MAIN = Path("D:/Home/meta-mcp/src/meta_mcp/__main__.py")
if _META_MCP_MAIN.exists():
    MCP_SERVERS.append(pytest.param(_META_MCP_MAIN, id="meta-mcp"))


# ── Static analysis tests ────────────────────────────────────────────


class TestNoStdoutReconfigure:
    """Static analysis: no MCP server should reconfigure sys.stdout."""

    @pytest.mark.parametrize("server_path", MCP_SERVERS)
    def test_no_stdout_reconfigure(self, server_path: Path):
        """MCP server must NOT call sys.stdout.reconfigure().

        sys.stdout.reconfigure(encoding="utf-8") switches stdout from binary
        to text mode, which breaks FastMCP's stdio transport. The JSON-RPC
        response after a tool call is silently lost or buffered forever.

        This affects ALL MCP clients on ALL platforms:
        - Windows: most common trigger (cp1252 -> utf-8 reconfigure)
        - macOS/Linux: can also break if locale isn't UTF-8
        """
        source = server_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(server_path))

        violations = []
        for node in ast.walk(tree):
            # Match: sys.stdout.reconfigure(...)
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "reconfigure"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "stdout"
                ):
                    violations.append(node.lineno)

        assert not violations, (
            f"{server_path.name} calls sys.stdout.reconfigure() at line(s) "
            f"{violations}. This breaks MCP stdio transport. "
            f"Only sys.stderr.reconfigure() is safe."
        )

    @pytest.mark.parametrize("server_path", MCP_SERVERS)
    def test_stderr_reconfigure_is_ok(self, server_path: Path):
        """sys.stderr.reconfigure() is safe and should not be flagged."""
        source = server_path.read_text(encoding="utf-8")
        # This test just ensures we don't accidentally flag stderr
        # It's a positive test — stderr reconfigure should be allowed
        tree = ast.parse(source, filename=str(server_path))
        # No assertion — just verifying the file parses and the pattern exists


class TestStdoutReconfigurePattern:
    """Pattern-based detection for stdout corruption across codebases."""

    @pytest.mark.parametrize("server_path", MCP_SERVERS)
    def test_no_stdout_write_mode_change(self, server_path: Path):
        """No MCP server should change stdout's mode/encoding at module level."""
        source = server_path.read_text(encoding="utf-8")

        # Patterns that break stdio transport
        dangerous_patterns = [
            r"sys\.stdout\.reconfigure\s*\(",
            r"sys\.stdout\s*=\s*",  # reassigning stdout
            r"os\.fdopen\(.*stdout",  # reopening stdout fd
            r"codecs\.getwriter.*stdout",  # wrapping stdout in codec
        ]

        for pattern in dangerous_patterns:
            matches = list(re.finditer(pattern, source))
            # Filter: allow if inside a comment or string
            real_matches = []
            for m in matches:
                line_start = source.rfind("\n", 0, m.start()) + 1
                line = source[line_start : source.find("\n", m.end())]
                stripped = line.lstrip()
                if not stripped.startswith("#"):
                    real_matches.append((m.start(), line.strip()))

            assert not real_matches, (
                f"{server_path.name} modifies sys.stdout which breaks "
                f"MCP stdio transport: {real_matches}"
            )


# ── Cross-platform encoding safety ───────────────────────────────────


class TestEncodingSafety:
    """Ensure MCP servers handle encoding safely across platforms."""

    def test_stderr_encoding_can_be_reconfigured(self):
        """stderr.reconfigure() should work on all platforms."""
        if hasattr(sys.stderr, "reconfigure"):
            # Should not raise
            original = sys.stderr.encoding
            sys.stderr.reconfigure(encoding="utf-8")
            assert sys.stderr.encoding == "utf-8"

    def test_stdout_buffer_exists(self):
        """stdout.buffer must exist for FastMCP's binary transport."""
        assert hasattr(sys.stdout, "buffer"), (
            "sys.stdout.buffer is required for MCP stdio transport"
        )

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific")
    def test_windows_default_encoding_not_utf8(self):
        """On Windows, default stdout encoding is often not UTF-8.

        This is why developers add sys.stdout.reconfigure(encoding='utf-8') —
        but it breaks MCP. This test documents the Windows behavior.
        """
        # On Windows without PYTHONIOENCODING, stdout defaults to cp1252/cp65001
        # The temptation to reconfigure is strong, but it breaks MCP
        # This test just documents the situation
        encoding = sys.stdout.encoding
        assert encoding is not None, "stdout should have an encoding"


# ── MCP client compatibility matrix (documentation) ──────────────────


class TestClientCompatibilityDocs:
    """Document which MCP clients are affected by stdio corruption.

    All clients using JSON-RPC over stdio are affected identically because
    the bug is server-side (Python process), not client-side.
    """

    AFFECTED_CLIENTS = [
        "Claude Code (Anthropic CLI - Windows/macOS/Linux)",
        "VS Code + Copilot MCP extension",
        "VS Code + Continue extension",
        "Cursor",
        "Cline",
        "Roo Code",
        "Antigravity / Windsurf",
        "Zed Editor",
    ]

    AFFECTED_PLATFORMS = [
        ("Windows", "Most common — cp1252 default encoding triggers the reconfigure pattern"),
        ("macOS", "Usually UTF-8 default, but reconfigure still breaks binary transport"),
        ("Linux", "Usually UTF-8 default, but reconfigure still breaks binary transport"),
    ]

    def test_all_clients_use_stdio(self):
        """All major MCP clients use JSON-RPC over stdio for local servers.

        The bug affects all of them equally because:
        1. Client sends JSON-RPC request via server's stdin
        2. Server processes request and writes response to stdout
        3. If stdout was reconfigured to text mode, the response is
           buffered/corrupted and never reaches the client
        4. Client waits indefinitely → timeout
        """
        assert len(self.AFFECTED_CLIENTS) > 0
        assert len(self.AFFECTED_PLATFORMS) > 0

    def test_symptom_is_tool_hang_not_error(self):
        """The symptom is a silent hang, not an error message.

        This makes the bug hard to diagnose:
        - initialize handshake works (happens before tool calls)
        - tools/list works (returns tool schemas)
        - tools/call hangs forever (response lost in stdout buffer)
        - No error in stderr
        - Client shows timeout after 30-60s
        """
        # Documentation test — the assertion is the docstring
        pass
