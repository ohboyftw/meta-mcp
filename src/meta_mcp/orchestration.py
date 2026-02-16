"""
Live Server Orchestration (R8).

Lifecycle management for MCP server processes: start, stop, restart, tool
discovery via MCP JSON-RPC, and cross-server workflow execution.

Communication uses newline-delimited JSON-RPC 2.0 over stdin/stdout.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import (
    ServerProcess,
    DiscoveredTool,
    ServerToolsResult,
    MCPServerStatus,
    WorkflowExecutionStep,
    WorkflowExecutionResult,
    WorkflowStepStatus,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STARTUP_TIMEOUT_S: float = 10.0
_TOOL_CALL_TIMEOUT_S: float = 30.0
_SHUTDOWN_GRACE_S: float = 5.0
_MCP_PROTOCOL_VERSION = "2024-11-05"
_PREVIOUS_OUTPUT_TOKEN = "$previous"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_jsonrpc_request(
    method: str,
    params: Optional[Dict[str, Any]] = None,
    request_id: int = 1,
) -> bytes:
    """Serialise a JSON-RPC 2.0 request to newline-delimited bytes."""
    payload: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    return (json.dumps(payload) + "\n").encode("utf-8")


async def _read_jsonrpc_response(
    stdout: asyncio.StreamReader,
    timeout: float,
) -> Dict[str, Any]:
    """Read lines from *stdout* until a JSON-RPC response (with ``id``) arrives.

    Notifications (no ``id``) are logged and skipped so that progress or log
    messages from the server don't block the caller.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError("Timed out waiting for JSON-RPC response")
        try:
            raw_line = await asyncio.wait_for(stdout.readline(), timeout=remaining)
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError("Timed out waiting for JSON-RPC response")

        if not raw_line:
            raise ConnectionError("Server process closed stdout unexpectedly")

        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Non-JSON line from server: %s", line[:200])
            continue

        if "id" not in msg:
            logger.debug("Server notification: %s", line[:300])
            continue

        return msg


def _substitute_previous_output(
    arguments: Dict[str, Any],
    previous_output: Any,
) -> Dict[str, Any]:
    """Replace ``$previous`` tokens in *arguments* with *previous_output*.

    Shallow substitution: exact-match string values are replaced directly;
    values *containing* the token receive the string representation instead.
    """
    if previous_output is None:
        return arguments

    prev_str = (
        json.dumps(previous_output)
        if not isinstance(previous_output, str)
        else previous_output
    )
    result: Dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, str):
            if value == _PREVIOUS_OUTPUT_TOKEN:
                result[key] = previous_output
            elif _PREVIOUS_OUTPUT_TOKEN in value:
                result[key] = value.replace(_PREVIOUS_OUTPUT_TOKEN, prev_str)
            else:
                result[key] = value
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# ServerOrchestrator
# ---------------------------------------------------------------------------

