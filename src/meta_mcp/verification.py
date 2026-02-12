"""
R3: Post-Install Verification Loop.

This module provides comprehensive verification of MCP servers after installation.
It performs smoke tests by spawning server processes, executing MCP protocol handshakes,
discovering tools, and optionally invoking simple tool calls. It also supports automatic
self-healing for common failure modes and ecosystem-wide health checks.
"""

import asyncio
import json
import logging
import os
import shutil
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    SmokeTestResult,
    VerificationResult,
    ServerHealthReport,
    EcosystemHealthResult,
    HealthStatus,
    MCPConfigEntry,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROTOCOL_VERSION = "2024-11-05"
_CLIENT_INFO = {"name": "meta-mcp-verifier", "version": "0.1.0"}
_DEFAULT_TIMEOUT = 10  # seconds
_MAX_SELF_HEAL_ATTEMPTS = 3

# JSON-RPC message templates ------------------------------------------------

_INITIALIZE_REQUEST: Dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": _PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": _CLIENT_INFO,
    },
}

_TOOLS_LIST_REQUEST: Dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {},
}

_INITIALIZED_NOTIFICATION: Dict[str, Any] = {
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
}

# ---------------------------------------------------------------------------
# Remediation map for self-healing
# ---------------------------------------------------------------------------

_REMEDIATION_MAP: List[Tuple[List[str], str, str]] = [
    # (error_patterns, category, suggestion)
    (
        ["ENOENT", "not found", "No such file"],
        "missing_binary",
        "The server binary was not found. Verify the command is installed and "
        "available on $PATH. You may need to run the installation step again.",
    ),
    (
        ["EACCES", "permission denied", "Permission denied"],
        "permission",
        "Permission denied when starting the server. Try: chmod +x <binary> "
        "or run with appropriate permissions (avoid sudo when possible).",
    ),
    (
        ["Cannot find module", "MODULE_NOT_FOUND", "Error: Cannot find module"],
        "missing_node_module",
        "A required Node.js module is missing. Run 'npm install' in the "
        "server directory, or reinstall the package with 'npm install -g <package>'.",
    ),
    (
        ["chromium", "browser", "Chromium", "puppeteer"],
        "missing_browser",
        "A browser binary (Chromium) is required but was not found. "
        "Run 'npx puppeteer install chromium' to download it.",
    ),
    (
        ["EADDRINUSE", "address already in use", "Address already in use"],
        "port_conflict",
        "The required port is already in use. Either stop the conflicting "
        "process (lsof -i :<port> | kill) or configure the server to use a "
        "different port.",
    ),
    (
        ["API key", "api_key", "unauthorized", "Unauthorized", "401", "UNAUTHORIZED"],
        "missing_credentials",
        "The server requires an API key or authentication token that is "
        "missing or invalid. Set the appropriate environment variable "
        "(e.g. *_API_KEY) before starting the server.",
    ),
    (
        ["ETIMEDOUT", "timeout", "Timeout", "ETIME"],
        "timeout",
        "The server timed out during startup. It may need more time to "
        "initialize, or a network dependency might be unreachable.",
    ),
    (
        ["ECONNREFUSED", "Connection refused"],
        "connection_refused",
        "Connection was refused. The server may have crashed during startup "
        "or a required dependency service is not running.",
    ),
]


# ---------------------------------------------------------------------------
# Helper: read a single JSON-RPC response from stdout
# ---------------------------------------------------------------------------

