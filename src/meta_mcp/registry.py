"""
Registry Federation for Meta MCP Server (R5).

Searches across multiple MCP registries in parallel, deduplicates results,
and computes trust scores for each discovered server.  Supports the Official
MCP Registry, Smithery, and mcp.so as federated sources.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .models import (
    FederatedSearchResult,
    MCPServerCategory,
    MCPServerOption,
    MCPServerWithOptions,
    RegistrySource,
    TrustLevel,
    TrustScore,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REQUEST_TIMEOUT = 10.0  # seconds

_SOURCE_MULTIPLIERS: Dict[str, int] = {
    "official_registry": 30,
    "smithery": 25,
    "awesome_list": 20,
    "github": 15,
    "mcp_so": 15,
    "unknown": 5,
}

_MULTI_SOURCE_BONUS = 10  # per additional source beyond the first

_STARS_THRESHOLDS: List[Tuple[int, int]] = [
    # (min_stars, points)
    (10_000, 20),
    (1_000, 15),
    (100, 10),
    (1, 5),
    (0, 0),
]

_RECENT_UPDATE_BONUS = 10
_SECURITY_SCAN_BONUS = 5
_DOCUMENTATION_BONUS = 5
_MAX_TRUST_SCORE = 100

_TRUST_LEVEL_THRESHOLDS: List[Tuple[int, TrustLevel]] = [
    (80, TrustLevel.OFFICIAL),
    (60, TrustLevel.VERIFIED),
    (40, TrustLevel.COMMUNITY),
    (0, TrustLevel.UNKNOWN),
]


# ---------------------------------------------------------------------------
# Registry adapter base
# ---------------------------------------------------------------------------

class _RegistryAdapter:
    """Base class for a single registry adapter."""

    name: str = "unknown"
    url: str = ""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: str) -> List[Dict[str, Any]]:
        """Return a list of normalised server dicts from this registry."""
        raise NotImplementedError

    async def ping(self) -> bool:
        """Return *True* if the registry is reachable."""
        raise NotImplementedError

    # shared helper used by every concrete adapter
    @staticmethod
    def _normalise_entry(raw: Dict[str, Any], source: str) -> Dict[str, Any]:
        return {
            "name": raw.get("name", ""),
            "description": raw.get("description", ""),
            "stars": raw.get("stars") or raw.get("github_stars"),
            "updated_at": raw.get("updated_at"),
            "repository_url": raw.get("repository_url") or raw.get("repo") or raw.get("url"),
            "documentation_url": raw.get("documentation_url"),
            "has_security_scan": raw.get("has_security_scan", False),
            "category": raw.get("category"),
            "author": raw.get("author"),
            "install_command": raw.get("install_command"),
            "env_vars": raw.get("env_vars", []),
            "source": source,
        }


# ---------------------------------------------------------------------------
# Official MCP Registry adapter
# ---------------------------------------------------------------------------

class _OfficialRegistryAdapter(_RegistryAdapter):
    """Adapter for registry.modelcontextprotocol.io."""

    name = "official_registry"
    url = "https://registry.modelcontextprotocol.io"

    async def search(self, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            resp = await self._client.get(
                f"{self.url}/servers",
                params={"q": query},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            servers = data if isinstance(data, list) else data.get("servers", [])
            for entry in servers:
                results.append(self._normalise_entry(entry, self.name))
        except httpx.TimeoutException:
            logger.warning("Official MCP Registry timed out for query %r", query)
        except httpx.HTTPStatusError as exc:
            logger.warning("Official registry HTTP %s for %r", exc.response.status_code, query)
        except Exception:
            logger.exception("Unexpected error querying Official MCP Registry")
        return results

    async def ping(self) -> bool:
        try:
            r = await self._client.get(f"{self.url}/servers", params={"q": "ping"}, timeout=_REQUEST_TIMEOUT)
            return r.status_code < 500
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Smithery adapter
# ---------------------------------------------------------------------------

class _SmitheryAdapter(_RegistryAdapter):
    """Adapter for smithery.ai -- includes quality ratings & security scans."""

    name = "smithery"
    url = "https://smithery.ai"

    async def search(self, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            resp = await self._client.get(
                f"{self.url}/api/v1/servers",
                params={"q": query},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            servers = data if isinstance(data, list) else data.get("servers", [])
            for entry in servers:
                norm = self._normalise_entry(entry, self.name)
                # Smithery-specific: infer security scan from quality fields
                norm["has_security_scan"] = bool(
                    entry.get("security_scan")
                    or entry.get("has_security_scan")
                    or entry.get("quality_rating")
                )
                results.append(norm)
        except httpx.TimeoutException:
            logger.warning("Smithery timed out for query %r", query)
        except httpx.HTTPStatusError as exc:
            logger.warning("Smithery HTTP %s for %r", exc.response.status_code, query)
        except Exception:
            logger.exception("Unexpected error querying Smithery")
        return results

    async def ping(self) -> bool:
        try:
            r = await self._client.get(f"{self.url}/api/v1/servers", params={"q": "ping"}, timeout=_REQUEST_TIMEOUT)
            return r.status_code < 500
        except Exception:
            return False


# ---------------------------------------------------------------------------
# mcp.so adapter
# ---------------------------------------------------------------------------

class _McpSoAdapter(_RegistryAdapter):
    """Adapter for mcp.so -- community registry with 17K+ servers."""

    name = "mcp_so"
    url = "https://mcp.so"

    async def search(self, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            resp = await self._client.get(
                f"{self.url}/api/search",
                params={"q": query},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            servers = data if isinstance(data, list) else data.get("results", data.get("servers", []))
            for entry in servers:
                norm = self._normalise_entry(entry, self.name)
                norm["has_security_scan"] = False  # mcp.so has no scan data
                results.append(norm)
        except httpx.TimeoutException:
            logger.warning("mcp.so timed out for query %r", query)
        except httpx.HTTPStatusError as exc:
            logger.warning("mcp.so HTTP %s for %r", exc.response.status_code, query)
        except Exception:
            logger.exception("Unexpected error querying mcp.so")
        return results

    async def ping(self) -> bool:
        try:
            r = await self._client.get(self.url, timeout=_REQUEST_TIMEOUT)
            return r.status_code < 500
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Trust-score computation
# ---------------------------------------------------------------------------

def _stars_score(stars: Optional[int]) -> int:
    """Logarithmic star score, max 20 points."""
    if not stars or stars <= 0:
        return 0
    for threshold, points in _STARS_THRESHOLDS:
        if stars >= threshold:
            return points
    return 0


def _trust_level_for(score: int) -> TrustLevel:
    for threshold, level in _TRUST_LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return TrustLevel.UNKNOWN


def compute_trust_score(
    server_name: str,
    sources: List[str],
    stars: Optional[int] = None,
    updated_at: Optional[str] = None,
    has_security_scan: bool = False,
    has_documentation: bool = False,
) -> TrustScore:
    """Compute a 0-100 trust score for an MCP server.

    Signals
    -------
    - Best-source multiplier (max of all sources)   up to 30
    - Multi-source bonus (+10 per extra source)      variable
    - GitHub stars (log-scale buckets)               up to 20
    - Recent update (within 30 days)                 up to 10
    - Has security scan                              up to  5
    - Has documentation                              up to  5
    Total is capped at 100.
    """
    signals: Dict[str, Any] = {}

    # Source base score -- take the highest multiplier among all sources
    source_scores = [_SOURCE_MULTIPLIERS.get(s, _SOURCE_MULTIPLIERS["unknown"]) for s in sources]
    base = max(source_scores) if source_scores else _SOURCE_MULTIPLIERS["unknown"]
    signals["source_base"] = base

    # Multi-source bonus
    extra_sources = max(0, len(set(sources)) - 1)
    multi_bonus = extra_sources * _MULTI_SOURCE_BONUS
    signals["multi_source_bonus"] = multi_bonus

    # Stars
    star_pts = _stars_score(stars)
    signals["stars"] = {"count": stars or 0, "points": star_pts}

    # Recency
    recency_pts = 0
    if updated_at:
        try:
            updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - updated_dt) <= timedelta(days=30):
                recency_pts = _RECENT_UPDATE_BONUS
        except (ValueError, TypeError):
            logger.debug("Could not parse updated_at %r for %s", updated_at, server_name)
    signals["recent_update"] = recency_pts

    # Security scan
    sec_pts = _SECURITY_SCAN_BONUS if has_security_scan else 0
    signals["security_scan"] = sec_pts

    # Documentation
    doc_pts = _DOCUMENTATION_BONUS if has_documentation else 0
    signals["documentation"] = doc_pts

    # Final score
    raw = base + multi_bonus + star_pts + recency_pts + sec_pts + doc_pts
    score = min(raw, _MAX_TRUST_SCORE)
    level = _trust_level_for(score)

    # Human-readable explanation
    parts: List[str] = [f"base={base} (best source: {sources[0] if sources else 'unknown'})"]
    if multi_bonus:
        parts.append(f"multi-source +{multi_bonus}")
    if star_pts:
        parts.append(f"stars +{star_pts} ({stars})")
    if recency_pts:
        parts.append(f"recent update +{recency_pts}")
    if sec_pts:
        parts.append(f"security scan +{sec_pts}")
    if doc_pts:
        parts.append(f"documentation +{doc_pts}")
    explanation = f"Score {score}/{_MAX_TRUST_SCORE} [{level.value}]: " + ", ".join(parts)

    return TrustScore(score=score, level=level, signals=signals, explanation=explanation)


# ---------------------------------------------------------------------------
# RegistryFederation
# ---------------------------------------------------------------------------

class RegistryFederation:
    """Federated search across multiple MCP server registries.

    Usage::

        async with RegistryFederation() as fed:
            results = await fed.search_federated("database")
            for r in results:
                print(r.server, r.trust_score.score)
    """

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": "meta-mcp/0.1.0"},
        )
        self._adapters: List[_RegistryAdapter] = [
            _OfficialRegistryAdapter(self._client),
            _SmitheryAdapter(self._client),
            _McpSoAdapter(self._client),
        ]

    # -- context manager ------------------------------------------------------

    async def __aenter__(self) -> "RegistryFederation":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client if we own it."""
        if self._owns_client:
            await self._client.aclose()

    # -- public API -----------------------------------------------------------

    async def search_federated(self, query: str) -> List[FederatedSearchResult]:
        """Search all registries in parallel, deduplicate, score, and rank.

        Returns ``FederatedSearchResult`` items sorted by descending trust score.
        """
        logger.info("Federated search started for query %r", query)
        start = datetime.now()

        # Query every registry concurrently
        tasks = [adapter.search(query) for adapter in self._adapters]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten results, tolerating individual adapter failures
        all_entries: List[Dict[str, Any]] = []
        for adapter, result in zip(self._adapters, raw_results):
            if isinstance(result, BaseException):
                logger.warning("Registry %s failed: %s", adapter.name, result)
                continue
            for entry in result:
                entry.setdefault("source", adapter.name)
                all_entries.append(entry)

        # Deduplicate by normalised server name
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for entry in all_entries:
            key = self._normalise_name(entry.get("name", ""))
            if not key:
                continue
            grouped.setdefault(key, []).append(entry)

        # Score each unique server
        federated: List[FederatedSearchResult] = []
        for canonical_name, entries in grouped.items():
            sources = list({e["source"] for e in entries})
            merged = self._merge_entries(entries)

            trust = compute_trust_score(
                server_name=canonical_name,
                sources=sources,
                stars=merged.get("stars"),
                updated_at=merged.get("updated_at"),
                has_security_scan=merged.get("has_security_scan", False),
                has_documentation=bool(merged.get("documentation_url")),
            )

            confidence = "high" if trust.score >= 70 else ("medium" if trust.score >= 40 else "low")
            federated.append(FederatedSearchResult(
                server=canonical_name,
                sources=sources,
                trust_score=trust,
                confidence=confidence,
            ))

        federated.sort(key=lambda r: r.trust_score.score, reverse=True)

        elapsed = int((datetime.now() - start).total_seconds() * 1000)
        logger.info("Federated search for %r: %d results in %d ms", query, len(federated), elapsed)
        return federated

    async def list_registries(self) -> List[RegistrySource]:
        """Return metadata and reachability status for every configured registry."""
        logger.info("Checking status of %d registries", len(self._adapters))

        async def _check(adapter: _RegistryAdapter) -> RegistrySource:
            available = await adapter.ping()
            return RegistrySource(
                name=adapter.name,
                url=adapter.url,
                server_count=None,
                last_queried=datetime.now(timezone.utc) if available else None,
                available=available,
            )

        tasks = [_check(a) for a in self._adapters]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        results: List[RegistrySource] = []
        for adapter, outcome in zip(self._adapters, outcomes):
            if isinstance(outcome, BaseException):
                logger.warning("Ping failed for %s: %s", adapter.name, outcome)
                results.append(RegistrySource(
                    name=adapter.name, url=adapter.url,
                    server_count=None, last_queried=None, available=False,
                ))
            else:
                results.append(outcome)
        return results

    # -- internal helpers -----------------------------------------------------

    @staticmethod
    def _normalise_name(name: str) -> str:
        """Normalise a server name for deduplication."""
        if not name:
            return ""
        n = name.strip().lower()
        # Collapse separators early so prefix/suffix matching works uniformly
        n = n.replace("_", "-").replace(" ", "-")
        for prefix in ("@modelcontextprotocol/server-", "mcp-server-", "mcp-", "@"):
            if n.startswith(prefix):
                n = n[len(prefix):]
        for suffix in ("-mcp", "-server"):
            if n.endswith(suffix):
                n = n[: -len(suffix)]
        return n.strip("-")

    @staticmethod
    def _merge_entries(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge multiple registry entries, preferring higher-trust sources."""
        priority = {"official_registry": 0, "smithery": 1, "mcp_so": 2, "unknown": 3}
        ranked = sorted(entries, key=lambda e: priority.get(e.get("source", "unknown"), 99))
        all_keys = {k for e in entries for k in e}
        merged: Dict[str, Any] = {}
        for key in all_keys:
            for entry in ranked:
                val = entry.get(key)
                if val is not None and val != "" and val != []:
                    merged[key] = val
                    break
            else:
                merged[key] = None
        return merged

    @staticmethod
    def _categorise(name: str, description: str) -> MCPServerCategory:
        """Best-effort category inference from name and description."""
        text = f"{name} {description}".lower()
        mapping = [
            (MCPServerCategory.VERSION_CONTROL, ["github", "gitlab", "git", "version"]),
            (MCPServerCategory.SEARCH, ["search", "brave", "google", "perplexity"]),
            (MCPServerCategory.AUTOMATION, ["browser", "puppeteer", "playwright", "automation"]),
            (MCPServerCategory.CODING, ["code", "ide", "coding", "lint", "format"]),
            (MCPServerCategory.CONTEXT, ["context", "doc", "knowledge", "memory"]),
            (MCPServerCategory.DATABASE, ["database", "sql", "postgres", "mysql", "mongo", "redis"]),
            (MCPServerCategory.COMMUNICATION, ["slack", "discord", "email", "chat"]),
            (MCPServerCategory.MONITORING, ["monitor", "log", "metric", "alert"]),
            (MCPServerCategory.SECURITY, ["security", "auth", "vault", "secret"]),
            (MCPServerCategory.ORCHESTRATION, ["orchestrat", "router", "workflow", "pipeline"]),
        ]
        for cat, keywords in mapping:
            if any(kw in text for kw in keywords):
                return cat
        return MCPServerCategory.OTHER

    @staticmethod
    def _to_server_model(
        name: str,
        merged: Dict[str, Any],
        entries: List[Dict[str, Any]],
    ) -> MCPServerWithOptions:
        """Convert merged registry data into an ``MCPServerWithOptions``."""
        desc = merged.get("description") or f"MCP server: {name}"
        category = RegistryFederation._categorise(name, desc)

        updated_at = None
        raw_ts = merged.get("updated_at")
        if raw_ts:
            try:
                updated_at = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        options: List[MCPServerOption] = []
        seen: set = set()
        for entry in entries:
            src = entry.get("source", "unknown")
            if src in seen:
                continue
            seen.add(src)
            cmd = entry.get("install_command") or f"npx -y {name}"
            options.append(MCPServerOption(
                name=src,
                display_name=src.replace("_", " ").title(),
                description=f"From {src}",
                install_command=cmd,
                config_name=name,
                env_vars=entry.get("env_vars") or [],
                repository_url=entry.get("repository_url"),
                recommended=(src == "official_registry"),
            ))

        return MCPServerWithOptions(
            name=name,
            display_name=name.replace("-", " ").title(),
            description=desc,
            category=category,
            repository_url=merged.get("repository_url"),
            documentation_url=merged.get("documentation_url"),
            author=merged.get("author"),
            stars=merged.get("stars"),
            updated_at=updated_at,
            keywords=_extract_keywords(name, desc),
            options=options,
        )

    async def search_servers(self, query: str) -> List[MCPServerWithOptions]:
        """Search registries and return full ``MCPServerWithOptions`` models.

        This is a higher-level wrapper over :meth:`search_federated` that
        also materialises the merged registry data into rich server models.
        """
        logger.info("Federated server model search for %r", query)

        tasks = [adapter.search(query) for adapter in self._adapters]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_entries: List[Dict[str, Any]] = []
        for adapter, result in zip(self._adapters, raw_results):
            if isinstance(result, BaseException):
                logger.warning("Registry %s failed: %s", adapter.name, result)
                continue
            for entry in result:
                entry.setdefault("source", adapter.name)
                all_entries.append(entry)

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for entry in all_entries:
            key = self._normalise_name(entry.get("name", ""))
            if key:
                grouped.setdefault(key, []).append(entry)

        servers = [
            self._to_server_model(name, self._merge_entries(entries), entries)
            for name, entries in grouped.items()
        ]
        servers.sort(key=lambda s: (s.stars or 0), reverse=True)
        return servers


# ---------------------------------------------------------------------------
# Module-level keyword extraction
# ---------------------------------------------------------------------------

def _extract_keywords(name: str, description: str) -> List[str]:
    """Extract search keywords from a server name and description."""
    kw: set = set()
    kw.update(re.findall(r"[a-z]+", name.lower()))
    kw.update(re.findall(
        r"\b(?:api|server|client|tool|integration|search|browser|code|"
        r"git|database|ai|model|context|protocol|mcp)\b",
        description.lower(),
    ))
    return sorted(kw)


# ---------------------------------------------------------------------------
# Convenience module-level async functions
# ---------------------------------------------------------------------------

async def search_federated(query: str) -> List[FederatedSearchResult]:
    """Search all known MCP registries and return ranked results."""
    async with RegistryFederation() as federation:
        return await federation.search_federated(query)


async def list_registries() -> List[RegistrySource]:
    """Return the status of all configured registries."""
    async with RegistryFederation() as federation:
        return await federation.list_registries()
