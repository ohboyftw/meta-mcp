"""
Installation Logging Manager for Meta MCP Server.

This module provides comprehensive logging and analysis for MCP server installation attempts,
including success tracking, error analysis, and detailed debugging information.
"""

import asyncio
import json
import logging
import platform
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any, Tuple

from .models import (
    InstallationLogEntry,
    InstallationError,
    InstallationSession,
    ErrorCategory,
)

logger = logging.getLogger(__name__)


class InstallationLogManager:
    """Manages detailed logging of MCP server installation attempts."""

    def __init__(self):
        self.log_dir = Path.home() / ".mcp-manager" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Log file paths
        self.attempts_log = self.log_dir / "installation_attempts.jsonl"
        self.errors_summary = self.log_dir / "errors_summary.json"
        self.failed_installs = self.log_dir / "failed_installs.json"
        self.session_logs_dir = self.log_dir / "session_logs"
        self.session_logs_dir.mkdir(exist_ok=True)

        # Current session
        self.current_session: Optional[InstallationSession] = None

    def start_session(
        self, server_name: str, option_name: str, install_command: str
    ) -> str:
        """Start a new installation session and return session ID."""
        session_id = str(uuid.uuid4())

        self.current_session = InstallationSession(
            session_id=session_id,
            server_name=server_name,
            option_name=option_name,
            install_command=install_command,
            started_at=datetime.now(),
            system_info=self._get_system_info(),
            attempts=[],
        )

        logger.info(
            f"Started installation session {session_id} for {server_name}-{option_name}"
        )
        return session_id

    def end_session(self, success: bool, final_message: str) -> None:
        """End the current installation session."""
        if not self.current_session:
            logger.warning("No active session to end")
            return

        self.current_session.ended_at = datetime.now()
        self.current_session.success = success
        self.current_session.final_message = final_message
        self.current_session.duration_seconds = (
            self.current_session.ended_at - self.current_session.started_at
        ).total_seconds()

        # Save session log
        self._save_session_log()

        # Update summary logs
        self._update_attempts_log()
        if not success:
            self._update_failed_installs_log()
        self._update_errors_summary()

        logger.info(
            f"Ended installation session {self.current_session.session_id} - Success: {success}"
        )
        self.current_session = None

    async def log_installation_attempt(
        self, command: str, attempt_type: str = "primary", cwd: Optional[str] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Execute and log an installation command with detailed capture.

        Returns (success, message, log_data)
        """
        if not self.current_session:
            raise RuntimeError("No active session - call start_session() first")

        attempt_start = time.time()
        attempt_id = len(self.current_session.attempts) + 1

        log_entry = InstallationLogEntry(
            attempt_id=attempt_id,
            command=command,
            attempt_type=attempt_type,
            started_at=datetime.now(),
            cwd=cwd or str(Path.home()),
        )

        try:
            # Execute the command with detailed logging
            success, stdout, stderr, return_code = await self._execute_with_logging(
                command, cwd
            )

            # Complete the log entry
            log_entry.ended_at = datetime.now()
            log_entry.duration_seconds = time.time() - attempt_start
            log_entry.return_code = return_code
            log_entry.stdout = stdout
            log_entry.stderr = stderr
            log_entry.success = success

            # Analyze any errors
            if not success:
                log_entry.error = self._analyze_error(stderr, stdout, command)

            # Add to session
            self.current_session.attempts.append(log_entry)

            # Return simplified message for compatibility
            message = stdout if success else stderr
            log_data = {
                "attempt_id": attempt_id,
                "duration": log_entry.duration_seconds,
                "return_code": return_code,
                "error_category": log_entry.error.category if log_entry.error else None,
            }

            return success, message, log_data

        except Exception as e:
            # Handle execution errors
            log_entry.ended_at = datetime.now()
            log_entry.duration_seconds = time.time() - attempt_start
            log_entry.success = False
            log_entry.error = InstallationError(
                category=ErrorCategory.SYSTEM_ERROR,
                message=str(e),
                details={"exception_type": type(e).__name__},
            )

            self.current_session.attempts.append(log_entry)

            return False, str(e), {"attempt_id": attempt_id, "exception": True}

    async def _execute_with_logging(
        self, command: str, cwd: Optional[str] = None
    ) -> Tuple[bool, str, str, int]:
        """Execute command and capture detailed output."""
        try:
            cmd_parts = command.split()
            work_dir = Path(cwd) if cwd else Path.home()

            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
            )

            stdout_bytes, stderr_bytes = await process.communicate()

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            success = process.returncode == 0
            return success, stdout, stderr, process.returncode

        except Exception as e:
            return False, "", str(e), -1

    def _analyze_error(
        self, stderr: str, stdout: str, command: str
    ) -> InstallationError:
        """Analyze error output and categorize the error."""
        error_text = stderr.lower() + stdout.lower()
        command_lower = command.lower()

        # Determine error category
        if "permission denied" in error_text or "eacces" in error_text:
            category = ErrorCategory.PERMISSION_ERROR
            suggestion = "Try running with sudo or check file permissions"
        elif (
            "network" in error_text
            or "connection" in error_text
            or "timeout" in error_text
        ):
            category = ErrorCategory.NETWORK_ERROR
            suggestion = "Check internet connection and try again"
        elif "not found" in error_text and (
            "npm" in command_lower or "npx" in command_lower
        ):
            category = ErrorCategory.DEPENDENCY_MISSING
            suggestion = "Install Node.js and npm from https://nodejs.org/"
        elif "not found" in error_text and "uvx" in command_lower:
            category = ErrorCategory.DEPENDENCY_MISSING
            suggestion = (
                "Install uv/uvx using: curl -LsSf https://astral.sh/uv/install.sh | sh"
            )
        elif "404" in error_text or "not found" in error_text:
            category = ErrorCategory.PACKAGE_NOT_FOUND
            suggestion = "Package may not exist or URL is incorrect"
        elif "lockfile" in error_text:
            category = ErrorCategory.ENVIRONMENT_ISSUE
            suggestion = "Remove lock files and try again"
        elif "disk" in error_text or "space" in error_text:
            category = ErrorCategory.SYSTEM_ERROR
            suggestion = "Free up disk space and try again"
        else:
            category = ErrorCategory.UNKNOWN
            suggestion = "Check the full error output for specific details"

        return InstallationError(
            category=category,
            message=stderr[:500] if stderr else stdout[:500],  # Truncate long messages
            details={
                "full_stderr": stderr,
                "full_stdout": stdout,
                "command": command,
                "suggestion": suggestion,
            },
        )

    def _get_system_info(self) -> Dict[str, Any]:
        """Collect system information for debugging."""
        return {
            "platform": platform.platform(),
            "python_version": sys.version,
            "architecture": platform.architecture(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "system": platform.system(),
            "release": platform.release(),
            "timestamp": datetime.now().isoformat(),
        }

    def _save_session_log(self) -> None:
        """Save detailed session log to individual file."""
        if not self.current_session:
            return

        session_file = self.session_logs_dir / f"{self.current_session.session_id}.json"
        try:
            with open(session_file, "w") as f:
                json.dump(self.current_session.model_dump(), f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save session log: {e}")

    def _update_attempts_log(self) -> None:
        """Update the main attempts log (JSONL format)."""
        if not self.current_session:
            return

        try:
            # Create summary entry for JSONL log
            summary = {
                "session_id": self.current_session.session_id,
                "server_name": self.current_session.server_name,
                "option_name": self.current_session.option_name,
                "install_command": self.current_session.install_command,
                "success": self.current_session.success,
                "started_at": self.current_session.started_at.isoformat(),
                "ended_at": (
                    self.current_session.ended_at.isoformat()
                    if self.current_session.ended_at
                    else None
                ),
                "duration_seconds": self.current_session.duration_seconds,
                "attempts_count": len(self.current_session.attempts),
                "final_message": self.current_session.final_message,
                "system": self.current_session.system_info.get("system"),
                "platform": self.current_session.system_info.get("platform"),
            }

            with open(self.attempts_log, "a") as f:
                f.write(json.dumps(summary, default=str) + "\n")

        except Exception as e:
            logger.error(f"Failed to update attempts log: {e}")

    def _update_failed_installs_log(self) -> None:
        """Update the failed installations log."""
        if not self.current_session or self.current_session.success:
            return

        try:
            # Load existing failed installs
            failed_data = {}
            if self.failed_installs.exists():
                with open(self.failed_installs, "r") as f:
                    failed_data = json.load(f)

            server_key = (
                f"{self.current_session.server_name}-{self.current_session.option_name}"
            )

            # Add or update entry
            failed_data[server_key] = {
                "server_name": self.current_session.server_name,
                "option_name": self.current_session.option_name,
                "install_command": self.current_session.install_command,
                "last_attempt": self.current_session.started_at.isoformat(),
                "session_id": self.current_session.session_id,
                "error_categories": [
                    attempt.error.category
                    for attempt in self.current_session.attempts
                    if attempt.error
                ],
                "final_message": self.current_session.final_message,
                "attempt_count": len(self.current_session.attempts),
            }

            with open(self.failed_installs, "w") as f:
                json.dump(failed_data, f, indent=2, default=str)

        except Exception as e:
            logger.error(f"Failed to update failed installs log: {e}")

    def _update_errors_summary(self) -> None:
        """Update the errors summary with categorized statistics."""
        try:
            # Load existing summary
            summary_data = {
                "last_updated": datetime.now().isoformat(),
                "error_categories": {},
                "server_failure_rates": {},
                "common_issues": [],
            }

            if self.errors_summary.exists():
                with open(self.errors_summary, "r") as f:
                    summary_data = json.load(f)

            # Update with current session data if it failed
            if self.current_session and not self.current_session.success:
                server_key = f"{self.current_session.server_name}-{self.current_session.option_name}"

                # Count error categories
                for attempt in self.current_session.attempts:
                    if attempt.error:
                        category = attempt.error.category
                        summary_data["error_categories"][category] = (
                            summary_data["error_categories"].get(category, 0) + 1
                        )

                # Track server failure rates
                if server_key not in summary_data["server_failure_rates"]:
                    summary_data["server_failure_rates"][server_key] = {
                        "attempts": 0,
                        "failures": 0,
                    }

                summary_data["server_failure_rates"][server_key]["attempts"] += 1
                summary_data["server_failure_rates"][server_key]["failures"] += 1

            summary_data["last_updated"] = datetime.now().isoformat()

            with open(self.errors_summary, "w") as f:
                json.dump(summary_data, f, indent=2, default=str)

        except Exception as e:
            logger.error(f"Failed to update errors summary: {e}")

    def get_installation_stats(self) -> Dict[str, Any]:
        """Get installation statistics and analysis."""
        try:
            stats = {
                "total_attempts": 0,
                "successful_installs": 0,
                "failed_installs": 0,
                "error_categories": {},
                "problematic_servers": [],
                "recent_attempts": [],
            }

            # Read attempts log
            if self.attempts_log.exists():
                with open(self.attempts_log, "r") as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())
                            stats["total_attempts"] += 1

                            if entry.get("success"):
                                stats["successful_installs"] += 1
                            else:
                                stats["failed_installs"] += 1

                            stats["recent_attempts"].append(
                                {
                                    "server": f"{entry['server_name']}-{entry['option_name']}",
                                    "success": entry.get("success", False),
                                    "timestamp": entry.get("started_at"),
                                    "duration": entry.get("duration_seconds"),
                                }
                            )
                        except json.JSONDecodeError:
                            continue

            # Read errors summary
            if self.errors_summary.exists():
                with open(self.errors_summary, "r") as f:
                    error_data = json.load(f)
                    stats["error_categories"] = error_data.get("error_categories", {})

            # Sort recent attempts by timestamp (most recent first)
            stats["recent_attempts"] = sorted(
                stats["recent_attempts"][-50:],  # Last 50 attempts
                key=lambda x: x.get("timestamp", ""),
                reverse=True,
            )

            return stats

        except Exception as e:
            logger.error(f"Failed to get installation stats: {e}")
            return {"error": str(e)}

    def get_session_details(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific session."""
        try:
            session_file = self.session_logs_dir / f"{session_id}.json"
            if session_file.exists():
                with open(session_file, "r") as f:
                    return json.load(f)
            return None
        except Exception as e:
            logger.error(f"Failed to get session details: {e}")
            return None

    def cleanup_old_logs(self, days_to_keep: int = 30) -> int:
        """Clean up log files older than specified days. Returns number of files cleaned."""
        try:
            cutoff_time = datetime.now().timestamp() - (days_to_keep * 24 * 60 * 60)
            cleaned_count = 0

            # Clean session logs
            for session_file in self.session_logs_dir.glob("*.json"):
                if session_file.stat().st_mtime < cutoff_time:
                    session_file.unlink()
                    cleaned_count += 1

            logger.info(f"Cleaned up {cleaned_count} old session logs")
            return cleaned_count

        except Exception as e:
            logger.error(f"Failed to cleanup old logs: {e}")
            return 0
