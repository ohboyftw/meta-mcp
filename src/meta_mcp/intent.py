"""
Intent-Based Capability Resolution (R1).

This module provides intelligent mapping from natural-language task descriptions
to the MCP servers required to fulfil them.  It maintains a capability taxonomy,
detects gaps between what a user wants to accomplish and what is currently
installed, and suggests complete multi-server workflows for common goals.

Key public interface
--------------------
    IntentEngine.detect_capability_gaps(task_description, installed_servers)
    IntentEngine.suggest_workflow(goal, installed_servers)
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .models import (
    CapabilityGapResult,
    MCPServerCategory,
    MissingCapability,
    WorkflowStep,
    WorkflowSuggestion,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helper types used only within the taxonomy
# ---------------------------------------------------------------------------

@dataclass
class ServerEntry:
    """Metadata for a single MCP server within a capability."""

    name: str
    description: str
    category: MCPServerCategory
    required_credentials: List[str] = field(default_factory=list)
    recommended: bool = False


@dataclass
class CapabilityDefinition:
    """A named capability together with the servers that provide it."""

    display_name: str
    description: str
    servers: List[ServerEntry] = field(default_factory=list)


@dataclass
class IntentPattern:
    """Maps a set of keywords / regex patterns to a capability name."""

    capability: str
    keywords: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)


@dataclass
class WorkflowTemplate:
    """Pre-built workflow template for a common goal."""

    name: str
    description: str
    steps: List[Tuple[str, str, bool]]  # (server, role, required)
    required_credentials: List[str] = field(default_factory=list)
    estimated_setup_time: str = "5-10 minutes"


# ---------------------------------------------------------------------------
# Taxonomy data
# ---------------------------------------------------------------------------

CAPABILITY_MAP: Dict[str, CapabilityDefinition] = {
    "web_search": CapabilityDefinition(
        display_name="Web Search",
        description="Search the web for information, articles, and real-time data",
        servers=[
            ServerEntry(
                name="brave-search",
                description="Privacy-focused web search via the Brave Search API",
                category=MCPServerCategory.SEARCH,
                required_credentials=["BRAVE_API_KEY"],
                recommended=True,
            ),
            ServerEntry(
                name="perplexity",
                description="AI-powered search with summarised answers",
                category=MCPServerCategory.SEARCH,
                required_credentials=["PERPLEXITY_API_KEY"],
            ),
        ],
    ),
    "web_scraping": CapabilityDefinition(
        display_name="Web Scraping",
        description="Extract structured data from web pages",
        servers=[
            ServerEntry(
                name="firecrawl",
                description="Cloud-based web scraping and crawling service",
                category=MCPServerCategory.AUTOMATION,
                required_credentials=["FIRECRAWL_API_KEY"],
                recommended=True,
            ),
            ServerEntry(
                name="puppeteer",
                description="Headless Chrome scraping via Puppeteer",
                category=MCPServerCategory.AUTOMATION,
            ),
            ServerEntry(
                name="playwright",
                description="Cross-browser scraping with Playwright",
                category=MCPServerCategory.AUTOMATION,
            ),
        ],
    ),
    "browser_automation": CapabilityDefinition(
        display_name="Browser Automation",
        description="Automate browser interactions such as clicking, form filling, and navigation",
        servers=[
            ServerEntry(
                name="puppeteer",
                description="Headless Chrome automation via Puppeteer",
                category=MCPServerCategory.AUTOMATION,
                recommended=True,
            ),
            ServerEntry(
                name="playwright",
                description="Cross-browser automation with Playwright",
                category=MCPServerCategory.AUTOMATION,
            ),
        ],
    ),
    "version_control": CapabilityDefinition(
        display_name="Version Control",
        description="Interact with Git hosting platforms for PRs, issues, and repositories",
        servers=[
            ServerEntry(
                name="github",
                description="Full GitHub API access: repos, PRs, issues, actions",
                category=MCPServerCategory.VERSION_CONTROL,
                required_credentials=["GITHUB_TOKEN"],
                recommended=True,
            ),
            ServerEntry(
                name="gitlab",
                description="GitLab API access: merge requests, pipelines, issues",
                category=MCPServerCategory.VERSION_CONTROL,
                required_credentials=["GITLAB_TOKEN"],
            ),
        ],
    ),
    "database": CapabilityDefinition(
        display_name="Database",
        description="Query and manage relational databases",
        servers=[
            ServerEntry(
                name="server-postgres",
                description="PostgreSQL database access and query execution",
                category=MCPServerCategory.DATABASE,
                required_credentials=["POSTGRES_CONNECTION_STRING"],
                recommended=True,
            ),
            ServerEntry(
                name="sqlite",
                description="Local SQLite database access",
                category=MCPServerCategory.DATABASE,
            ),
        ],
    ),
    "code_analysis": CapabilityDefinition(
        display_name="Code Analysis",
        description="Navigate, analyse, and refactor source code",
        servers=[
            ServerEntry(
                name="serena",
                description="AI-powered code navigation and refactoring",
                category=MCPServerCategory.CODING,
                recommended=True,
            ),
        ],
    ),
    "documentation": CapabilityDefinition(
        display_name="Documentation",
        description="Look up framework docs, API references, and technical documentation",
        servers=[
            ServerEntry(
                name="context7",
                description="Instant access to framework and library documentation",
                category=MCPServerCategory.CONTEXT,
                required_credentials=["CONTEXT7_API_KEY"],
                recommended=True,
            ),
        ],
    ),
    "communication": CapabilityDefinition(
        display_name="Communication",
        description="Send messages and notifications via team-communication platforms",
        servers=[
            ServerEntry(
                name="slack-mcp",
                description="Slack messaging and channel integration",
                category=MCPServerCategory.COMMUNICATION,
                required_credentials=["SLACK_BOT_TOKEN"],
                recommended=True,
            ),
            ServerEntry(
                name="discord-mcp",
                description="Discord messaging and server integration",
                category=MCPServerCategory.COMMUNICATION,
                required_credentials=["DISCORD_BOT_TOKEN"],
            ),
        ],
    ),
    "file_system": CapabilityDefinition(
        display_name="File System",
        description="Read, write, and manage files and directories on the local machine",
        servers=[
            ServerEntry(
                name="filesystem",
                description="Local file-system access with sandboxing support",
                category=MCPServerCategory.OTHER,
                recommended=True,
            ),
        ],
    ),
    "spreadsheet": CapabilityDefinition(
        display_name="Spreadsheet",
        description="Work with spreadsheets, CSVs, and tabular data",
        servers=[
            ServerEntry(
                name="google-sheets-mcp",
                description="Google Sheets read/write integration",
                category=MCPServerCategory.OTHER,
                required_credentials=["GOOGLE_SHEETS_CREDENTIALS"],
                recommended=True,
            ),
            ServerEntry(
                name="excel-mcp",
                description="Microsoft Excel file manipulation",
                category=MCPServerCategory.OTHER,
            ),
        ],
    ),
    "ai_orchestration": CapabilityDefinition(
        display_name="AI Orchestration",
        description="Route tasks to multiple AI models and coordinate complex multi-model workflows",
        servers=[
            ServerEntry(
                name="zen-mcp",
                description="Multi-model orchestration and intelligent routing",
                category=MCPServerCategory.ORCHESTRATION,
                recommended=True,
            ),
        ],
    ),
    "memory": CapabilityDefinition(
        display_name="Memory / Persistence",
        description="Persist knowledge across sessions and recall previous context",
        servers=[
            ServerEntry(
                name="basic-memory",
                description="AI-human collaboration memory framework",
                category=MCPServerCategory.OTHER,
                recommended=True,
            ),
        ],
    ),
    "testing": CapabilityDefinition(
        display_name="Testing & QA",
        description="Automated testing, test generation, and quality assurance",
        servers=[
            ServerEntry(
                name="testsprite",
                description="AI-powered automated test generation and execution",
                category=MCPServerCategory.AUTOMATION,
                required_credentials=["TESTSPRITE_API_KEY"],
                recommended=True,
            ),
            ServerEntry(
                name="playwright",
                description="End-to-end browser testing with Playwright",
                category=MCPServerCategory.AUTOMATION,
            ),
        ],
    ),
    "monitoring": CapabilityDefinition(
        display_name="Monitoring",
        description="Monitor system processes, terminals, and desktop activity",
        servers=[
            ServerEntry(
                name="desktop-commander",
                description="System-process and terminal monitoring",
                category=MCPServerCategory.MONITORING,
                recommended=True,
            ),
        ],
    ),
}


# ---------------------------------------------------------------------------
# Intent patterns: keyword / regex -> capability name
# ---------------------------------------------------------------------------

INTENT_PATTERNS: List[IntentPattern] = [
    IntentPattern(
        capability="web_search",
        keywords=["search", "research", "find", "look up", "lookup", "google", "query the web"],
        patterns=[r"\bsearch\s+(?:for|the\s+web)\b", r"\blook\s*up\b", r"\bfind\s+(?:info|information|out)\b"],
    ),
    IntentPattern(
        capability="web_scraping",
        keywords=["scrape", "extract", "crawl", "parse website", "harvest", "pull data from"],
        patterns=[r"\bscrape\b", r"\bcrawl\b", r"\bextract\s+(?:data|content|info)\b"],
    ),
    IntentPattern(
        capability="browser_automation",
        keywords=["browser", "automate", "click", "fill form", "navigate to", "open page", "selenium"],
        patterns=[r"\bbrowser\b", r"\bfill\s+(?:in|out)?\s*(?:a\s+)?form\b", r"\bclick\s+(?:on|the)\b"],
    ),
    IntentPattern(
        capability="version_control",
        keywords=["github", "git", "PR", "pull request", "commit", "repo", "repository", "issue",
                   "merge", "branch", "gitlab"],
        patterns=[r"\bpull\s+request\b", r"\bPR\b", r"\bgit\s+(?:push|pull|commit|clone)\b"],
    ),
    IntentPattern(
        capability="database",
        keywords=["database", "SQL", "query", "postgres", "postgresql", "sqlite", "db",
                   "table", "schema", "migration"],
        patterns=[r"\bSQL\b", r"\bdatabase\b", r"\bquery\s+(?:the\s+)?(?:db|database)\b"],
    ),
    IntentPattern(
        capability="code_analysis",
        keywords=["code", "analyze", "analyse", "refactor", "navigate", "understand code",
                   "code review", "codebase", "source code"],
        patterns=[r"\banalyze?\s+(?:the\s+)?code\b", r"\brefactor\b", r"\bcode\s+review\b"],
    ),
    IntentPattern(
        capability="documentation",
        keywords=["docs", "documentation", "API reference", "framework docs", "library docs",
                   "reference", "manual", "guide"],
        patterns=[r"\bdocs?\b", r"\bdocumentation\b", r"\bAPI\s+reference\b"],
    ),
    IntentPattern(
        capability="communication",
        keywords=["slack", "discord", "message", "notify", "alert", "send notification",
                   "post message", "channel"],
        patterns=[r"\bslack\b", r"\bdiscord\b", r"\bnotify\b", r"\bsend\s+(?:a\s+)?message\b"],
    ),
    IntentPattern(
        capability="file_system",
        keywords=["file", "read", "write", "directory", "folder", "path", "move file",
                   "copy file", "delete file", "list files"],
        patterns=[r"\bread\s+(?:a\s+)?file\b", r"\bwrite\s+(?:a\s+)?file\b", r"\blist\s+files\b"],
    ),
    IntentPattern(
        capability="spreadsheet",
        keywords=["spreadsheet", "csv", "excel", "table", "sheet", "google sheets",
                   "tabular", "rows and columns"],
        patterns=[r"\bspreadsheet\b", r"\bcsv\b", r"\bexcel\b", r"\bgoogle\s+sheets\b"],
    ),
    IntentPattern(
        capability="ai_orchestration",
        keywords=["multi-model", "orchestrate", "route", "different AI", "multiple models",
                   "model routing", "AI orchestration"],
        patterns=[r"\bmulti[\s-]?model\b", r"\borchestrat\w*\b", r"\broute\s+(?:to\s+)?(?:different\s+)?(?:AI|model)\b"],
    ),
    IntentPattern(
        capability="memory",
        keywords=["remember", "memory", "persist", "recall", "knowledge", "long-term",
                   "save context", "remember this"],
        patterns=[r"\bremember\b", r"\brecall\b", r"\bpersist\b", r"\blong[\s-]?term\s+memory\b"],
    ),
    IntentPattern(
        capability="testing",
        keywords=["test", "QA", "quality", "automated testing", "unit test", "integration test",
                   "e2e", "end-to-end", "test suite"],
        patterns=[r"\btest(?:ing|s)?\b", r"\bQA\b", r"\bend[\s-]?to[\s-]?end\b", r"\be2e\b"],
    ),
    IntentPattern(
        capability="monitoring",
        keywords=["monitor", "system", "process", "terminal", "watch", "observe",
                   "resource usage", "cpu", "uptime"],
        patterns=[r"\bmonitor\b", r"\bprocess(?:es)?\b", r"\bterminal\b", r"\bresource\s+usage\b"],
    ),
]


# ---------------------------------------------------------------------------
# Workflow templates
# ---------------------------------------------------------------------------

WORKFLOW_TEMPLATES: Dict[str, WorkflowTemplate] = {
    "competitive research": WorkflowTemplate(
        name="Competitive Research",
        description="Search the web for competitive intelligence, scrape detailed pages, "
                    "and organise findings in a spreadsheet",
        steps=[
            ("brave-search", "Search for competitors, market trends, and industry news", True),
            ("firecrawl", "Scrape competitor websites for detailed product and pricing data", True),
            ("google-sheets-mcp", "Organise and compare findings in a structured spreadsheet", False),
        ],
        required_credentials=["BRAVE_API_KEY", "FIRECRAWL_API_KEY", "GOOGLE_SHEETS_CREDENTIALS"],
        estimated_setup_time="10-15 minutes",
    ),
    "ci/cd monitoring": WorkflowTemplate(
        name="CI/CD Monitoring",
        description="Monitor GitHub repositories for build status, search for known issues, "
                    "and alert the team via Slack",
        steps=[
            ("github", "Monitor repository actions, check build status and PRs", True),
            ("brave-search", "Search for known issues or stack traces when builds fail", False),
            ("slack-mcp", "Send notifications and status updates to the team channel", True),
        ],
        required_credentials=["GITHUB_TOKEN", "BRAVE_API_KEY", "SLACK_BOT_TOKEN"],
        estimated_setup_time="10-15 minutes",
    ),
    "full-stack development": WorkflowTemplate(
        name="Full-Stack Development",
        description="End-to-end development workflow with version control, code analysis, "
                    "database access, and documentation lookup",
        steps=[
            ("github", "Manage source code, branches, PRs, and code reviews", True),
            ("serena", "Navigate, analyse, and refactor the codebase", True),
            ("server-postgres", "Query and manage the application database", False),
            ("context7", "Look up framework and library documentation as needed", False),
        ],
        required_credentials=["GITHUB_TOKEN", "POSTGRES_CONNECTION_STRING", "CONTEXT7_API_KEY"],
        estimated_setup_time="15-20 minutes",
    ),
    "content creation": WorkflowTemplate(
        name="Content Creation",
        description="Research a topic on the web, scrape reference material, "
                    "and persist notes for later use",
        steps=[
            ("brave-search", "Research topics, gather sources, and find references", True),
            ("firecrawl", "Scrape full articles and reference pages for in-depth reading", False),
            ("basic-memory", "Store research notes and outlines for persistent recall", False),
        ],
        required_credentials=["BRAVE_API_KEY", "FIRECRAWL_API_KEY"],
        estimated_setup_time="5-10 minutes",
    ),
    "database analytics": WorkflowTemplate(
        name="Database Analytics",
        description="Query a PostgreSQL database and export results to a spreadsheet "
                    "for analysis and sharing",
        steps=[
            ("server-postgres", "Run analytical queries against the database", True),
            ("google-sheets-mcp", "Export query results to a spreadsheet for visualisation", False),
        ],
        required_credentials=["POSTGRES_CONNECTION_STRING", "GOOGLE_SHEETS_CREDENTIALS"],
        estimated_setup_time="5-10 minutes",
    ),
    "browser testing": WorkflowTemplate(
        name="Browser Testing",
        description="Run end-to-end browser tests with Playwright and generate "
                    "AI-powered test reports",
        steps=[
            ("playwright", "Execute end-to-end browser test suites", True),
            ("testsprite", "Generate additional AI-powered tests and quality reports", False),
        ],
        required_credentials=["TESTSPRITE_API_KEY"],
        estimated_setup_time="5-10 minutes",
    ),
    "documentation lookup": WorkflowTemplate(
        name="Documentation Lookup",
        description="Search framework documentation first, then fall back to web search "
                    "for community answers",
        steps=[
            ("context7", "Look up official framework and library documentation", True),
            ("brave-search", "Search the web for community guides and Stack Overflow answers", False),
        ],
        required_credentials=["CONTEXT7_API_KEY", "BRAVE_API_KEY"],
        estimated_setup_time="5 minutes",
    ),
}


# ---------------------------------------------------------------------------
# IntentEngine
# ---------------------------------------------------------------------------

class IntentEngine:
    """Analyses natural-language task descriptions and resolves them to MCP
    server capabilities, gap reports, and workflow suggestions.

    All public methods are synchronous.
    """

    def __init__(self) -> None:
        self.capability_map: Dict[str, CapabilityDefinition] = CAPABILITY_MAP
        self.intent_patterns: List[IntentPattern] = INTENT_PATTERNS
        self.workflow_templates: Dict[str, WorkflowTemplate] = WORKFLOW_TEMPLATES

        logger.info(
            "IntentEngine initialised with %d capabilities, %d intent patterns, "
            "%d workflow templates",
            len(self.capability_map),
            len(self.intent_patterns),
            len(self.workflow_templates),
        )

    # -- public API ---------------------------------------------------------

    def detect_capability_gaps(
        self,
        task_description: str,
        installed_servers: List[str],
    ) -> CapabilityGapResult:
        """Analyse *task_description* and return the capabilities that are
        not covered by *installed_servers*.

        Parameters
        ----------
        task_description:
            Free-form text describing what the user wants to achieve.
        installed_servers:
            Names of MCP servers already installed and available.

        Returns
        -------
        CapabilityGapResult
            Structured gap report including missing capabilities, servers that
            would fill them, and a human-readable workflow suggestion.
        """
        logger.info("Detecting capability gaps for task: %s", task_description)
        logger.debug("Installed servers: %s", installed_servers)

        installed_set = {s.lower().strip() for s in installed_servers}

        # 1. Parse the task into required capabilities
        required_capabilities = self._parse_intent(task_description)
        logger.info(
            "Matched %d capabilities: %s",
            len(required_capabilities),
            ", ".join(required_capabilities) or "(none)",
        )

        # 2. Determine which capabilities are already covered
        covered, missing = self._partition_capabilities(
            required_capabilities, installed_set,
        )
        logger.info(
            "Covered: %s | Missing: %s",
            ", ".join(covered) or "(none)",
            ", ".join(missing) or "(none)",
        )

        # 3. Build MissingCapability models
        missing_models = self._build_missing_models(
            missing, task_description, installed_set,
        )

        # 4. Determine which capabilities are currently available
        currently_available = self._resolve_available_capabilities(installed_set)

        # 5. Compose a suggested-workflow narrative
        suggested_workflow = self._compose_workflow_narrative(
            required_capabilities, covered, missing,
        )

        return CapabilityGapResult(
            task_description=task_description,
            missing_capabilities=missing_models,
            suggested_workflow=suggested_workflow,
            currently_available=currently_available,
        )

    def suggest_workflow(
        self,
        goal: str,
        installed_servers: List[str],
    ) -> WorkflowSuggestion:
        """Given a high-level *goal*, return a complete workflow plan.

        If the goal matches a known template the template is used; otherwise a
        workflow is assembled dynamically from detected capabilities.

        Parameters
        ----------
        goal:
            Free-form text describing the user's objective.
        installed_servers:
            Names of MCP servers already installed and available.

        Returns
        -------
        WorkflowSuggestion
            Named workflow with ordered steps and credential requirements.
        """
        logger.info("Suggesting workflow for goal: %s", goal)

        installed_set = {s.lower().strip() for s in installed_servers}

        # 1. Attempt to match a pre-built template
        template = self._match_template(goal)
        if template is not None:
            logger.info("Matched workflow template: %s", template.name)
            return self._template_to_suggestion(template, installed_set)

        # 2. Fall back to a dynamically built workflow
        logger.info("No template match; building dynamic workflow")
        return self._build_dynamic_workflow(goal, installed_set)

    # -- intent parsing -----------------------------------------------------

    def _parse_intent(self, text: str) -> List[str]:
        """Return an ordered list of capability names detected in *text*.

        Matching is performed via keyword containment and compiled regex
        patterns.  The result is deduplicated and ordered by first occurrence
        in the text.
        """
        text_lower = text.lower()
        scored: Dict[str, int] = {}

        for pattern_def in self.intent_patterns:
            score = self._score_pattern(text_lower, pattern_def)
            if score > 0:
                scored[pattern_def.capability] = max(
                    scored.get(pattern_def.capability, 0), score,
                )

        # Sort by score descending, then alphabetically for determinism
        ranked = sorted(scored.keys(), key=lambda c: (-scored[c], c))
        return ranked

    def _score_pattern(self, text_lower: str, pattern_def: IntentPattern) -> int:
        """Return a relevance score (0 = no match) for *pattern_def*
        against the lowercased *text_lower*."""
        score = 0

        # Keyword hits
        for kw in pattern_def.keywords:
            if kw.lower() in text_lower:
                score += 1

        # Regex hits (worth more because they are more specific)
        for pat in pattern_def.patterns:
            try:
                if re.search(pat, text_lower, re.IGNORECASE):
                    score += 2
            except re.error:
                logger.warning("Invalid regex pattern skipped: %s", pat)

        return score

    # -- capability gap helpers ---------------------------------------------

    def _partition_capabilities(
        self,
        required: List[str],
        installed_set: Set[str],
    ) -> Tuple[List[str], List[str]]:
        """Split *required* capabilities into covered and missing lists."""
        covered: List[str] = []
        missing: List[str] = []

        for cap_name in required:
            cap_def = self.capability_map.get(cap_name)
            if cap_def is None:
                continue

            has_any = any(
                se.name.lower() in installed_set
                for se in cap_def.servers
            )
            if has_any:
                covered.append(cap_name)
            else:
                missing.append(cap_name)

        return covered, missing

    def _build_missing_models(
        self,
        missing: List[str],
        task_description: str,
        installed_set: Set[str],
    ) -> List[MissingCapability]:
        """Build a list of ``MissingCapability`` models for every gap."""
        models: List[MissingCapability] = []

        for idx, cap_name in enumerate(missing):
            cap_def = self.capability_map.get(cap_name)
            if cap_def is None:
                continue

            # Determine priority: first gap is high, rest degrade
            if idx == 0:
                priority = "high"
            elif idx <= 2:
                priority = "medium"
            else:
                priority = "low"

            server_names = [se.name for se in cap_def.servers]
            reason = (
                f"The task \"{task_description}\" requires {cap_def.display_name.lower()} "
                f"capabilities ({cap_def.description.lower()}), but none of the servers "
                f"that provide it ({', '.join(server_names)}) are currently installed."
            )

            models.append(
                MissingCapability(
                    capability=cap_name,
                    reason=reason,
                    servers=server_names,
                    priority=priority,
                )
            )

        return models

    def _resolve_available_capabilities(
        self, installed_set: Set[str],
    ) -> List[str]:
        """Return capability names that are fully or partially available."""
        available: List[str] = []
        for cap_name, cap_def in self.capability_map.items():
            if any(se.name.lower() in installed_set for se in cap_def.servers):
                available.append(cap_name)
        return sorted(available)

    def _compose_workflow_narrative(
        self,
        required: List[str],
        covered: List[str],
        missing: List[str],
    ) -> str:
        """Compose a human-readable workflow suggestion string."""
        if not required:
            return (
                "No specific capability requirements were detected in the task "
                "description. Try rephrasing with more detail about what you "
                "want to accomplish."
            )

        parts: List[str] = []

        if covered:
            covered_names = [
                self.capability_map[c].display_name
                for c in covered if c in self.capability_map
            ]
            parts.append(
                f"You already have the following capabilities covered: "
                f"{', '.join(covered_names)}."
            )

        if missing:
            for cap_name in missing:
                cap_def = self.capability_map.get(cap_name)
                if cap_def is None:
                    continue
                recommended = [
                    se.name for se in cap_def.servers if se.recommended
                ]
                if recommended:
                    parts.append(
                        f"For {cap_def.display_name.lower()}, install "
                        f"{recommended[0]} (recommended)."
                    )
                else:
                    all_names = [se.name for se in cap_def.servers]
                    parts.append(
                        f"For {cap_def.display_name.lower()}, install one of: "
                        f"{', '.join(all_names)}."
                    )

        if not missing:
            parts.append(
                "All required capabilities are already installed. You are "
                "ready to proceed."
            )

        return " ".join(parts)

    # -- workflow suggestion helpers -----------------------------------------

    def _match_template(self, goal: str) -> Optional[WorkflowTemplate]:
        """Find the best-matching workflow template for *goal*.

        Matching is performed by checking whether the template key (or a
        significant subset of its words) appears in the goal text.
        """
        goal_lower = goal.lower()

        best_template: Optional[WorkflowTemplate] = None
        best_score = 0

        for key, template in self.workflow_templates.items():
            score = 0

            # Exact key match
            if key in goal_lower:
                score += 10

            # Word overlap between the goal and the template key + description
            key_words = set(key.split())
            desc_words = set(template.description.lower().split())
            goal_words = set(goal_lower.split())

            key_overlap = len(key_words & goal_words)
            desc_overlap = len(desc_words & goal_words)

            score += key_overlap * 3
            score += desc_overlap

            if score > best_score:
                best_score = score
                best_template = template

        # Require a minimum relevance threshold
        if best_score >= 3:
            return best_template
        return None

    def _template_to_suggestion(
        self,
        template: WorkflowTemplate,
        installed_set: Set[str],
    ) -> WorkflowSuggestion:
        """Convert a ``WorkflowTemplate`` into a ``WorkflowSuggestion``."""
        steps: List[WorkflowStep] = []
        all_credentials: List[str] = list(template.required_credentials)

        for idx, (server, role, required) in enumerate(template.steps, start=1):
            steps.append(
                WorkflowStep(
                    order=idx,
                    server=server,
                    role=role,
                    required=required,
                )
            )

        # Annotate the description with installation status
        missing_servers = [
            s.server for s in steps
            if s.server.lower() not in installed_set and s.required
        ]
        description = template.description
        if missing_servers:
            description += (
                f" (Note: the following required servers are not yet installed: "
                f"{', '.join(missing_servers)})"
            )

        return WorkflowSuggestion(
            workflow_name=template.name,
            description=description,
            steps=steps,
            required_credentials=all_credentials,
            estimated_setup_time=template.estimated_setup_time,
        )

    def _build_dynamic_workflow(
        self,
        goal: str,
        installed_set: Set[str],
    ) -> WorkflowSuggestion:
        """Assemble a workflow dynamically from detected capabilities."""
        capabilities = self._parse_intent(goal)

        steps: List[WorkflowStep] = []
        credentials: List[str] = []
        order = 1

        for cap_name in capabilities:
            cap_def = self.capability_map.get(cap_name)
            if cap_def is None:
                continue

            # Pick the best server: prefer recommended, then installed, then first
            chosen = self._pick_server(cap_def, installed_set)
            if chosen is None:
                continue

            steps.append(
                WorkflowStep(
                    order=order,
                    server=chosen.name,
                    role=f"{cap_def.display_name}: {cap_def.description}",
                    required=(order == 1),  # first step always required
                )
            )
            credentials.extend(chosen.required_credentials)
            order += 1

        # Deduplicate credentials while preserving order
        seen_creds: Set[str] = set()
        unique_creds: List[str] = []
        for cred in credentials:
            if cred not in seen_creds:
                unique_creds.append(cred)
                seen_creds.add(cred)

        # Compose workflow name and description
        if steps:
            workflow_name = f"Custom: {goal[:60]}"
            description = (
                f"Dynamically assembled workflow for \"{goal}\" comprising "
                f"{len(steps)} step(s): "
                + " -> ".join(s.server for s in steps)
                + "."
            )
        else:
            workflow_name = "Empty Workflow"
            description = (
                "No matching capabilities were detected for the stated goal. "
                "Try rephrasing with more detail."
            )

        return WorkflowSuggestion(
            workflow_name=workflow_name,
            description=description,
            steps=steps,
            required_credentials=unique_creds,
            estimated_setup_time=self._estimate_setup_time(steps, installed_set),
        )

    def _pick_server(
        self,
        cap_def: CapabilityDefinition,
        installed_set: Set[str],
    ) -> Optional[ServerEntry]:
        """Choose the best server for a capability.

        Preference order:
        1. A recommended server that is already installed.
        2. Any server that is already installed.
        3. The recommended server (not yet installed).
        4. The first server in the list.
        """
        recommended: Optional[ServerEntry] = None
        installed_any: Optional[ServerEntry] = None

        for se in cap_def.servers:
            is_installed = se.name.lower() in installed_set
            if se.recommended:
                if is_installed:
                    return se  # best possible: recommended + installed
                recommended = se
            if is_installed and installed_any is None:
                installed_any = se

        if installed_any is not None:
            return installed_any
        if recommended is not None:
            return recommended
        return cap_def.servers[0] if cap_def.servers else None

    @staticmethod
    def _estimate_setup_time(
        steps: List[WorkflowStep],
        installed_set: Set[str],
    ) -> str:
        """Estimate setup time based on how many servers still need installing."""
        not_installed = sum(
            1 for s in steps if s.server.lower() not in installed_set
        )
        if not_installed == 0:
            return "ready now"
        if not_installed <= 2:
            return "5-10 minutes"
        return "15-20 minutes"
