"""Tests for ConversationalMemory (R7)."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.meta_mcp.memory import ConversationalMemory, _MAX_RECORDS


class TestConversationalMemory:
    """Core memory operations."""

    def test_init_fresh(self, tmp_path):
        """New memory file starts with empty state."""
        mem = ConversationalMemory(memory_path=str(tmp_path / "mem.json"))
        assert mem.get_installation_history() == []

    def test_record_installation(self, tmp_path):
        mem = ConversationalMemory(memory_path=str(tmp_path / "mem.json"))
        record = mem.record_installation(
            server="brave-search", option="official", success=True,
        )
        assert record.server_name == "brave-search"
        assert record.success is True
        history = mem.get_installation_history()
        assert len(history) == 1
        assert history[0].server_name == "brave-search"

    def test_record_failure(self, tmp_path):
        mem = ConversationalMemory(memory_path=str(tmp_path / "mem.json"))
        record = mem.record_failure(
            server="broken-server",
            error_sig="missing_binary",
            error_msg="Command not found: broken-server",
        )
        assert record.server_name == "broken-server"
        assert record.error_signature == "missing_binary"

    def test_check_failure_memory_returns_none_when_empty(self, tmp_path):
        mem = ConversationalMemory(memory_path=str(tmp_path / "mem.json"))
        assert mem.check_failure_memory("nonexistent") is None

    def test_check_failure_memory_returns_most_recent(self, tmp_path):
        mem = ConversationalMemory(memory_path=str(tmp_path / "mem.json"))
        mem.record_failure(server="srv", error_sig="e1", error_msg="first")
        mem.record_failure(server="srv", error_sig="e2", error_msg="second")
        result = mem.check_failure_memory("srv")
        assert result is not None
        assert result.error_signature == "e2"

    def test_persistence_across_instances(self, tmp_path):
        path = str(tmp_path / "mem.json")
        mem1 = ConversationalMemory(memory_path=path)
        mem1.record_installation(server="s1", option="o1", success=True)

        mem2 = ConversationalMemory(memory_path=path)
        history = mem2.get_installation_history()
        assert len(history) == 1
        assert history[0].server_name == "s1"

    def test_corrupt_file_resets(self, tmp_path):
        path = tmp_path / "mem.json"
        path.write_text("NOT VALID JSON", encoding="utf-8")
        mem = ConversationalMemory(memory_path=str(path))
        assert mem.get_installation_history() == []

    def test_trim_keeps_max_records(self, tmp_path):
        mem = ConversationalMemory(memory_path=str(tmp_path / "mem.json"))
        for i in range(_MAX_RECORDS + 5):
            mem.record_installation(server=f"s{i}", option="o", success=True)
        history = mem.get_installation_history()
        assert len(history) <= _MAX_RECORDS


class TestPreferences:
    """Preference learning from installation history."""

    def test_preferred_install_method(self, tmp_path):
        mem = ConversationalMemory(memory_path=str(tmp_path / "mem.json"))
        for _ in range(3):
            mem.record_installation(server="s", option="official", success=True)
        mem.record_installation(server="s", option="enhanced", success=True)
        prefs = mem.get_preferences()
        assert prefs.preferred_install_method == "official"

    def test_update_preferences_increments_interaction(self, tmp_path):
        mem = ConversationalMemory(memory_path=str(tmp_path / "mem.json"))
        prefs = mem.update_preferences("install")
        assert prefs.interaction_count == 1
        prefs = mem.update_preferences("search")
        assert prefs.interaction_count == 2

    def test_prefers_official(self, tmp_path):
        mem = ConversationalMemory(memory_path=str(tmp_path / "mem.json"))
        for _ in range(5):
            mem.record_installation(server="s", option="official", success=True)
        for _ in range(2):
            mem.record_installation(server="s", option="enhanced", success=True)
        prefs = mem.get_preferences()
        assert prefs.prefers_official is True


class TestHistoryQueries:
    """Installation history query filtering."""

    def test_filter_by_project(self, tmp_path):
        mem = ConversationalMemory(memory_path=str(tmp_path / "mem.json"))
        mem.record_installation(
            server="s1", option="o", success=True, project_path="/proj/a",
        )
        mem.record_installation(
            server="s2", option="o", success=True, project_path="/proj/b",
        )
        result = mem.get_installation_history(project="/proj/a")
        assert len(result) == 1
        assert result[0].server_name == "s1"

    def test_history_sorted_newest_first(self, tmp_path):
        mem = ConversationalMemory(memory_path=str(tmp_path / "mem.json"))
        mem.record_installation(server="first", option="o", success=True)
        mem.record_installation(server="second", option="o", success=True)
        history = mem.get_installation_history()
        assert history[0].server_name == "second"


class TestErrorSignature:
    """Error signature extraction."""

    def test_extract_first_line(self):
        sig = ConversationalMemory._extract_error_signature("Line1\nLine2")
        assert sig == "Line1"

    def test_truncate_long_lines(self):
        long_msg = "x" * 300
        sig = ConversationalMemory._extract_error_signature(long_msg)
        assert len(sig) == 200

    def test_empty_yields_unknown(self):
        sig = ConversationalMemory._extract_error_signature("\n\n")
        assert sig == "unknown_error"
