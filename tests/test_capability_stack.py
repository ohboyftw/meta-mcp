"""Tests for Capability Stack Model (R10)."""

from src.meta_mcp.capability_stack import (
    CapabilityStack,
    _run_async,
)
from src.meta_mcp.models import CapabilityLayer


# -- Helpers -----------------------------------------------------------------

def _make_tools_layer(servers=None):
    """Build a minimal tools layer dict."""
    names = servers or []
    return {
        "server_count": len(names),
        "servers": names,
        "raw_entries": {n: {"command": n, "args": []} for n in names},
    }


def _make_prompts_layer(servers_with_prompts=0, servers_without_prompts=0, total=0):
    return {
        "total_prompts": total,
        "servers_with_prompts": servers_with_prompts,
        "servers_without_prompts": servers_without_prompts,
        "prompts_by_server": {},
    }


def _make_skills_layer(skills=None):
    names = skills or []
    return {
        "global_skills": [],
        "project_skills": names,
        "all_skills": names,
        "total_count": len(names),
    }


def _make_context_layer(has_agents_md=False, project_detected=False, language=None):
    return {
        "has_agents_md": has_agents_md,
        "agents_md_path": None,
        "agents_md_size": 0,
        "project_detected": project_detected,
        "language": language,
        "framework": None,
        "vcs": None,
    }


# -- Tests: _run_async -------------------------------------------------------

class TestRunAsync:
    """Sync wrapper for async coroutines."""

    def test_runs_simple_coroutine(self):
        async def _get_value():
            return 42

        assert _run_async(_get_value()) == 42


# -- Tests: _match_known_prompts --------------------------------------------

class TestMatchKnownPrompts:
    """Fuzzy matching of server names to known prompt sets."""

    def test_github_server_matches(self):
        prompts = CapabilityStack._match_known_prompts("github")
        assert len(prompts) > 0
        assert "create-pull-request" in prompts

    def test_postgres_server_matches(self):
        prompts = CapabilityStack._match_known_prompts("server-postgres")
        assert "query-database" in prompts

    def test_unknown_server_no_match(self):
        prompts = CapabilityStack._match_known_prompts("my-custom-thing")
        assert prompts == []

    def test_partial_name_match(self):
        prompts = CapabilityStack._match_known_prompts("brave-search-v2")
        assert len(prompts) > 0


# -- Tests: _scan_skill_files -----------------------------------------------

class TestScanSkillFiles:
    """Discover SKILL.md files in project directories."""

    def test_no_skills_directory(self, tmp_path):
        skills = CapabilityStack._scan_skill_files(str(tmp_path))
        assert skills == []

    def test_finds_skills_in_dot_skills(self, tmp_path):
        skill_dir = tmp_path / ".skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# My Skill", encoding="utf-8")
        skills = CapabilityStack._scan_skill_files(str(tmp_path))
        assert "my-skill" in skills

    def test_finds_skills_in_claude_skills(self, tmp_path):
        skill_dir = tmp_path / ".claude" / "skills" / "code-review"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Code Review", encoding="utf-8")
        skills = CapabilityStack._scan_skill_files(str(tmp_path))
        assert "code-review" in skills

    def test_deduplicates_skill_names(self, tmp_path):
        for d in (".skills", "skills"):
            skill_dir = tmp_path / d / "same-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("# Same", encoding="utf-8")
        skills = CapabilityStack._scan_skill_files(str(tmp_path))
        assert skills.count("same-skill") == 1

    def test_nonexistent_path(self):
        skills = CapabilityStack._scan_skill_files("/nonexistent/path/xyz")
        assert skills == []


# -- Tests: _detect_project_context ------------------------------------------

class TestDetectProjectContext:
    """Heuristic project language/framework detection."""

    def test_detects_python_from_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        result = CapabilityStack._detect_project_context(tmp_path)
        assert result["detected"] is True
        assert result["language"] == "python"

    def test_detects_javascript_from_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        result = CapabilityStack._detect_project_context(tmp_path)
        assert result["detected"] is True
        assert result["language"] == "javascript"

    def test_detects_git_vcs(self, tmp_path):
        (tmp_path / ".git").mkdir()
        result = CapabilityStack._detect_project_context(tmp_path)
        assert result["detected"] is True
        assert result["vcs"] == "git"

    def test_empty_project(self, tmp_path):
        result = CapabilityStack._detect_project_context(tmp_path)
        assert result["detected"] is False


# -- Tests: Gap detection ---------------------------------------------------

class TestGapsTools:
    """Tool-layer gap detection."""

    def test_no_servers_gap(self):
        gaps = CapabilityStack._gaps_tools(_make_tools_layer([]))
        assert len(gaps) == 1
        assert gaps[0].layer == CapabilityLayer.TOOLS
        assert gaps[0].priority == "high"

    def test_servers_present_no_gap(self):
        gaps = CapabilityStack._gaps_tools(_make_tools_layer(["github"]))
        assert gaps == []