async def _read_jsonrpc_response(
    stdout: asyncio.StreamReader,
    timeout: float = _DEFAULT_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    """Read a single newline-delimited JSON-RPC message from *stdout*.

    MCP stdio servers communicate via newline-delimited JSON.  We read one
    line at a time and attempt to parse it.  Non-JSON lines (e.g. log output
    sent to stdout by accident) are silently skipped so that we are resilient
    to noisy servers.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            line = await asyncio.wait_for(
                stdout.readline(),
                timeout=remaining,
            )
        except asyncio.TimeoutError:
            break

        if not line:
            # EOF – process likely exited
            break

        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue

        try:
            msg = json.loads(text)
            if isinstance(msg, dict):
                return msg
        except json.JSONDecodeError:
            # Likely a log line emitted on stdout – skip it.
            logger.debug("Skipped non-JSON line from server: %s", text[:120])
            continue

    return None


async def _write_jsonrpc_message(
    stdin: asyncio.StreamWriter,
    message: Dict[str, Any],
) -> None:
    """Write a newline-delimited JSON-RPC message to *stdin*."""
    payload = json.dumps(message) + "\n"
    stdin.write(payload.encode("utf-8"))
    await stdin.drain()


# ---------------------------------------------------------------------------
# ServerVerifier
# ---------------------------------------------------------------------------

class ServerVerifier:
    """Full-lifecycle MCP server verification engine.

    Responsibilities:
    * Spawn a server process in stdio mode.
    * Execute the MCP ``initialize`` handshake.
    * Discover exposed tools via ``tools/list``.
    * Optionally invoke a simple tool for a smoke test.
    * Time every step and return a structured ``VerificationResult``.
    * Provide self-healing suggestions for common failure classes.
    * Perform ecosystem-wide health checks across all configured servers.
    """

    def __init__(self, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    # -- Public API ---------------------------------------------------------

    async def verify_server(
        self,
        server_name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> VerificationResult:
        """Run a complete smoke-test against a single MCP server.

        Steps executed in order:
        1. Spawn the server subprocess (stdio transport).
        2. Send ``initialize`` and validate the response.
        3. Send ``notifications/initialized``.
        4. Send ``tools/list`` and capture discovered tools.
        5. If a simple tool is available, attempt to call it.
        6. Collect timing data for each phase.
        7. Terminate the process and return ``VerificationResult``.
        """
        errors: List[str] = []
        tools_discovered: List[str] = []
        smoke_test: Optional[SmokeTestResult] = None
        process_started = False
        mcp_handshake = False
        process: Optional[asyncio.subprocess.Process] = None

        overall_start = time.monotonic()

        try:
            # ---- Step 1: Spawn process -----------------------------------
            process, spawn_error = await self._spawn_process(
                command, args or [], env,
            )
            if process is None:
                errors.append(spawn_error or "Failed to spawn server process")
                return self._build_result(
                    process_started=False,
                    mcp_handshake=False,
                    tools_discovered=[],
                    smoke_test=None,
                    errors=errors,
                )

            process_started = True
            logger.info(
                "Server '%s' spawned (pid=%s)",
                server_name,
                process.pid,
            )

            assert process.stdin is not None
            assert process.stdout is not None

            # ---- Step 2: MCP initialize handshake ------------------------
            handshake_ok, handshake_err = await self._perform_handshake(
                process.stdin, process.stdout,
            )
            if not handshake_ok:
                errors.append(handshake_err or "MCP handshake failed")
                return self._build_result(
                    process_started=True,
                    mcp_handshake=False,
                    tools_discovered=[],
                    smoke_test=None,
                    errors=errors,
                )

            mcp_handshake = True
            logger.info("MCP handshake succeeded for '%s'", server_name)

            # ---- Step 3: Send initialized notification -------------------
            try:
                await _write_jsonrpc_message(
                    process.stdin, _INITIALIZED_NOTIFICATION,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to send initialized notification: %s", exc,
                )

            # ---- Step 4: Discover tools ----------------------------------
            tools_discovered, tools_raw, tools_err = await self._discover_tools(
                process.stdin, process.stdout,
            )
            if tools_err:
                errors.append(tools_err)

            logger.info(
                "Discovered %d tools for '%s': %s",
                len(tools_discovered),
                server_name,
                tools_discovered,
            )

            # ---- Step 5: Smoke test a simple tool ------------------------
            if tools_discovered and tools_raw:
                smoke_test = await self._smoke_test_tool(
                    process.stdin,
                    process.stdout,
                    tools_raw,
                    server_name,
                )

        except asyncio.CancelledError:
            errors.append("Verification was cancelled")
            raise
        except Exception as exc:
            logger.exception("Unexpected error verifying '%s'", server_name)
            errors.append(f"Unexpected error: {exc}")
        finally:
            # ---- Step 6: Terminate the process ---------------------------
            await self._terminate_process(process)

        elapsed_ms = int((time.monotonic() - overall_start) * 1000)
        logger.info(
            "Verification of '%s' completed in %dms",
            server_name,
            elapsed_ms,
        )

        return self._build_result(
            process_started=process_started,
            mcp_handshake=mcp_handshake,
            tools_discovered=tools_discovered,
            smoke_test=smoke_test,
            errors=errors,
        )

    async def self_heal(
        self,
        server_name: str,
        error: str,
        command: str,
    ) -> Dict[str, Any]:
        """Attempt automatic remediation for a known failure class.

        Returns a dict with:
        * ``category`` – the matched error category (or ``"unknown"``).
        * ``suggestion`` – human-readable remediation advice.
        * ``auto_fix_attempted`` – whether an automatic fix was tried.
        * ``auto_fix_result`` – outcome of the auto-fix (if attempted).
        """
        error_lower = error.lower()

        # Walk through the remediation map and find first match.
        for patterns, category, suggestion in _REMEDIATION_MAP:
            if any(p.lower() in error_lower for p in patterns):
                logger.info(
                    "Self-heal matched category '%s' for server '%s'",
                    category,
                    server_name,
                )
                auto_fix_attempted, auto_fix_result = await self._attempt_auto_fix(
                    category, command, server_name, error,
                )
                return {
                    "category": category,
                    "suggestion": suggestion,
                    "auto_fix_attempted": auto_fix_attempted,
                    "auto_fix_result": auto_fix_result,
                }

        logger.warning(
            "No remediation match for server '%s', error: %s",
            server_name,
            error[:200],
        )
        return {
            "category": "unknown",
            "suggestion": (
                f"An unrecognised error occurred while verifying '{server_name}'. "
                f"Error: {error[:300]}. "
                "Check the server logs for more details and ensure all "
                "dependencies are installed."
            ),
            "auto_fix_attempted": False,
            "auto_fix_result": None,
        }

    async def check_ecosystem_health(
        self,
        config: Dict[str, MCPConfigEntry],
    ) -> EcosystemHealthResult:
        """Check the health of every configured MCP server.

        Iterates over all servers in the provided MCP configuration, runs
        ``verify_server`` for each, and aggregates the results into an
        ``EcosystemHealthResult``.
        """
        reports: List[ServerHealthReport] = []

        if not config:
            logger.info("No servers configured – ecosystem is trivially healthy")
            return EcosystemHealthResult(
                servers=[],
                summary={"healthy": 0, "unhealthy": 0, "degraded": 0, "unknown": 0},
                checked_at=datetime.now(),
            )

        # Run verification for each server concurrently (bounded).
        semaphore = asyncio.Semaphore(4)  # at most 4 concurrent checks

        async def _check_one(name: str, entry: MCPConfigEntry) -> ServerHealthReport:
            async with semaphore:
                return await self._check_single_server_health(name, entry)

        tasks = [
            _check_one(name, entry)
            for name, entry in config.items()
        ]
        reports = await asyncio.gather(*tasks, return_exceptions=False)

        # Build summary counts.
        summary: Dict[str, int] = {
            "healthy": 0,
            "unhealthy": 0,
            "degraded": 0,
            "unknown": 0,
        }
        for report in reports:
            key = report.status.value
            summary[key] = summary.get(key, 0) + 1

        logger.info(
            "Ecosystem health check complete: %d servers, %s",
            len(reports),
            summary,
        )

        return EcosystemHealthResult(
            servers=list(reports),
            summary=summary,
            checked_at=datetime.now(),
        )

    # -- Internal helpers ---------------------------------------------------

    async def _spawn_process(
        self,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]],
    ) -> Tuple[Optional[asyncio.subprocess.Process], Optional[str]]:
        """Spawn the server as a subprocess with stdio pipes.

        Returns ``(process, None)`` on success, or ``(None, error_msg)`` on
        failure.
        """
        # Build the environment: inherit the current env and overlay extras.
        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        # Verify the command binary exists before spawning.
        resolved = shutil.which(command, path=full_env.get("PATH"))
        if resolved is None:
            msg = (
                f"Command '{command}' not found on PATH. "
                "Ensure the server binary is installed."
            )
            logger.error(msg)
            return None, msg

        try:
            process = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    command,
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=full_env,
                ),
                timeout=self.timeout,
            )
            # Give the process a moment to crash immediately on startup.
            await asyncio.sleep(0.3)
            if process.returncode is not None:
                stderr_bytes = b""
                if process.stderr:
                    try:
                        stderr_bytes = await asyncio.wait_for(
                            process.stderr.read(4096), timeout=2,
                        )
                    except asyncio.TimeoutError:
                        pass
                stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
                msg = (
                    f"Server process exited immediately with code "
                    f"{process.returncode}"
                )
                if stderr_text:
                    msg += f": {stderr_text[:500]}"
                logger.error(msg)
                return None, msg

            return process, None

        except asyncio.TimeoutError:
            logger.error("Timed out spawning server process for '%s'", command)
            return None, "Timed out while spawning server process"
        except FileNotFoundError:
            msg = f"Command '{command}' not found (FileNotFoundError)"
            logger.error(msg)
            return None, msg
        except PermissionError:
            msg = f"Permission denied executing '{command}'"
            logger.error(msg)
            return None, msg
        except OSError as exc:
            msg = f"OS error spawning '{command}': {exc}"
            logger.error(msg)
            return None, msg

    async def _perform_handshake(
        self,
        stdin: asyncio.StreamWriter,
        stdout: asyncio.StreamReader,
    ) -> Tuple[bool, Optional[str]]:
        """Send the ``initialize`` request and validate the response."""
        try:
            await _write_jsonrpc_message(stdin, _INITIALIZE_REQUEST)
        except Exception as exc:
            return False, f"Failed to send initialize request: {exc}"

        response = await _read_jsonrpc_response(stdout, timeout=self.timeout)
        if response is None:
            return False, (
                "No response to initialize request (timeout or process exited)"
            )

        # Validate the response structure.
        if "error" in response:
            err = response["error"]
            return False, (
                f"Server returned error on initialize: "
                f"{err.get('message', err)}"
            )

        result = response.get("result")
        if not isinstance(result, dict):
            return False, (
                f"Invalid initialize response: expected 'result' dict, "
                f"got {type(result).__name__}"
            )

        # Check for required fields.
        protocol_version = result.get("protocolVersion")
        if not protocol_version:
            logger.warning(
                "Server did not return protocolVersion in initialize response"
            )

        server_info = result.get("serverInfo", {})
        logger.info(
            "Server identified as: %s (protocol %s)",
            server_info.get("name", "unknown"),
            protocol_version or "unknown",
        )

        return True, None

    async def _discover_tools(
        self,
        stdin: asyncio.StreamWriter,
        stdout: asyncio.StreamReader,
    ) -> Tuple[List[str], List[Dict[str, Any]], Optional[str]]:
        """Send ``tools/list`` and return (tool_names, raw_tools, error)."""
        try:
            await _write_jsonrpc_message(stdin, _TOOLS_LIST_REQUEST)
        except Exception as exc:
            return [], [], f"Failed to send tools/list request: {exc}"

        response = await _read_jsonrpc_response(stdout, timeout=self.timeout)
        if response is None:
            return [], [], "No response to tools/list request"

        if "error" in response:
            err = response["error"]
            return [], [], (
                f"Server returned error on tools/list: "
                f"{err.get('message', err)}"
            )

        result = response.get("result", {})
        tools: List[Dict[str, Any]] = result.get("tools", [])
        if not isinstance(tools, list):
            return [], [], (
                f"Expected 'tools' to be a list, got {type(tools).__name__}"
            )

        tool_names = [
            t.get("name", "<unnamed>") for t in tools if isinstance(t, dict)
        ]
        return tool_names, tools, None

    async def _smoke_test_tool(
        self,
        stdin: asyncio.StreamWriter,
        stdout: asyncio.StreamReader,
        tools_raw: List[Dict[str, Any]],
        server_name: str,
    ) -> Optional[SmokeTestResult]:
        """Pick a simple tool and attempt a basic invocation.

        We prefer tools that require no arguments or only simple string
        arguments so we can construct a reasonable test input.
        """
        candidate = self._pick_simple_tool(tools_raw)
        if candidate is None:
            logger.info(
                "No suitable simple tool found for smoke test on '%s'",
                server_name,
            )
            return None

        tool_name = candidate.get("name", "<unnamed>")
        test_input = self._build_test_input(candidate)
        input_description = json.dumps(test_input) if test_input else "{}"

        call_request: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": test_input,
            },
        }

        start = time.monotonic()
        try:
            await _write_jsonrpc_message(stdin, call_request)
            response = await _read_jsonrpc_response(stdout, timeout=self.timeout)
            latency_ms = int((time.monotonic() - start) * 1000)

            if response is None:
                return SmokeTestResult(
                    tool=tool_name,
                    input_used=input_description,
                    result="timeout",
                    latency_ms=latency_ms,
                    error="No response to tools/call request",
                )

            if "error" in response:
                err = response["error"]
                return SmokeTestResult(
                    tool=tool_name,
                    input_used=input_description,
                    result="error",
                    latency_ms=latency_ms,
                    error=f"Tool call error: {err.get('message', err)}",
                )

            return SmokeTestResult(
                tool=tool_name,
                input_used=input_description,
                result="ok",
                latency_ms=latency_ms,
                error=None,
            )

        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            return SmokeTestResult(
                tool=tool_name,
                input_used=input_description,
                result="error",
                latency_ms=latency_ms,
                error=str(exc),
            )

    def _pick_simple_tool(
        self,
        tools_raw: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Select the simplest tool available for a smoke test.

        Priority order:
        1. Tools with zero required parameters.
        2. Tools whose only required parameter is a simple string.
        3. Fall back to the first tool if nothing else matches.
        """
        zero_params: List[Dict[str, Any]] = []
        simple_string: List[Dict[str, Any]] = []

        for tool in tools_raw:
            if not isinstance(tool, dict):
                continue
            schema = tool.get("inputSchema", tool.get("parameters", {}))
            if not isinstance(schema, dict):
                schema = {}

            properties = schema.get("properties", {})
            required = schema.get("required", [])

            if not required and not properties:
                # No parameters at all – best candidate.
                zero_params.append(tool)
                continue

            if not required:
                zero_params.append(tool)
                continue

            # Check if all required params are simple strings.
            all_simple = True
            for req_name in required:
                prop = properties.get(req_name, {})
                if prop.get("type") != "string":
                    all_simple = False
                    break
            if all_simple and len(required) <= 2:
                simple_string.append(tool)

        if zero_params:
            return zero_params[0]
        if simple_string:
            return simple_string[0]
        if tools_raw:
            return tools_raw[0]
        return None

    def _build_test_input(
        self,
        tool: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build a minimal test input for the given tool schema."""
        schema = tool.get("inputSchema", tool.get("parameters", {}))
        if not isinstance(schema, dict):
            return {}

        properties = schema.get("properties", {})
        required = schema.get("required", [])
        test_input: Dict[str, Any] = {}

        for param_name in required:
            prop = properties.get(param_name, {})
            param_type = prop.get("type", "string")

            if param_type == "string":
                # Use a sensible default test value.
                test_input[param_name] = "test"
            elif param_type == "integer":
                test_input[param_name] = 1
            elif param_type == "number":
                test_input[param_name] = 1.0
            elif param_type == "boolean":
                test_input[param_name] = True
            elif param_type == "array":
                test_input[param_name] = []
            elif param_type == "object":
                test_input[param_name] = {}
            else:
                test_input[param_name] = "test"

        return test_input

    async def _terminate_process(
        self,
        process: Optional[asyncio.subprocess.Process],
    ) -> None:
        """Gracefully terminate the server process."""
        if process is None:
            return
        if process.returncode is not None:
            # Already exited.
            return

        logger.debug("Terminating server process (pid=%s)", process.pid)
        try:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                logger.warning(
                    "Process did not exit after SIGTERM, sending SIGKILL "
                    "(pid=%s)",
                    process.pid,
                )
                process.kill()
                await asyncio.wait_for(process.wait(), timeout=2)
        except ProcessLookupError:
            pass  # Already gone.
        except Exception as exc:
            logger.warning("Error terminating process: %s", exc)

    def _build_result(
        self,
        process_started: bool,
        mcp_handshake: bool,
        tools_discovered: List[str],
        smoke_test: Optional[SmokeTestResult],
        errors: List[str],
    ) -> VerificationResult:
        """Construct the final ``VerificationResult`` with a verdict."""
        if not process_started:
            verdict = "failed"
        elif not mcp_handshake:
            verdict = "failed"
        elif errors and not tools_discovered:
            verdict = "failed"
        elif errors:
            verdict = "partially_working"
        elif smoke_test and smoke_test.result != "ok":
            verdict = "partially_working"
        else:
            verdict = "fully_operational"

        return VerificationResult(
            process_started=process_started,
            mcp_handshake=mcp_handshake,
            tools_discovered=tools_discovered,
            smoke_test=smoke_test,
            verdict=verdict,
            errors=errors,
        )

    # -- Self-heal auto-fix logic ------------------------------------------

    async def _attempt_auto_fix(
        self,
        category: str,
        command: str,
        server_name: str,
        error: str,
    ) -> Tuple[bool, Optional[str]]:
        """Attempt an automatic fix based on the error category.

        Returns ``(attempted, result_message)``.
        """
        if category == "missing_binary":
            return await self._fix_missing_binary(command)
        elif category == "missing_node_module":
            return await self._fix_missing_node_module(command, error)
        elif category == "missing_browser":
            return await self._fix_missing_browser()
        elif category == "permission":
            return await self._fix_permission(command)
        elif category == "port_conflict":
            return False, (
                "Port conflict detected. Manual intervention required: "
                "identify and stop the conflicting process."
            )
        elif category == "missing_credentials":
            return False, (
                "Credentials are missing. Set the required environment "
                "variable and try again."
            )
        elif category == "timeout":
            return False, (
                "Server timed out. Try increasing the timeout or checking "
                "network connectivity."
            )
        elif category == "connection_refused":
            return False, (
                "Connection refused. Ensure any required backend services "
                "are running."
            )

        return False, None

    async def _fix_missing_binary(
        self,
        command: str,
    ) -> Tuple[bool, Optional[str]]:
        """Check if the binary exists and provide targeted advice."""
        # Check common package managers.
        which_result = shutil.which(command)
        if which_result:
            return False, (
                f"Binary '{command}' found at {which_result} but the server "
                f"still failed to start. The issue may be with arguments or "
                f"the working directory."
            )

        # Try to detect if it is an npx-style command.
        if command == "npx" or command == "node":
            node_path = shutil.which("node")
            if node_path is None:
                return False, (
                    "Node.js is not installed. Install it from "
                    "https://nodejs.org/ or via your system package manager."
                )
            return False, (
                f"Node.js found at {node_path} but '{command}' is not "
                "available. Try reinstalling Node.js or running "
                "'npm install -g npx'."
            )

        if command == "uvx" or command == "uv":
            return await self._try_install_uv()

        return False, (
            f"Binary '{command}' is not installed. Install it using your "
            "system package manager or the official installation instructions."
        )

    async def _fix_missing_node_module(
        self,
        command: str,
        error: str,
    ) -> Tuple[bool, Optional[str]]:
        """Attempt ``npm install`` to restore missing Node modules."""
        npm_path = shutil.which("npm")
        if npm_path is None:
            return False, (
                "npm is not installed. Install Node.js from "
                "https://nodejs.org/ to get npm."
            )

        # Try a global npm install if we can extract the package name.
        # This is a best-effort approach.
        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "install", "-g", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(), timeout=60,
            )
            if proc.returncode == 0:
                return True, (
                    f"Successfully ran 'npm install -g {command}'. "
                    "Try verifying the server again."
                )
            else:
                stderr_text = stderr_data.decode("utf-8", errors="replace")
                return False, (
                    f"'npm install -g {command}' failed: {stderr_text[:300]}"
                )
        except asyncio.TimeoutError:
            return False, "npm install timed out after 60 seconds"
        except Exception as exc:
            return False, f"Failed to run npm install: {exc}"

    async def _fix_missing_browser(self) -> Tuple[bool, Optional[str]]:
        """Attempt to install Chromium via puppeteer."""
        npx_path = shutil.which("npx")
        if npx_path is None:
            return False, (
                "npx is not available. Install Node.js from "
                "https://nodejs.org/ first, then run "
                "'npx puppeteer install chromium'."
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                "npx", "puppeteer", "install", "chromium",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(), timeout=120,
            )
            if proc.returncode == 0:
                return True, (
                    "Successfully installed Chromium via puppeteer. "
                    "Try verifying the server again."
                )
            else:
                stderr_text = stderr_data.decode("utf-8", errors="replace")
                return False, (
                    f"'npx puppeteer install chromium' failed: "
                    f"{stderr_text[:300]}"
                )
        except asyncio.TimeoutError:
            return False, "Chromium installation timed out after 120 seconds"
        except Exception as exc:
            return False, f"Failed to install Chromium: {exc}"

    async def _fix_permission(
        self,
        command: str,
    ) -> Tuple[bool, Optional[str]]:
        """Suggest permission fixes without running dangerous commands."""
        which_result = shutil.which(command)
        if which_result:
            return False, (
                f"Binary found at '{which_result}'. Try running: "
                f"chmod +x {which_result}"
            )
        return False, (
            f"Binary '{command}' not found. If it exists at a known path, "
            "ensure it has execute permissions (chmod +x)."
        )

    async def _try_install_uv(self) -> Tuple[bool, Optional[str]]:
        """Attempt to install uv (which provides uvx)."""
        curl_path = shutil.which("curl")
        if curl_path is None:
            return False, (
                "uv/uvx is not installed and 'curl' is not available to "
                "run the installer. Install uv manually from "
                "https://docs.astral.sh/uv/"
            )

        try:
            proc = await asyncio.create_subprocess_shell(
                "curl -LsSf https://astral.sh/uv/install.sh | sh",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(), timeout=60,
            )
            if proc.returncode == 0:
                return True, (
                    "Successfully installed uv/uvx. You may need to "
                    "restart your shell or source your profile for the "
                    "PATH changes to take effect."
                )
            else:
                stderr_text = stderr_data.decode("utf-8", errors="replace")
                return False, (
                    f"uv installer failed: {stderr_text[:300]}"
                )
        except asyncio.TimeoutError:
            return False, "uv installation timed out after 60 seconds"
        except Exception as exc:
            return False, f"Failed to install uv: {exc}"

    # -- Ecosystem health helpers ------------------------------------------

    async def _check_single_server_health(
        self,
        name: str,
        entry: MCPConfigEntry,
    ) -> ServerHealthReport:
        """Verify a single server and produce a ``ServerHealthReport``."""
        start = time.monotonic()
        suggestion: Optional[str] = None

        try:
            result = await self.verify_server(
                server_name=name,
                command=entry.command,
                args=entry.args,
                env=entry.env,
            )

            latency_ms = int((time.monotonic() - start) * 1000)

            if result.verdict == "fully_operational":
                status = HealthStatus.HEALTHY
                error = None
            elif result.verdict == "partially_working":
                status = HealthStatus.DEGRADED
                error = "; ".join(result.errors) if result.errors else None
            else:
                status = HealthStatus.UNHEALTHY
                error = "; ".join(result.errors) if result.errors else "Verification failed"

            # If unhealthy or degraded, run self-heal to get a suggestion.
            if status in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED) and error:
                heal_result = await self.self_heal(
                    server_name=name,
                    error=error,
                    command=entry.command,
                )
                suggestion = heal_result.get("suggestion")

            return ServerHealthReport(
                name=name,
                status=status,
                latency_ms=latency_ms,
                tools_count=len(result.tools_discovered),
                error=error,
                suggestion=suggestion,
            )

        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.exception("Health check failed for '%s'", name)
            return ServerHealthReport(
                name=name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                tools_count=None,
                error=f"Health check exception: {exc}",
                suggestion="An unexpected error occurred during the health check.",
            )


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

async def verify_server(
    server_name: str,
    command: str,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> VerificationResult:
    """Convenience wrapper: verify a single MCP server."""
    verifier = ServerVerifier(timeout=timeout)
    return await verifier.verify_server(server_name, command, args, env)


async def self_heal(
    server_name: str,
    error: str,
    command: str,
) -> Dict[str, Any]:
    """Convenience wrapper: attempt self-healing for a server error."""
    verifier = ServerVerifier()
    return await verifier.self_heal(server_name, error, command)


async def check_ecosystem_health(
    config: Dict[str, MCPConfigEntry],
    timeout: float = _DEFAULT_TIMEOUT,
) -> EcosystemHealthResult:
    """Convenience wrapper: check health of all configured MCP servers."""
    verifier = ServerVerifier(timeout=timeout)
    return await verifier.check_ecosystem_health(config)
