"""Tests for Registry Federation (R5)."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.meta_mcp.registry import (
    RegistryFederation,
    compute_trust_score,
    _stars_score,
    _trust_level_for,
    _extract_keywords,
    _OfficialRegistryAdapter,
    _SmitheryAdapter,
    _McpSoAdapter,
)
from src.meta_mcp.models import TrustLevel


class TestTrustScoreComputation:
    """Trust score calculation from signals."""

    def test_official_source_gets_high_base(self):
        ts = compute_trust_score("srv", sources=["official_registry"])
        assert ts.score >= 30

    def test_multi_source_bonus(self):
        single = compute_trust_score("srv", sources=["official_registry"])
        multi = compute_trust_score("srv", sources=["official_registry", "smithery"])
        assert multi.score > single.score

    def test_stars_boost(self):
        no_stars = compute_trust_score("srv", sources=["unknown"])
        with_stars = compute_trust_score("srv", sources=["unknown"], stars=5000)
        assert with_stars.score > no_stars.score

    def test_recent_update_bonus(self):
        old = compute_trust_score("srv", sources=["unknown"])
        recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        recent = compute_trust_score("srv", sources=["unknown"], updated_at=recent_date)
        assert recent.score > old.score

    def test_security_scan_bonus(self):
        no_scan = compute_trust_score("srv", sources=["unknown"])
        with_scan = compute_trust_score("srv", sources=["unknown"], has_security_scan=True)
        assert with_scan.score > no_scan.score

    def test_documentation_bonus(self):
        no_doc = compute_trust_score("srv", sources=["unknown"])
        with_doc = compute_trust_score("srv", sources=["unknown"], has_documentation=True)
        assert with_doc.score > no_doc.score

    def test_max_score_capped(self):
        ts = compute_trust_score(
            "srv",
            sources=["official_registry", "smithery", "mcp_so"],
            stars=50000,
            updated_at=datetime.now(timezone.utc).isoformat(),
            has_security_scan=True,
            has_documentation=True,
        )
        assert ts.score <= 100

    def test_explanation_present(self):
        ts = compute_trust_score("srv", sources=["smithery"], stars=100)
        assert "Score" in ts.explanation
        assert ts.level in (TrustLevel.OFFICIAL, TrustLevel.VERIFIED,
                            TrustLevel.COMMUNITY, TrustLevel.UNKNOWN)


class TestStarsScore:
    """Star-based scoring buckets."""

    def test_zero_stars(self):
        assert _stars_score(0) == 0

    def test_negative_stars(self):
        assert _stars_score(-5) == 0

    def test_high_stars(self):
        assert _stars_score(15000) == 20

    def test_medium_stars(self):
        assert _stars_score(500) == 10


class TestTrustLevels:
    """Trust level thresholds."""

    def test_high_score_official(self):
        assert _trust_level_for(85) == TrustLevel.OFFICIAL

    def test_medium_score_verified(self):
        assert _trust_level_for(65) == TrustLevel.VERIFIED

    def test_low_score_community(self):
        assert _trust_level_for(45) == TrustLevel.COMMUNITY

    def test_very_low_unknown(self):
        assert _trust_level_for(10) == TrustLevel.UNKNOWN


class TestNameNormalisation:
    """Server name deduplication normalisation."""

    def test_strip_mcp_prefix(self):
        assert RegistryFederation._normalise_name("mcp-server-postgres") == "postgres"

    def test_strip_official_prefix(self):
        assert RegistryFederation._normalise_name(
            "@modelcontextprotocol/server-github"
        ) == "github"

    def test_strip_mcp_suffix(self):
        assert RegistryFederation._normalise_name("brave-search-mcp") == "brave-search"

    def test_collapse_separators(self):
        # Underscores become hyphens; "mcp" is stripped as a path segment
        result = RegistryFederation._normalise_name("my_mcp_server")
        assert "_" not in result  # underscores replaced
        assert "-" in result or result.isalpha()  # hyphens used as separators

    def test_empty_string(self):
        assert RegistryFederation._normalise_name("") == ""


class TestExtractKeywords:
    """Keyword extraction for search indexing."""

    def test_extracts_from_name(self):
        kws = _extract_keywords("brave-search", "Web search API")
        assert "brave" in kws
        assert "search" in kws

    def test_extracts_from_description(self):
        kws = _extract_keywords("x", "A database tool for MCP")
        assert "database" in kws
        assert "tool" in kws
        assert "mcp" in kws


class TestMergeEntries:
    """Multi-source entry merging."""

    def test_prefers_official_source(self):
        entries = [
            {"source": "mcp_so", "description": "community desc", "stars": None},
            {"source": "official_registry", "description": "official desc", "stars": 100},
        ]
        merged = RegistryFederation._merge_entries(entries)
        assert merged["description"] == "official desc"
        assert merged["stars"] == 100


class TestFederatedSearch:
    """Integration test for federated search with mocked HTTP."""

    @pytest.fixture
    def mock_client(self):
        client = AsyncMock()
        client.aclose = AsyncMock()
        return client

    async def test_search_empty_results(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"servers": []}
        mock_client.get = AsyncMock(return_value=mock_response)

        fed = RegistryFederation(client=mock_client)
        results = await fed.search_federated("nonexistent-thing")
        assert isinstance(results, list)
        await fed.close()

    async def test_search_with_results(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "servers": [
                {
                    "name": "test-server",
                    "description": "A test MCP server",
                    "stars": 500,
                    "repository_url": "https://github.com/test/server",
                }
            ]
        }
        mock_client.get = AsyncMock(return_value=mock_response)

        fed = RegistryFederation(client=mock_client)
        results = await fed.search_federated("test")
        # All 3 adapters return same name -> deduplicated to 1
        assert len(results) >= 1
        assert results[0].server == "test"  # normalised
        await fed.close()

    async def test_adapter_failure_tolerance(self, mock_client):
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        fed = RegistryFederation(client=mock_client)
        results = await fed.search_federated("anything")
        assert results == []
        await fed.close()
