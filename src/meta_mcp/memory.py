"""
Conversational Memory and Learning (R7).

Persists installation history, failure records, and learned user preferences
to ``~/.mcp-manager/memory.json``.  Every mutating method saves state to disk
immediately.  Thread safety via ``threading.Lock``.
"""

import json
import logging
import threading
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    FailureRecord,
    InstallationRecord,
    MemoryState,
    UserPreferences,
)

logger = logging.getLogger(__name__)

_DEFAULT_MEMORY_FILE = Path.home() / ".mcp-manager" / "memory.json"
_MAX_RECORDS = 1000
_COMBO_WINDOW_MINUTES = 5


class ConversationalMemory:
    """Persistent conversational memory for the MCP manager.

    Records installations, failures, and user preferences so that repeated
    sessions can recall past outcomes and offer progressively better defaults.
    """

    def __init__(self, memory_path: Optional[str] = None) -> None:
        self._path = Path(memory_path) if memory_path else _DEFAULT_MEMORY_FILE
        self._lock = threading.Lock()
        self._state = self._load()

    # ---- persistence -----------------------------------------------------

    def _load(self) -> MemoryState:
        """Load state from disk, returning defaults on any error."""
        if not self._path.exists():
            logger.debug("No memory file at %s; starting fresh", self._path)
            return MemoryState()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            state = MemoryState.model_validate(data)
            logger.info(
                "Loaded memory: %d installations, %d failures",
                len(state.installations), len(state.failures),
            )
            return state
        except json.JSONDecodeError as exc:
            logger.warning("Corrupt memory file -- resetting: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load memory -- resetting: %s", exc)
        return MemoryState()

    def _save(self) -> None:
        """Persist state via atomic tmp-file rename."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._state.last_updated = datetime.now()
            payload = self._state.model_dump(mode="json")
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            tmp.replace(self._path)
            logger.debug("Memory saved to %s", self._path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to save memory: %s", exc)

    def _trim(self) -> None:
        """Keep only the most recent ``_MAX_RECORDS`` entries per list."""
        if len(self._state.installations) > _MAX_RECORDS:
            self._state.installations = self._state.installations[-_MAX_RECORDS:]
        if len(self._state.failures) > _MAX_RECORDS:
            self._state.failures = self._state.failures[-_MAX_RECORDS:]

    # ---- installation tracking -------------------------------------------

    def record_installation(
        self, server: str, option: str, success: bool,
        project_path: Optional[str] = None,
    ) -> InstallationRecord:
        """Append an installation record and recompute derived preferences."""
        record = InstallationRecord(
            server_name=server, option_name=option,
            success=success, project_path=project_path,
            installed_at=datetime.now(),
        )
        with self._lock:
            self._state.installations.append(record)
            self._trim()
            self._recompute_preferences()
            self._save()
        logger.info("Recorded install: server=%s option=%s ok=%s", server, option, success)
        return record

    # ---- failure tracking ------------------------------------------------

    @staticmethod
    def _extract_error_signature(error_msg: str) -> str:
        """First non-empty line of *error_msg*, truncated to 200 chars."""
        for line in error_msg.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:200]
        return "unknown_error"

    def record_failure(
        self, server: str, error_sig: str, error_msg: str,
        system_state: Optional[Dict[str, Any]] = None,
    ) -> FailureRecord:
        """Record a failure.  Derives signature from *error_msg* when *error_sig* is empty."""
        signature = error_sig or self._extract_error_signature(error_msg)
        record = FailureRecord(
            server_name=server, error_signature=signature,
            error_message=error_msg, system_state=system_state or {},
            occurred_at=datetime.now(),
        )
        with self._lock:
            self._state.failures.append(record)
            self._trim()
            self._save()
        logger.info("Recorded failure: server=%s sig=%s", server, signature)
        return record

    def check_failure_memory(self, server: str) -> Optional[FailureRecord]:
        """Return the most relevant prior failure for *server*.

        Prefers the most recent record with a ``fix_applied`` value; falls
        back to the most recent failure overall.  Returns ``None`` if none.
        """
        with self._lock:
            candidates = [f for f in self._state.failures if f.server_name == server]
        if not candidates:
            return None
        with_fix = [c for c in candidates if c.fix_applied]
        if with_fix:
            return max(with_fix, key=lambda r: r.occurred_at)
        return max(candidates, key=lambda r: r.occurred_at)

    # ---- preferences -----------------------------------------------------

    def _recompute_preferences(self) -> None:
        """Derive preferences from the full installation history.

        Must be called while ``self._lock`` is held.
        """
        prefs = self._state.preferences
        installs = self._state.installations

        # preferred_install_method -- most-used successful option
        method_counts: Counter[str] = Counter(
            r.option_name for r in installs if r.success
        )
        if method_counts:
            prefs.preferred_install_method = method_counts.most_common(1)[0][0]

        # preferred_clients -- ranked by frequency
        client_counts: Counter[str] = Counter(
            c for r in installs for c in r.client_targets
        )
        if client_counts:
            prefs.preferred_clients = [c for c, _ in client_counts.most_common()]

        # prefers_official -- compare official/recommended vs others
        official_kw = {"official", "recommended"}
        official = sum(
            1 for r in installs
            if r.success and any(k in r.option_name.lower() for k in official_kw)
        )
        enhanced = sum(
            1 for r in installs
            if r.success and not any(k in r.option_name.lower() for k in official_kw)
        )
        if official + enhanced > 0:
            prefs.prefers_official = official >= enhanced

        # common_server_combos
        prefs.common_server_combos = self._detect_server_combos(installs)

    @staticmethod
    def _detect_server_combos(installs: List[InstallationRecord]) -> List[List[str]]:
        """Find servers frequently installed together within a time window.

        Two servers count as "together" when both were installed successfully
        within ``_COMBO_WINDOW_MINUTES`` minutes.  Returns top-10 combos that
        appeared at least twice.
        """
        successful = sorted(
            (r for r in installs if r.success), key=lambda r: r.installed_at,
        )
        combo_counter: Counter[tuple[str, ...]] = Counter()
        window = timedelta(minutes=_COMBO_WINDOW_MINUTES)

        for i, rec in enumerate(successful):
            group = {rec.server_name}
            for other in successful[i + 1:]:
                if other.installed_at - rec.installed_at <= window:
                    group.add(other.server_name)
                else:
                    break
            if len(group) >= 2:
                combo_counter[tuple(sorted(group))] += 1

        return [list(combo) for combo, cnt in combo_counter.most_common(10) if cnt >= 2]

    def get_preferences(self) -> UserPreferences:
        """Return the current learned user preferences (deep copy)."""
        with self._lock:
            return self._state.preferences.model_copy(deep=True)

    def update_preferences(self, action: str) -> UserPreferences:
        """Increment interaction count and recompute preferences.

        *action* is a free-form label (``"install"``, ``"search"``, etc.)
        logged for future analysis hooks.
        """
        with self._lock:
            self._state.preferences.interaction_count += 1
            self._recompute_preferences()
            self._save()
            logger.debug(
                "Preferences updated (action=%s, interactions=%d)",
                action, self._state.preferences.interaction_count,
            )
            return self._state.preferences.model_copy(deep=True)

    # ---- history queries -------------------------------------------------

    def get_installation_history(
        self, project: Optional[str] = None,
    ) -> List[InstallationRecord]:
        """Return installation records sorted newest-first.

        When *project* is given, only records whose ``project_path`` matches
        the exact path or is a sub-path are included.
        """
        with self._lock:
            records = list(self._state.installations)

        if project:
            # Normalise with trailing separator so "/tmp/proj" does not
            # accidentally match "/tmp/proj2".
            norm = project.rstrip("/") + "/"
            records = [
                r for r in records
                if r.project_path is not None
                and (r.project_path == project
                     or r.project_path.rstrip("/") + "/" == norm
                     or r.project_path.startswith(norm))
            ]

        records.sort(key=lambda r: r.installed_at, reverse=True)
        return records
