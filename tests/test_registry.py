"""Tests for Registry Federation (R5)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.meta_mcp.registry import (
    RegistryFederation,
    _extract_keywords,
    _OfficialRegistryAdapter,
    _SmitheryAdapter,
    _McpSoAdapter,
)


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
