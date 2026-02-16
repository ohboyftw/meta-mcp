"""Tests for Intent-Based Capability Resolution (R1)."""

import pytest

from src.meta_mcp.intent import IntentEngine, CAPABILITY_MAP, WORKFLOW_TEMPLATES


class TestIntentParsing:
    """Parse natural-language descriptions into capabilities."""

    def test_web_search_keywords(self):
        engine = IntentEngine()
        result = engine.detect_capability_gaps(
            "Search the web for Python documentation",
            installed_servers=[],
        )
        caps = [m.capability for m in result.missing_capabilities]
        assert "web_search" in caps

    def test_database_keywords(self):
        engine = IntentEngine()
        result = engine.detect_capability_gaps(
            "Query the PostgreSQL database for user records",
            installed_servers=[],
        )
        caps = [m.capability for m in result.missing_capabilities]
        assert "database" in caps

    def test_version_control_detected(self):
        engine = IntentEngine()
        result = engine.detect_capability_gaps(
            "Create a pull request on GitHub",
            installed_servers=[],
        )
        caps = [m.capability for m in result.missing_capabilities]
        assert "version_control" in caps

    def test_no_capabilities_on_vague_input(self):
        engine = IntentEngine()
        result = engine.detect_capability_gaps(
            "hello world",
            installed_servers=[],
        )
        assert result.missing_capabilities == [] or len(result.missing_capabilities) == 0

    def test_multiple_capabilities_detected(self):
        engine = IntentEngine()
        result = engine.detect_capability_gaps(
            "Search the web, scrape competitor pages, and save results to a spreadsheet",
            installed_servers=[],
        )
        caps = [m.capability for m in result.missing_capabilities]
        assert len(caps) >= 2


class TestCapabilityGaps:
    """Gap analysis between required and installed capabilities."""

    def test_no_gap_when_server_installed(self):
        engine = IntentEngine()
        result = engine.detect_capability_gaps(
            "Search the web for information",
            installed_servers=["brave-search"],
        )
        missing_caps = [m.capability for m in result.missing_capabilities]
        assert "web_search" not in missing_caps

    def test_covered_capabilities_listed(self):
        engine = IntentEngine()
        result = engine.detect_capability_gaps(
            "Search the web for information",
            installed_servers=["brave-search"],
        )
        assert "web_search" in result.currently_available

    def test_missing_capability_has_priority(self):
        engine = IntentEngine()
        result = engine.detect_capability_gaps(
            "Search the web and query the database",
            installed_servers=[],
        )
        for m in result.missing_capabilities:
            assert m.priority in ("high", "medium", "low")

    def test_first_gap_is_high_priority(self):
        engine = IntentEngine()
        result = engine.detect_capability_gaps(
            "Search the web",
            installed_servers=[],
        )
        if result.missing_capabilities:
            assert result.missing_capabilities[0].priority == "high"

    def test_suggested_workflow_narrative(self):
        engine = IntentEngine()
        result = engine.detect_capability_gaps(
            "Search the web for Python docs",
            installed_servers=[],
        )
        assert result.suggested_workflow
        assert len(result.suggested_workflow) > 10


class TestWorkflowSuggestion:
    """Workflow suggestion from templates and dynamic assembly."""

    def test_template_match(self):
        engine = IntentEngine()
        result = engine.suggest_workflow(
            "competitive research on market trends",
            installed_servers=[],
        )
        assert result.workflow_name
        assert len(result.steps) > 0

    def test_full_stack_development_template(self):
        engine = IntentEngine()
        result = engine.suggest_workflow(
            "full-stack development with testing",
            installed_servers=["github"],
        )
        assert len(result.steps) > 0
        assert result.required_credentials

    def test_dynamic_workflow_fallback(self):
        engine = IntentEngine()
        result = engine.suggest_workflow(
            "search the web and scrape pages",
            installed_servers=[],
        )
        assert result.workflow_name
        assert len(result.steps) > 0

    def test_empty_workflow_on_no_match(self):
        engine = IntentEngine()
        result = engine.suggest_workflow(
            "do something completely unrelated to anything",
            installed_servers=[],
        )
        # Either empty steps or a dynamically built one
        assert result.workflow_name is not None

    def test_estimated_setup_time_ready(self):
        engine = IntentEngine()
        result = engine.suggest_workflow(
            "search the web for info",
            installed_servers=["brave-search"],
        )
        # brave-search is installed, so setup time should be shorter
        assert result.estimated_setup_time is not None


class TestPickServer:
    """Server selection priority logic."""

    def test_prefers_recommended_installed(self):
        engine = IntentEngine()
        cap_def = CAPABILITY_MAP["web_search"]
        # brave-search is recommended
        chosen = engine._pick_server(cap_def, {"brave-search"})
        assert chosen is not None
        assert chosen.name == "brave-search"

    def test_falls_back_to_recommended_when_none_installed(self):
        engine = IntentEngine()
        cap_def = CAPABILITY_MAP["web_search"]
        chosen = engine._pick_server(cap_def, set())
        assert chosen is not None
        assert chosen.recommended is True

    def test_prefers_installed_non_recommended(self):
        engine = IntentEngine()
        cap_def = CAPABILITY_MAP["web_search"]
        # perplexity is installed but not recommended
        chosen = engine._pick_server(cap_def, {"perplexity"})
        assert chosen is not None
        assert chosen.name == "perplexity"