class TestGapsPrompts:
    """Prompt-layer gap detection."""

    def test_no_prompts_gap(self):
        tools = _make_tools_layer(["custom-server"])
        prompts = _make_prompts_layer(servers_with_prompts=0)
        gaps = CapabilityStack._gaps_prompts(prompts, tools)
        assert len(gaps) == 1
        assert gaps[0].layer == CapabilityLayer.PROMPTS

    def test_has_prompts_no_gap(self):
        tools = _make_tools_layer(["github"])
        prompts = _make_prompts_layer(servers_with_prompts=1)
        gaps = CapabilityStack._gaps_prompts(prompts, tools)
        assert gaps == []

    def test_no_servers_no_gap(self):
        tools = _make_tools_layer([])
        prompts = _make_prompts_layer()
        gaps = CapabilityStack._gaps_prompts(prompts, tools)
        assert gaps == []


class TestGapsSkills:
    """Skills-layer gap detection."""

    def test_no_skills_gap(self):
        gaps = CapabilityStack._gaps_skills(_make_skills_layer([]))
        assert len(gaps) == 1
        assert gaps[0].layer == CapabilityLayer.SKILLS

    def test_has_skills_no_gap(self):
        gaps = CapabilityStack._gaps_skills(_make_skills_layer(["code-review"]))
        assert gaps == []


class TestGapsContext:
    """Context-layer gap detection."""

    def test_no_agents_md_gap(self):
        ctx = _make_context_layer(has_agents_md=False, project_detected=True)
        gaps = CapabilityStack._gaps_context(ctx)
        assert any(g.gap and "AGENTS.md" in g.gap for g in gaps)

    def test_no_project_detected_gap(self):
        ctx = _make_context_layer(has_agents_md=True, project_detected=False)
        gaps = CapabilityStack._gaps_context(ctx)
        assert any("project type" in g.gap for g in gaps)

    def test_full_context_no_gap(self):
        ctx = _make_context_layer(has_agents_md=True, project_detected=True)
        gaps = CapabilityStack._gaps_context(ctx)
        assert gaps == []


class TestGapsCrossLayer:
    """Cross-layer gap detection."""

    def test_complementary_pair_gap(self):
        tools = _make_tools_layer(["github"])
        prompts = _make_prompts_layer(servers_with_prompts=1, total=2)
        skills = _make_skills_layer([])
        context = _make_context_layer(has_agents_md=True, project_detected=True)
        gaps = CapabilityStack._gaps_cross_layer(tools, prompts, skills, context)
        # Should suggest code-review skill for github server
        assert any("code-review" in g.fix for g in gaps)

    def test_skills_without_agents_md_gap(self):
        tools = _make_tools_layer(["srv"])
        prompts = _make_prompts_layer()
        skills = _make_skills_layer(["my-skill"])
        context = _make_context_layer(has_agents_md=False)
        gaps = CapabilityStack._gaps_cross_layer(tools, prompts, skills, context)
        assert any("AGENTS.md" in g.gap for g in gaps)

    def test_many_servers_no_skills_gap(self):
        tools = _make_tools_layer(["s1", "s2", "s3"])
        prompts = _make_prompts_layer()
        skills = _make_skills_layer([])
        context = _make_context_layer(has_agents_md=True, project_detected=True)
        gaps = CapabilityStack._gaps_cross_layer(tools, prompts, skills, context)
        assert any("workflow" in g.gap.lower() for g in gaps)


# -- Tests: Scoring ---------------------------------------------------------

class TestScoring:
    """Capability stack scoring (0-100)."""

    def test_empty_stack_zero(self):
        stack = CapabilityStack.__new__(CapabilityStack)
        score = stack._compute_score(
            _make_tools_layer([]),
            _make_prompts_layer(),
            _make_skills_layer([]),
            _make_context_layer(),
        )
        assert score == 0

    def test_tools_contribute_score(self):
        stack = CapabilityStack.__new__(CapabilityStack)
        score = stack._compute_score(
            _make_tools_layer(["s1", "s2"]),
            _make_prompts_layer(),
            _make_skills_layer([]),
            _make_context_layer(),
        )
        assert score > 0

    def test_context_with_agents_md(self):
        stack = CapabilityStack.__new__(CapabilityStack)
        without = stack._compute_score(
            _make_tools_layer([]),
            _make_prompts_layer(),
            _make_skills_layer([]),
            _make_context_layer(has_agents_md=False),
        )
        with_md = stack._compute_score(
            _make_tools_layer([]),
            _make_prompts_layer(),
            _make_skills_layer([]),
            _make_context_layer(has_agents_md=True),
        )
        assert with_md > without

    def test_score_capped_at_100(self):
        stack = CapabilityStack.__new__(CapabilityStack)
        # Max out every layer
        score = stack._compute_score(
            _make_tools_layer(["s1", "s2", "s3", "s4", "s5"]),
            _make_prompts_layer(servers_with_prompts=5),
            _make_skills_layer(["a", "b", "c", "d", "e"]),
            _make_context_layer(has_agents_md=True, project_detected=True),
        )
        assert score <= 100

    def test_skills_contribute_score(self):
        stack = CapabilityStack.__new__(CapabilityStack)
        no_skills = stack._compute_score(
            _make_tools_layer([]),
            _make_prompts_layer(),
            _make_skills_layer([]),
            _make_context_layer(),
        )
        with_skills = stack._compute_score(
            _make_tools_layer([]),
            _make_prompts_layer(),
            _make_skills_layer(["s1"]),
            _make_context_layer(),
        )
        assert with_skills > no_skills
