"""
R10: The Capability Stack Model.

Unifying module that ties together all four capability layers:
  Layer 1 - Tools   : MCP servers providing tool-level primitives.
  Layer 2 - Prompts : MCP prompts exposed by servers for guided workflows.
  Layer 3 - Skills  : Agent skills (SKILL.md files) for high-level behaviours.
  Layer 4 - Context : Project-level context (AGENTS.md, language/framework detection).

Public API (all synchronous):
  CapabilityStack.analyze_full_stack(project_path)        -> CapabilityStackReport
  CapabilityStack.detect_cross_layer_gaps(project_path)   -> List[CapabilityGap]
  CapabilityStack.get_stack_score(project_path)           -> int
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    CapabilityLayer, CapabilityGap, CapabilityStackReport,
    CapabilityBundleItem, CapabilityBundleResult,
)
from .config import MCPConfig

logger = logging.getLogger(__name__)

# -- Lazy imports for modules that may not exist yet -------------------------
_has_skills = _has_project = False
_SkillsManager: Any = None
_ProjectAnalyzer: Any = None

try:
    from .skills import SkillsManager as _SkillsManager  # type: ignore[assignment]
    _has_skills = True
except ImportError:
    logger.debug("skills module unavailable; Skills layer analysis will be limited")
try:
    from .project import ProjectAnalyzer as _ProjectAnalyzer  # type: ignore[assignment]
    _has_project = True
except ImportError:
    logger.debug("project module unavailable; Context layer analysis will be limited")

# -- Constants ---------------------------------------------------------------
# Complementary pairs: (server pattern, skill pattern, human description)
_COMPLEMENTARY_PAIRS: List[Tuple[str, str, str]] = [
    ("github",          "code-review",                  "code-review skill"),
    ("server-postgres", "database-query-optimization",  "database query-optimization skill"),
    ("postgres",        "database-query-optimization",  "database query-optimization skill"),
    ("brave-search",    "competitive-research",         "competitive-research skill"),
    ("brave",           "competitive-research",         "competitive-research skill"),
    ("sqlite",          "database-query-optimization",  "database query-optimization skill"),
    ("filesystem",      "file-management",              "file-management skill"),
    ("puppeteer",       "web-scraping",                 "web-scraping skill"),
    ("slack",           "communication-workflow",        "communication-workflow skill"),
]

# Servers known to expose MCP prompts (static knowledge base).
_SERVERS_WITH_PROMPTS: Dict[str, List[str]] = {
    "github":          ["create-pull-request", "review-code"],
    "server-postgres": ["query-database", "explain-schema"],
    "brave-search":    ["research-topic"],
    "filesystem":      ["analyze-directory"],
    "sqlite":          ["query-database"],
}

_MAX_LAYER_SCORE         = 25
_POINTS_PER_SERVER       = 5
_POINTS_PER_SKILL        = 5
_AGENTS_MD_POINTS        = 15
_PROJECT_DETECTION_POINTS = 10

# Language / framework marker files for heuristic project detection.
_LANGUAGE_MARKERS: Dict[str, str] = {
    "package.json": "javascript", "tsconfig.json": "typescript",
    "pyproject.toml": "python", "setup.py": "python",
    "Cargo.toml": "rust", "go.mod": "go",
    "pom.xml": "java", "build.gradle": "java",
    "Gemfile": "ruby", "mix.exs": "elixir", "composer.json": "php",
}
_FRAMEWORK_MARKERS: Dict[str, str] = {
    "next.config.js": "next.js", "next.config.ts": "next.js",
    "next.config.mjs": "next.js", "nuxt.config.ts": "nuxt",
    "angular.json": "angular", "svelte.config.js": "svelte",
    "django": "django", "fastapi": "fastapi", "rails": "rails",
}


def _run_async(coro):  # type: ignore[type-arg]
    """Run an async coroutine synchronously, handling nested event loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class CapabilityStack:
    """Analyse, score, and report on the four-layer capability stack.

    All public methods are synchronous.  Async MCP config calls are bridged
    via ``_run_async``.
    """

    def __init__(self, config_path: Optional[str] = None) -> None:
        self._config = MCPConfig(config_path=config_path)

    # -- Public API ----------------------------------------------------------

    def analyze_full_stack(self, project_path: str) -> CapabilityStackReport:
        """Analyse all 4 layers and produce a comprehensive report."""
        logger.info("Analysing full capability stack for %s", project_path)
        layers = self._gather_layers(project_path)
        gaps = self._identify_all_gaps(*layers, project_path)
        score = self._compute_score(*layers)
        report = CapabilityStackReport(
            tools_layer=layers[0], prompts_layer=layers[1],
            skills_layer=layers[2], context_layer=layers[3],
            gaps=gaps, score=score,
        )
        logger.info("Stack analysis complete: score=%d, gaps=%d", score, len(gaps))
        return report

    def detect_cross_layer_gaps(self, project_path: str) -> List[CapabilityGap]:
        """Find gaps across all layers."""
        logger.info("Detecting cross-layer gaps for %s", project_path)
        return self._identify_all_gaps(*self._gather_layers(project_path), project_path)

    def get_stack_score(self, project_path: str) -> int:
        """Compute an overall capability score (0-100)."""
        logger.info("Computing stack score for %s", project_path)
        return self._compute_score(*self._gather_layers(project_path))

    # -- Internal: gather all layer dicts ------------------------------------

    def _gather_layers(self, project_path: str) -> Tuple[
        Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]
    ]:
        tools = self._analyze_tools_layer()
        return tools, self._analyze_prompts_layer(tools), \
            self._analyze_skills_layer(project_path), \
            self._analyze_context_layer(project_path)

    # -- Layer analysers -----------------------------------------------------

    def _analyze_tools_layer(self) -> Dict[str, Any]:
        """Layer 1: MCP server configuration."""
        servers: Dict[str, Any] = {}
        try:
            servers = _run_async(self._config.list_servers())
            logger.debug("Tools layer: %d configured servers", len(servers))
        except Exception:
            logger.exception("Failed to load MCP server configuration")
        names = list(servers.keys())
        return {
            "server_count": len(names), "servers": names,
            "raw_entries": {
                n: {"command": e.command, "args": e.args} for n, e in servers.items()
            },
        }

    def _analyze_prompts_layer(self, tools_layer: Dict[str, Any]) -> Dict[str, Any]:
        """Layer 2: MCP prompts exposed by configured servers."""
        prompts_by_server: Dict[str, List[str]] = {}
        total = 0
        for name in tools_layer.get("servers", []):
            matched = self._match_known_prompts(name)
            if matched:
                prompts_by_server[name] = matched
                total += len(matched)
        n_with = len(prompts_by_server)
        return {
            "total_prompts": total, "servers_with_prompts": n_with,
            "servers_without_prompts": tools_layer["server_count"] - n_with,
            "prompts_by_server": prompts_by_server,
        }

    def _analyze_skills_layer(self, project_path: str) -> Dict[str, Any]:
        """Layer 3: Installed agent skills (global + project)."""
        g_skills: List[str] = []
        p_skills: List[str] = []
        if _has_skills and _SkillsManager is not None:
            try:
                res = _SkillsManager(project_path=project_path).list_skills()
                g_skills = [s.name for s in getattr(res, "global_skills", [])]
                p_skills = [s.name for s in getattr(res, "project_skills", [])]
            except Exception:
                logger.exception("Failed to query SkillsManager")
        else:
            p_skills = self._scan_skill_files(project_path)
        all_s = g_skills + p_skills
        return {"global_skills": g_skills, "project_skills": p_skills,
                "all_skills": all_s, "total_count": len(all_s)}

    def _analyze_context_layer(self, project_path: str) -> Dict[str, Any]:
        """Layer 4: AGENTS.md and project context."""
        root = Path(project_path)
        agents_md = root / "AGENTS.md"
        has_md = agents_md.is_file()
        proj = self._detect_project_context(root)
        return {
            "has_agents_md": has_md,
            "agents_md_path": str(agents_md) if has_md else None,
            "agents_md_size": agents_md.stat().st_size if has_md else 0,
            "project_detected": proj.get("detected", False),
            "language": proj.get("language"),
            "framework": proj.get("framework"),
            "vcs": proj.get("vcs"),
        }

    # -- Gap identification --------------------------------------------------

    def _identify_all_gaps(
        self, tools: Dict[str, Any], prompts: Dict[str, Any],
        skills: Dict[str, Any], context: Dict[str, Any], project_path: str,
    ) -> List[CapabilityGap]:
        gaps: List[CapabilityGap] = []
        gaps.extend(self._gaps_tools(tools))
        gaps.extend(self._gaps_prompts(prompts, tools))
        gaps.extend(self._gaps_skills(skills))
        gaps.extend(self._gaps_context(context))
        gaps.extend(self._gaps_cross_layer(tools, prompts, skills, context))
        return gaps

    @staticmethod
    def _gaps_tools(t: Dict[str, Any]) -> List[CapabilityGap]:
        if t["server_count"] == 0:
            return [CapabilityGap(
                layer=CapabilityLayer.TOOLS, priority="high",
                gap="No MCP servers are configured",
                fix="Run 'search_mcp_servers' to discover and install MCP servers",
            )]
        return []

    @staticmethod
    def _gaps_prompts(p: Dict[str, Any], t: Dict[str, Any]) -> List[CapabilityGap]:
        if t["server_count"] > 0 and p["servers_with_prompts"] == 0:
            return [CapabilityGap(
                layer=CapabilityLayer.PROMPTS, priority="low",
                gap="None of your configured servers expose known prompts",
                fix="Consider adding servers that expose MCP prompts "
                    "(e.g. github, server-postgres) for guided workflows",
            )]
        return []

    @staticmethod
    def _gaps_skills(s: Dict[str, Any]) -> List[CapabilityGap]:
        if s["total_count"] == 0:
            return [CapabilityGap(
                layer=CapabilityLayer.SKILLS, priority="medium",
                gap="No agent skills are installed",
                fix="Install agent skills to give your AI assistant higher-level "
                    "capabilities (e.g. code-review, database-query-optimization)",
            )]
        return []

    @staticmethod
    def _gaps_context(c: Dict[str, Any]) -> List[CapabilityGap]:
        gaps: List[CapabilityGap] = []
        if not c["has_agents_md"]:
            gaps.append(CapabilityGap(
                layer=CapabilityLayer.CONTEXT, priority="high",
                gap="No AGENTS.md file found in project root",
                fix="Create an AGENTS.md file to guide agent behaviour, "
                    "document conventions, and define project-specific rules",
            ))
        if not c["project_detected"]:
            gaps.append(CapabilityGap(
                layer=CapabilityLayer.CONTEXT, priority="low",
                gap="Could not detect project type or language",
                fix="Ensure the project root contains standard files "
                    "(package.json, pyproject.toml, Cargo.toml, etc.)",
            ))
        return gaps

    @staticmethod
    def _gaps_cross_layer(
        tools: Dict[str, Any], prompts: Dict[str, Any],
        skills: Dict[str, Any], context: Dict[str, Any],
    ) -> List[CapabilityGap]:
        """Detect gaps visible only when comparing layers."""
        gaps: List[CapabilityGap] = []
        server_names = tools.get("servers", [])
        skill_names_lc = [s.lower() for s in skills.get("all_skills", [])]

        # 1. Complementary server <-> skill pairs
        seen_skills: set[str] = set()
        for srv_pat, skill_pat, desc in _COMPLEMENTARY_PAIRS:
            if skill_pat in seen_skills:
                continue
            srv_match = next((n for n in server_names if srv_pat in n.lower()), None)
            skill_match = any(skill_pat in s for s in skill_names_lc)
            if srv_match and not skill_match:
                seen_skills.add(skill_pat)
                gaps.append(CapabilityGap(
                    layer=CapabilityLayer.SKILLS, priority="medium",
                    gap=f"You have the '{srv_match}' MCP server but no {desc}",
                    fix=f"Install the '{skill_pat}' skill to complement "
                        f"your '{srv_match}' server",
                ))

        # 2. Skills present but no AGENTS.md
        if skills["total_count"] > 0 and not context["has_agents_md"]:
            gaps.append(CapabilityGap(
                layer=CapabilityLayer.CONTEXT, priority="high",
                gap="You have skills installed but no AGENTS.md to guide agent behaviour",
                fix="Create an AGENTS.md file that documents how the agent "
                    "should use your installed skills",
            ))

        # 3. Prompts exposed but not surfaced through skills
        if prompts["total_prompts"] > 0 and skills["total_count"] == 0:
            gaps.append(CapabilityGap(
                layer=CapabilityLayer.PROMPTS, priority="medium",
                gap="Your MCP servers expose prompts but they are not being "
                    "surfaced through skills",
                fix="Install skills that leverage the prompts exposed by "
                    "your MCP servers for guided workflows",
            ))

        # 4. Multiple servers but no workflow skills
        if tools["server_count"] >= 3 and skills["total_count"] == 0:
            gaps.append(CapabilityGap(
                layer=CapabilityLayer.SKILLS, priority="medium",
                gap="You have multiple MCP servers configured but no workflow "
                    "skills to orchestrate them",
                fix="Install workflow skills that chain multiple MCP servers "
                    "together for complex tasks",
            ))

        # 5. Servers configured but context layer entirely empty
        if tools["server_count"] > 0 and not context["has_agents_md"] \
                and not context["project_detected"]:
            gaps.append(CapabilityGap(
                layer=CapabilityLayer.CONTEXT, priority="high",
                gap="MCP servers are configured but the context layer is "
                    "empty -- the agent has no project awareness",
                fix="Add an AGENTS.md and ensure the project root is "
                    "detectable so the agent understands its environment",
            ))

        return gaps

    # -- Scoring -------------------------------------------------------------

    def _compute_score(
        self, tools: Dict[str, Any], prompts: Dict[str, Any],
        skills: Dict[str, Any], context: Dict[str, Any],
    ) -> int:
        t = min(tools["server_count"] * _POINTS_PER_SERVER, _MAX_LAYER_SCORE)
        p = (min(round(prompts["servers_with_prompts"] / tools["server_count"]
                       * _MAX_LAYER_SCORE), _MAX_LAYER_SCORE)
             if tools["server_count"] > 0 else 0)
        s = min(skills["total_count"] * _POINTS_PER_SKILL, _MAX_LAYER_SCORE)
        c = min((_AGENTS_MD_POINTS if context["has_agents_md"] else 0)
                + (_PROJECT_DETECTION_POINTS if context["project_detected"] else 0),
                _MAX_LAYER_SCORE)
        total = t + p + s + c
        logger.debug("Score breakdown: tools=%d prompts=%d skills=%d context=%d total=%d",
                      t, p, s, c, total)
        return total

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _match_known_prompts(server_name: str) -> List[str]:
        """Return known prompt names for *server_name* using fuzzy matching."""
        lower = server_name.lower()
        for pattern, prompts in _SERVERS_WITH_PROMPTS.items():
            if pattern in lower:
                return list(prompts)
        return []

    @staticmethod
    def _scan_skill_files(project_path: str) -> List[str]:
        """Scan for SKILL.md files under common project directories."""
        skills: List[str] = []
        root = Path(project_path)
        if not root.is_dir():
            return skills
        for search_dir in (root / ".skills", root / "skills",
                           root / ".claude" / "skills"):
            if search_dir.is_dir():
                for sf in search_dir.rglob("SKILL.md"):
                    name = sf.parent.name
                    if name and name not in skills:
                        skills.append(name)
                        logger.debug("Found skill file: %s", sf)
        return skills

    @staticmethod
    def _detect_project_context(root: Path) -> Dict[str, Any]:
        """Lightweight project detection (full ProjectAnalyzer or heuristics)."""
        info: Dict[str, Any] = {"detected": False}
        if _has_project and _ProjectAnalyzer is not None:
            try:
                result = _ProjectAnalyzer().analyze(str(root))
                project = getattr(result, "project", None)
                if project is not None:
                    return {"detected": True,
                            "language": getattr(project, "language", None),
                            "framework": getattr(project, "framework", None),
                            "vcs": getattr(project, "vcs", None)}
            except Exception:
                logger.debug("ProjectAnalyzer failed; falling back to heuristics")

        for marker, lang in _LANGUAGE_MARKERS.items():
            if (root / marker).exists():
                info.update(detected=True, language=lang)
                break
        for marker, fw in _FRAMEWORK_MARKERS.items():
            if (root / marker).exists():
                info["framework"] = fw
                break
        if (root / ".git").exists():
            info.update(detected=True, vcs="git")
        return info