class ServerOrchestrator:
    """Manages the full lifecycle of MCP server processes.

    Maintains a registry of running servers (keyed by name) and provides
    helpers for tool discovery and cross-server workflow execution.
    """

    def __init__(self) -> None:
        self._servers: Dict[str, ServerProcess] = {}
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        self._next_request_id: int = 1

    @property
    def running_servers(self) -> Dict[str, ServerProcess]:
        """Snapshot of currently tracked server models."""
        return dict(self._servers)

    def _alloc_request_id(self) -> int:
        rid = self._next_request_id
        self._next_request_id += 1
        return rid

    # -- start / stop / restart ----------------------------------------------

    async def start_server(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> ServerProcess:
        """Start an MCP server as a child process and return its ``ServerProcess``."""
        if name in self._servers and self._servers[name].status == MCPServerStatus.RUNNING:
            logger.warning("Server '%s' already running (pid=%s)", name, self._servers[name].pid)
            return self._servers[name]

        full_args: List[str] = args or []
        merged_env = {**os.environ, **(env or {})}
        logger.info("Starting server '%s': %s %s", name, command, " ".join(full_args))

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    command, *full_args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=merged_env,
                ),
                timeout=_STARTUP_TIMEOUT_S,
            )
        except FileNotFoundError:
            logger.error("Command not found: %s", command)
            self._servers[name] = ServerProcess(
                server_name=name, pid=None, status=MCPServerStatus.ERROR,
                started_at=None, command=command,
            )
            raise RuntimeError(f"Command not found: {command}")
        except asyncio.TimeoutError:
            logger.error("Timed out starting server '%s'", name)
            self._servers[name] = ServerProcess(
                server_name=name, pid=None, status=MCPServerStatus.ERROR,
                started_at=None, command=command,
            )
            raise RuntimeError(f"Timed out starting server '{name}'")

        model = ServerProcess(
            server_name=name, pid=proc.pid, status=MCPServerStatus.RUNNING,
            started_at=datetime.now(), command=command,
        )
        self._servers[name] = model
        self._processes[name] = proc
        logger.info("Server '%s' started (pid=%d)", name, proc.pid)
        return model

    async def stop_server(self, name: str) -> ServerProcess:
        """Gracefully stop a running server (SIGTERM, then SIGKILL after 5 s)."""
        if name not in self._servers:
            raise KeyError(f"No server tracked with name '{name}'")

        model = self._servers[name]
        proc = self._processes.get(name)

        if proc is None or proc.returncode is not None:
            logger.info("Server '%s' already exited", name)
            model.status = MCPServerStatus.STOPPED
            model.pid = None
            self._cleanup(name)
            return model

        logger.info("Stopping server '%s' (pid=%d) ...", name, proc.pid)

        # Phase 1 -- SIGTERM
        try:
            proc.terminate()
        except ProcessLookupError:
            model.status = MCPServerStatus.STOPPED
            model.pid = None
            self._cleanup(name)
            return model

        try:
            await asyncio.wait_for(proc.wait(), timeout=_SHUTDOWN_GRACE_S)
            logger.info("Server '%s' terminated gracefully", name)
        except asyncio.TimeoutError:
            # Phase 2 -- SIGKILL
            logger.warning("Server '%s' still alive after %.0fs, sending SIGKILL", name, _SHUTDOWN_GRACE_S)
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                logger.error("Failed to kill server '%s'", name)
                model.status = MCPServerStatus.ERROR
                self._cleanup(name)
                return model

        model.status = MCPServerStatus.STOPPED
        model.pid = None
        self._cleanup(name)
        logger.info("Server '%s' stopped", name)
        return model

    async def restart_server(self, name: str) -> ServerProcess:
        """Stop then re-start a tracked server using its original command."""
        if name not in self._servers:
            raise KeyError(f"No server tracked with name '{name}'")

        command = self._servers[name].command
        logger.info("Restarting server '%s' ...", name)
        await self.stop_server(name)
        return await self.start_server(name=name, command=command)

    # -- tool / prompt discovery ---------------------------------------------

    async def discover_server_tools(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> ServerToolsResult:
        """Start a temporary server, handshake, list tools and prompts, then kill it."""
        full_args: List[str] = args or []
        merged_env = {**os.environ, **(env or {})}
        logger.info("Discovering tools for '%s': %s %s", name, command, " ".join(full_args))

        proc: Optional[asyncio.subprocess.Process] = None
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    command, *full_args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=merged_env,
                ),
                timeout=_STARTUP_TIMEOUT_S,
            )
            assert proc.stdin is not None and proc.stdout is not None

            # --- MCP initialize handshake ---
            init_id = self._alloc_request_id()
            proc.stdin.write(_build_jsonrpc_request(
                "initialize",
                params={
                    "protocolVersion": _MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "meta-mcp-orchestrator", "version": "0.1.0"},
                },
                request_id=init_id,
            ))
            await proc.stdin.drain()

            init_resp = await _read_jsonrpc_response(proc.stdout, timeout=_STARTUP_TIMEOUT_S)
            logger.debug("Initialize response: %s", json.dumps(init_resp)[:500])
            if "error" in init_resp:
                err = init_resp["error"]
                raise RuntimeError(f"MCP initialize failed: {err.get('message', err)}")

            # Send initialized notification
            proc.stdin.write(
                (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
                .encode("utf-8")
            )
            await proc.stdin.drain()

            # --- tools/list ---
            tools: List[DiscoveredTool] = []
            tools_id = self._alloc_request_id()
            proc.stdin.write(_build_jsonrpc_request("tools/list", request_id=tools_id))
            await proc.stdin.drain()

            tools_resp = await _read_jsonrpc_response(proc.stdout, timeout=_TOOL_CALL_TIMEOUT_S)
            logger.debug("tools/list response: %s", json.dumps(tools_resp)[:500])
            if "result" in tools_resp:
                for td in tools_resp["result"].get("tools", []):
                    tools.append(DiscoveredTool(
                        name=td.get("name", "unknown"),
                        description=td.get("description", ""),
                        parameters=td.get("inputSchema", {}),
                    ))

            # --- prompts/list ---
            prompts: List[Dict[str, Any]] = []
            prompts_id = self._alloc_request_id()
            proc.stdin.write(_build_jsonrpc_request("prompts/list", request_id=prompts_id))
            await proc.stdin.drain()
            try:
                prompts_resp = await _read_jsonrpc_response(proc.stdout, timeout=_TOOL_CALL_TIMEOUT_S)
                if "result" in prompts_resp:
                    prompts = prompts_resp["result"].get("prompts", [])
            except (asyncio.TimeoutError, ConnectionError):
                logger.debug("Server '%s' did not respond to prompts/list", name)

            logger.info("Discovered %d tools and %d prompts for '%s'", len(tools), len(prompts), name)
            return ServerToolsResult(server=name, tools=tools, prompts=prompts)

        except FileNotFoundError:
            logger.error("Command not found during discovery: %s", command)
            return ServerToolsResult(server=name, tools=[], prompts=[])
        except asyncio.TimeoutError:
            logger.error("Timed out during discovery of '%s'", name)
            return ServerToolsResult(server=name, tools=[], prompts=[])
        except Exception:
            logger.exception("Error discovering tools for '%s'", name)
            return ServerToolsResult(server=name, tools=[], prompts=[])
        finally:
            if proc is not None:
                await self._kill_process(proc, label=f"discovery:{name}")

    # -- tool call forwarding ------------------------------------------------

    async def forward_tool_call(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: float = _TOOL_CALL_TIMEOUT_S,
    ) -> Any:
        """Forward a single tool call to a running backend server.

        The server must already be started via ``start_server()``.  If the
        process has exited it will be restarted automatically.

        Returns the extracted tool output (string or structured data).
        Raises ``RuntimeError`` on RPC-level errors.
        """
        proc = await self._ensure_server_running(server_name)
        assert proc.stdin is not None and proc.stdout is not None

        req_id = self._alloc_request_id()
        proc.stdin.write(_build_jsonrpc_request(
            "tools/call",
            params={"name": tool_name, "arguments": arguments},
            request_id=req_id,
        ))
        await proc.stdin.drain()

        response = await _read_jsonrpc_response(proc.stdout, timeout=timeout)

        if "error" in response:
            err = response["error"]
            raise RuntimeError(
                f"Backend '{server_name}' tool '{tool_name}' failed: "
                f"{err.get('message', err)}"
            )

        return self._extract_tool_output(response.get("result", {}))

    # -- workflow execution --------------------------------------------------

    async def execute_workflow(
        self,
        workflow_steps: List[WorkflowExecutionStep],
        workflow_name: str = "unnamed",
    ) -> WorkflowExecutionResult:
        """Execute an ordered sequence of tool calls across one or more servers.

        The ``$previous`` token in step arguments is replaced with the output
        of the immediately preceding step.  Servers are started automatically
        if not already running.
        """
        logger.info("Executing workflow '%s' with %d step(s)", workflow_name, len(workflow_steps))

        overall_start = time.monotonic()
        previous_output: Any = None
        completed_count = 0
        failed = False

        for idx, step in enumerate(workflow_steps):
            step_label = f"{workflow_name}[{idx}] {step.server}/{step.tool}"
            step.status = WorkflowStepStatus.RUNNING
            step_start = time.monotonic()
            logger.info("Workflow step %d/%d: %s", idx + 1, len(workflow_steps), step_label)

            try:
                proc = await self._ensure_server_running(step.server)
                assert proc.stdin is not None and proc.stdout is not None

                resolved_input = _substitute_previous_output(step.input, previous_output)

                req_id = self._alloc_request_id()
                proc.stdin.write(_build_jsonrpc_request(
                    "tools/call",
                    params={"name": step.tool, "arguments": resolved_input},
                    request_id=req_id,
                ))
                await proc.stdin.drain()

                response = await _read_jsonrpc_response(proc.stdout, timeout=_TOOL_CALL_TIMEOUT_S)
                elapsed_ms = int((time.monotonic() - step_start) * 1000)
                step.latency_ms = elapsed_ms

                if "error" in response:
                    err = response["error"]
                    error_msg = err.get("message", str(err))
                    logger.error("Step %s failed: %s", step_label, error_msg)
                    step.status = WorkflowStepStatus.FAILED
                    step.error = error_msg
                    step.output = None
                    failed = True
                    break

                output = self._extract_tool_output(response.get("result", {}))
                step.output = output
                step.status = WorkflowStepStatus.COMPLETED
                previous_output = output
                completed_count += 1
                logger.info("Step %s completed in %dms", step_label, elapsed_ms)

            except Exception as exc:
                step.latency_ms = int((time.monotonic() - step_start) * 1000)
                step.status = WorkflowStepStatus.FAILED
                step.error = str(exc)
                logger.exception("Step %s raised an exception", step_label)
                failed = True
                break

        # Mark remaining steps as skipped.
        for remaining in workflow_steps:
            if remaining.status == WorkflowStepStatus.PENDING:
                remaining.status = WorkflowStepStatus.SKIPPED

        total_time_ms = int((time.monotonic() - overall_start) * 1000)
        overall_status = (
            "completed" if not failed
            else ("failed" if completed_count == 0 else "partial")
        )

        logger.info(
            "Workflow '%s' finished: status=%s, steps=%d/%d, time=%dms",
            workflow_name, overall_status, completed_count, len(workflow_steps), total_time_ms,
        )
        return WorkflowExecutionResult(
            workflow_name=workflow_name,
            steps=workflow_steps,
            overall_status=overall_status,
            total_time_ms=total_time_ms,
        )

    # -- internal helpers ----------------------------------------------------

    def _cleanup(self, name: str) -> None:
        """Remove a server from the internal process tracking dict."""
        self._processes.pop(name, None)

    async def _kill_process(self, proc: asyncio.subprocess.Process, label: str = "unknown") -> None:
        """Terminate and then (if necessary) kill a subprocess."""
        if proc.returncode is not None:
            return
        try:
            proc.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=_SHUTDOWN_GRACE_S)
        except asyncio.TimeoutError:
            logger.warning("Process for '%s' did not exit, sending SIGKILL", label)
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                logger.error("Could not kill process for '%s'", label)
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass

    async def _ensure_server_running(self, name: str) -> asyncio.subprocess.Process:
        """Return a live subprocess handle, restarting the server if it exited."""
        proc = self._processes.get(name)
        if proc is not None and proc.returncode is None:
            return proc

        model = self._servers.get(name)
        if model is None:
            raise RuntimeError(
                f"Server '{name}' is not tracked by the orchestrator. "
                "Call start_server() first."
            )

        logger.warning(
            "Server '%s' not running (rc=%s), restarting ...",
            name, proc.returncode if proc else "n/a",
        )
        await self.start_server(name=name, command=model.command)

        proc = self._processes.get(name)
        if proc is None or proc.returncode is not None:
            raise RuntimeError(f"Failed to restart server '{name}'")

        # Handshake so the server is ready for tool calls.
        await self._perform_handshake(proc, name)
        return proc

    async def _perform_handshake(self, proc: asyncio.subprocess.Process, name: str) -> None:
        """Send MCP ``initialize`` + ``notifications/initialized``."""
        assert proc.stdin is not None and proc.stdout is not None

        init_id = self._alloc_request_id()
        proc.stdin.write(_build_jsonrpc_request(
            "initialize",
            params={
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "meta-mcp-orchestrator", "version": "0.1.0"},
            },
            request_id=init_id,
        ))
        await proc.stdin.drain()

        init_resp = await _read_jsonrpc_response(proc.stdout, timeout=_STARTUP_TIMEOUT_S)
        if "error" in init_resp:
            err = init_resp["error"]
            raise RuntimeError(f"MCP handshake failed for '{name}': {err.get('message', err)}")

        proc.stdin.write(
            (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            .encode("utf-8")
        )
        await proc.stdin.drain()
        logger.info("MCP handshake completed for server '%s'", name)

    @staticmethod
    def _extract_tool_output(result_data: Any) -> Any:
        """Collapse MCP ``tools/call`` content list into a plain value.

        Single text elements are unwrapped to a string; multi-element lists
        are returned as-is for the caller to inspect.
        """
        if not isinstance(result_data, dict):
            return result_data
        content = result_data.get("content")
        if not isinstance(content, list):
            return result_data
        if len(content) == 1 and content[0].get("type") == "text":
            return content[0].get("text", "")
        texts = []
        for item in content:
            texts.append(item.get("text", "") if item.get("type") == "text" else item)
        return texts if len(texts) != 1 else texts[0]

    # -- shutdown ------------------------------------------------------------

    async def shutdown(self) -> None:
        """Stop all tracked servers and release resources."""
        logger.info("Shutting down orchestrator (%d server(s) tracked) ...", len(self._servers))
        for name in list(self._servers.keys()):
            try:
                await self.stop_server(name)
            except Exception:
                logger.exception("Error stopping server '%s' during shutdown", name)
        self._servers.clear()
        self._processes.clear()
        logger.info("Orchestrator shutdown complete")
