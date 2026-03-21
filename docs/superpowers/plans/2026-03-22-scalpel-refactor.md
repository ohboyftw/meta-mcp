# Meta-MCP Scalpel Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape meta-mcp from 39 scattered tools to 31 focused tools in 3 tiers, cutting scaffolded modules and adding profile YAML bootstrap.

**Architecture:** Delete 2 modules entirely (intent.py, capability_stack.py), gut 4 modules (orchestration, registry, skills, memory), add a profile YAML loader, and restructure server.py registrations into 3 tiers. memory.py survives as internal infra.

**Tech Stack:** Python 3.10+, Pydantic, PyYAML, FastMCP, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-meta-mcp-scalpel-refactor-design.md`

---

## File Map

**Deleted:**
- `src/meta_mcp/intent.py` — entire module
- `src/meta_mcp/capability_stack.py` — entire module

**Created:**
- `src/meta_mcp/profiles/__init__.py` — profile loader with Pydantic validation
- `src/meta_mcp/profiles/default.yaml` — minimal built-in profile

**Modified (in task order):**
- `src/meta_mcp/models.py` — remove 13 dead models
- `src/meta_mcp/tools.py` — remove 8 tool classes + dead imports
- `src/meta_mcp/server.py` — remove 8 tool registrations, reorganize into 3 tiers
- `src/meta_mcp/orchestration.py` — remove execute_workflow + helpers
- `src/meta_mcp/registry.py` — remove compute_trust_score + constants
- `src/meta_mcp/skills.py` — remove generate_workflow_skill + discover_prompts
- `src/meta_mcp/memory.py` — remove get_installation_history method
- `src/meta_mcp/project_init.py` — replace hardcoded profiles with YAML loader
- `tests/test_tool_schema.py` — update for 31 tools
- `README.md` — 3-tier structure, updated counts

---

## Task 1: Delete Dead Models from models.py

**Files:**
- Modify: `src/meta_mcp/models.py`

These 13 models are only referenced by modules being deleted. Remove them first so later deletions don't leave dangling imports.

- [ ] **Step 1: Verify no surviving code references the 13 models**

Run:
```bash
cd D:/Home/meta-mcp && grep -rn "MissingCapability\|CapabilityGapResult\|WorkflowStep\b\|WorkflowStepStatus\|WorkflowSuggestion\|CapabilityGap\b\|CapabilityStackReport\|CapabilityBundleItem\|CapabilityBundleResult\|CapabilityLayer\|WorkflowExecutionStep\|WorkflowExecutionResult\|GeneratedSkill" src/meta_mcp/ --include="*.py" | grep -v "models.py" | grep -v "intent.py" | grep -v "capability_stack.py" | grep -v "orchestration.py"
```

Expected: Only hits in `tools.py` (for tool classes being deleted) and `skills.py` (for `GeneratedSkill` in `generate_workflow_skill` being deleted). No hits in surviving code.

- [ ] **Step 2: Delete the 13 model classes from models.py**

Delete these class definitions and any associated imports they use exclusively:

From intent.py group (lines ~92, ~196-222):
- `WorkflowStepStatus` enum (~line 92)
- `MissingCapability` (~lines 196-200)
- `CapabilityGapResult` (~lines 203-207)
- `WorkflowStep` (~lines 210-214)
- `WorkflowSuggestion` (~lines 217-222)

From capability_stack.py group (~lines 40, 502-528):
- `CapabilityLayer` enum (~line 40)
- `CapabilityGap` (~lines 502-506)
- `CapabilityStackReport` (~lines 509-515)
- `CapabilityBundleItem` (~lines 518-522)
- `CapabilityBundleResult` (~lines 525-528)

From orchestration.py group (~lines 425-439):
- `WorkflowExecutionStep` (~lines 425-432)
- `WorkflowExecutionResult` (~lines 435-439)

From skills.py group (~lines 493-497):
- `GeneratedSkill` (~lines 493-497)

- [ ] **Step 3: Verify models.py still parses**

Run:
```bash
cd D:/Home/meta-mcp && py -c "import ast; ast.parse(open('src/meta_mcp/models.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/meta_mcp/models.py
git commit -m "refactor: remove 13 dead models from models.py

Delete Pydantic models only referenced by modules being cut:
intent.py (5), capability_stack.py (5), orchestration.py (2), skills.py (1)"
```

---

## Task 2: Delete intent.py and capability_stack.py

**Files:**
- Delete: `src/meta_mcp/intent.py`
- Delete: `src/meta_mcp/capability_stack.py`

- [ ] **Step 1: Verify no surviving imports**

Run:
```bash
cd D:/Home/meta-mcp && grep -rn "from .intent\|from .capability_stack\|import intent\|import capability_stack" src/meta_mcp/ --include="*.py" | grep -v "intent.py" | grep -v "capability_stack.py"
```

Expected: Hits only in `tools.py` (lines 24, 32) — these get cleaned in Task 3.

- [ ] **Step 2: Delete the files**

```bash
rm src/meta_mcp/intent.py src/meta_mcp/capability_stack.py
```

- [ ] **Step 3: Commit**

```bash
git add -u src/meta_mcp/intent.py src/meta_mcp/capability_stack.py
git commit -m "refactor: delete intent.py and capability_stack.py

Remove NLU keyword-matching theater and list-only capability audit.
Neither module delivered real value."
```

---

## Task 3: Remove 8 Tool Classes + Dead Imports from tools.py

**Files:**
- Modify: `src/meta_mcp/tools.py`

- [ ] **Step 1: Remove dead imports**

Delete these import lines from the top of `tools.py`:
- `from .intent import IntentEngine` (~line 24)
- `from .capability_stack import CapabilityStack` (~line 32)

**Keep** `from .memory import ConversationalMemory` (line 29) — still used by surviving tools.
**Keep** `from .orchestration import ServerOrchestrator` (line 30) — still used by surviving tools.

- [ ] **Step 2: Delete 8 tool classes**

Delete these class definitions entirely:

1. `DetectCapabilityGapsTool` (~lines 364-395)
2. `SuggestWorkflowTool` (~lines 397-426)
3. `GetInstallationHistoryTool` (~lines 664-698)
4. `ExecuteWorkflowTool` (~lines 809-847)
5. `GenerateWorkflowSkillTool` (~lines 977-1011)
6. `DiscoverPromptsTool` (~lines 1043-1071)
7. `AnalyzeCapabilityStackTool` (~lines 1076-1119)
8. `RepoCatalogTool` (~lines 1371-1413)

- [ ] **Step 3: Fold RepoCatalogTool output into ListRepoSkillsTool**

In `ListRepoSkillsTool.apply()`, insert the following just **before** the existing `return content` statement (currently ~line 1180). The existing method already shows repos and skills; this adds the servers section that `RepoCatalogTool` used to provide:

```python
        # Add catalog summary (folded from RepoCatalogTool)
        catalog = manager.full_catalog()
        if catalog["servers"]:
            content += f"## MCP Servers ({len(catalog['servers'])})\n\n"
            for s in catalog["servers"]:
                content += f"- **{s['name']}** [{s['category']}]: {s['description'][:80]}\n"
            content += "\n"

        return content
```

- [ ] **Step 4: Verify tools.py parses**

Run:
```bash
cd D:/Home/meta-mcp && py -c "import ast; ast.parse(open('src/meta_mcp/tools.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/meta_mcp/tools.py
git commit -m "refactor: remove 8 tool classes from tools.py

Cut: DetectCapabilityGaps, SuggestWorkflow, GetInstallationHistory,
AnalyzeCapabilityStack, ExecuteWorkflow, DiscoverPrompts,
GenerateWorkflowSkill, RepoCatalog (folded into ListRepoSkills).
Remove dead imports for IntentEngine and CapabilityStack."
```

---

## Task 4: Reorganize server.py into 3 Tiers

**Files:**
- Modify: `src/meta_mcp/server.py`

- [ ] **Step 1: Remove 8 import lines**

Delete the import lines for the 8 removed tool classes (~lines 34, 35, 47, 53, 59, 61, 63, 71 in the import block).

- [ ] **Step 2: Remove 8 instantiation lines**

Delete the 8 tool instantiation lines (~lines 97, 98, 110, 116, 122, 124, 132, 134) from `_initialize_tools`.

- [ ] **Step 3: Reorganize with tier comments**

Replace the existing comments in `_initialize_tools` with:

```python
        self.tools = [
            # ── Tier 1: Sync & Bootstrap ──────────────────────────────
            DetectClientsTool(),
            SyncConfigurationsTool(),
            ValidateConfigTool(),
            ProjectInitTool(),
            ProjectValidateTool(),
            # ── Tier 2: Skills & Repo ─────────────────────────────────
            SearchCapabilitiesTool(),
            ListSkillsTool(),
            InstallSkillTool(),
            UninstallSkillTool(),
            AnalyzeSkillTrustTool(),
            ListRepoSkillsTool(),
            SearchRepoTool(),
            InstallFromRepoTool(),
            BatchInstallFromRepoTool(),
            ListRepoServersTool(),
            AddSkillRepoTool(),
            # ── Tier 3: Server Lifecycle ──────────────────────────────
            SearchMcpServersTool(),
            GetServerInfoTool(),
            InstallMcpServerTool(),
            ListInstalledServersTool(),
            UninstallMcpServerTool(),
            SearchFederatedTool(),
            RefreshServerCacheTool(),
            GetManagerStatsTool(),
            AnalyzeProjectContextTool(),
            InstallWorkflowTool(),
            CheckEcosystemHealthTool(),
            StartServerTool(),
            StopServerTool(),
            RestartServerTool(),
            DiscoverServerToolsTool(),
        ]
```

- [ ] **Step 4: Verify server.py parses**

Run:
```bash
cd D:/Home/meta-mcp && py -c "import ast; ast.parse(open('src/meta_mcp/server.py').read()); print('OK')"
```

- [ ] **Step 5: Count tools = 31**

Run:
```bash
cd D:/Home/meta-mcp && py -c "
import ast, re
tree = ast.parse(open('src/meta_mcp/server.py').read())
for node in ast.walk(tree):
    if isinstance(node, ast.List):
        calls = [n for n in node.elts if isinstance(n, ast.Call)]
        if len(calls) > 20:
            print(f'Tool count: {len(calls)}')
"
```

Expected: `Tool count: 31`

- [ ] **Step 6: Commit**

```bash
git add src/meta_mcp/server.py
git commit -m "refactor: reorganize server.py into 3-tier tool surface

Tier 1 (Sync & Bootstrap): 5 tools
Tier 2 (Skills & Repo): 11 tools
Tier 3 (Server Lifecycle): 15 tools
Total: 31 tools (down from 39)"
```

---

## Task 5: Gut orchestration.py (remove execute_workflow)

**Files:**
- Modify: `src/meta_mcp/orchestration.py`

- [ ] **Step 1: Delete execute_workflow method**

Remove the `execute_workflow` async method (~lines 406-493) from the `ServerOrchestrator` class.

- [ ] **Step 2: Delete helpers**

Remove:
- `_PREVIOUS_OUTPUT_TOKEN = "$previous"` (~line 38)
- `_substitute_previous_output` function (~lines 100-128)

- [ ] **Step 3: Remove now-unused imports**

Check the top of `orchestration.py` for imports only used by the deleted code (e.g., model imports for `WorkflowExecutionStep`, `WorkflowExecutionResult`). Remove those.

- [ ] **Step 4: Verify**

Run:
```bash
cd D:/Home/meta-mcp && py -c "import ast; ast.parse(open('src/meta_mcp/orchestration.py').read()); print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add src/meta_mcp/orchestration.py
git commit -m "refactor: remove execute_workflow from orchestration.py

Keep server start/stop/restart/discover. Remove workflow chaining stub
that had no state passing, error handling, or rollback."
```

---

## Task 6: Strip Trust Scoring from registry.py

**Files:**
- Modify: `src/meta_mcp/registry.py`

- [ ] **Step 1: Delete trust score constants**

Remove:
- `_SOURCE_MULTIPLIERS` dict (~lines 39-47)
- `_MULTI_SOURCE_BONUS` (~line 53)
- `_RECENT_UPDATE_BONUS` (~line 64)
- `_SECURITY_SCAN_BONUS` (~line 65)
- `_DOCUMENTATION_BONUS` (~line 66)
- `_MAX_TRUST_SCORE` (~line 67)
- `_TRUST_LEVEL_THRESHOLDS` (~lines 69-74)
- `_STARS_THRESHOLDS` (~lines 55-62)

- [ ] **Step 2: Delete compute_trust_score and helper functions**

Remove:
- `compute_trust_score` function (~lines 446-520)
- `_stars_score` function (~lines 429-436) — only called by `compute_trust_score`
- `_trust_level_for` function (~lines 439-443) — only called by `compute_trust_score`

- [ ] **Step 3: Replace call site with neutral default**

At ~line 603 where `compute_trust_score` was called inside `search_federated`, replace with a neutral default `TrustScore`. The `TrustScore` model uses these fields: `score: int`, `level: TrustLevel` (enum), `signals: Dict[str, Any]`, `explanation: str`.

```python
            trust = TrustScore(
                score=50,
                level=TrustLevel.COMMUNITY,
                signals={"source": "aggregated from registry"},
                explanation="Neutral default — trust scoring removed",
            )
```

Ensure `TrustLevel` is still imported in `registry.py` (it already should be).

- [ ] **Step 4: Verify**

Run:
```bash
cd D:/Home/meta-mcp && py -c "import ast; ast.parse(open('src/meta_mcp/registry.py').read()); print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add src/meta_mcp/registry.py
git commit -m "refactor: strip trust scoring from registry.py

Remove compute_trust_score and arbitrary multiplier constants.
search_federated returns neutral trust score. Aggregation preserved."
```

---

## Task 7: Remove Dead Methods from skills.py

**Files:**
- Modify: `src/meta_mcp/skills.py`

- [ ] **Step 1: Delete generate_workflow_skill method**

Remove the method (~lines 790-859) from the `SkillsManager` class.

- [ ] **Step 2: Delete discover_prompts method**

Remove the method (~lines 754-786) from the `SkillsManager` class.

**Keep** `_KNOWN_SERVER_PROMPTS` dict (~lines 183-229) — it is used by the surviving `search_capabilities` method.

- [ ] **Step 3: Clean up any imports only used by deleted methods**

Check for model imports (`GeneratedSkill`, etc.) that are no longer needed. Remove them.

- [ ] **Step 4: Verify**

Run:
```bash
cd D:/Home/meta-mcp && py -c "import ast; ast.parse(open('src/meta_mcp/skills.py').read()); print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add src/meta_mcp/skills.py
git commit -m "refactor: remove generate_workflow_skill and discover_prompts

Keep _KNOWN_SERVER_PROMPTS (used by search_capabilities).
Only the standalone tools are cut, not the backing data."
```

---

## Task 8: Remove get_installation_history from memory.py

**Files:**
- Modify: `src/meta_mcp/memory.py`

- [ ] **Step 1: Delete get_installation_history method**

Remove the `get_installation_history` method (~lines 237-261) from `ConversationalMemory`.

**Keep everything else** — `record_installation()`, `record_failure()`, `check_failure_memory()` are used by surviving tools.

- [ ] **Step 2: Verify**

Run:
```bash
cd D:/Home/meta-mcp && py -c "import ast; ast.parse(open('src/meta_mcp/memory.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add src/meta_mcp/memory.py
git commit -m "refactor: remove get_installation_history from memory.py

Module stays as internal infra. Only the public tool is cut."
```

---

## Task 9: Build Profile YAML System

**Files:**
- Create: `src/meta_mcp/profiles/__init__.py`
- Create: `src/meta_mcp/profiles/default.yaml`
- Test: `tests/test_profiles.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_profiles.py`:

```python
"""Tests for profile YAML loading and validation."""

import pytest
from pathlib import Path
from meta_mcp.profiles import load_profile, ProfileConfig, ProfileNotFoundError


FIXTURES = Path(__file__).parent / "fixtures" / "profiles"


@pytest.fixture(autouse=True)
def setup_fixtures(tmp_path):
    """Create test profile fixtures."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()

    # Valid profile
    (profiles_dir / "test-stack.yaml").write_text(
        "name: test-stack\n"
        "description: Test profile\n"
        "skills:\n  - beacon\n  - engram\n"
        "servers:\n  - name: beacon\n    auto_install: true\n"
        "env_required:\n  - TEST_VAR\n"
        "post_install:\n  - 'Run tests'\n"
    )

    # Minimal valid profile
    (profiles_dir / "minimal.yaml").write_text(
        "name: minimal\ndescription: Minimal test\n"
    )

    # Malformed YAML
    (profiles_dir / "bad.yaml").write_text(
        "name: bad\ndescription: [unterminated\n"
    )

    # Missing required fields
    (profiles_dir / "no-name.yaml").write_text(
        "description: No name field\n"
    )

    return tmp_path  # Return parent — _search_dirs appends /profiles


def test_load_valid_profile(setup_fixtures):
    profile = load_profile("test-stack", extra_dirs=[setup_fixtures])
    assert isinstance(profile, ProfileConfig)
    assert profile.name == "test-stack"
    assert profile.description == "Test profile"
    assert profile.skills == ["beacon", "engram"]
    assert len(profile.servers) == 1
    assert profile.servers[0].name == "beacon"
    assert profile.servers[0].auto_install is True
    assert profile.env_required == ["TEST_VAR"]
    assert profile.post_install == ["Run tests"]


def test_load_minimal_profile(setup_fixtures):
    profile = load_profile("minimal", extra_dirs=[setup_fixtures])
    assert profile.name == "minimal"
    assert profile.skills == []
    assert profile.servers == []


def test_load_default_profile():
    profile = load_profile("default", extra_dirs=[])
    assert profile.name == "default"
    assert profile.skills == []


def test_profile_not_found():
    with pytest.raises(ProfileNotFoundError, match="nonexistent"):
        load_profile("nonexistent", extra_dirs=[])


def test_malformed_yaml(setup_fixtures):
    with pytest.raises(ValueError, match="YAML"):
        load_profile("bad", extra_dirs=[setup_fixtures])


def test_missing_required_field(setup_fixtures):
    with pytest.raises(ValueError, match="name"):
        load_profile("no-name", extra_dirs=[setup_fixtures])


def test_discovery_order(setup_fixtures, tmp_path):
    """First match wins — extra_dirs before built-in."""
    # Create a 'default' profile in extra_dirs that overrides built-in
    (setup_fixtures / "default.yaml").write_text(
        "name: default\ndescription: Overridden default\n"
    )
    profile = load_profile("default", extra_dirs=[setup_fixtures])
    assert profile.description == "Overridden default"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd D:/Home/meta-mcp && py -m pytest tests/test_profiles.py -v 2>&1 | head -30
```

Expected: FAIL — `ModuleNotFoundError: No module named 'meta_mcp.profiles'`

- [ ] **Step 3: Create the default.yaml**

Create `src/meta_mcp/profiles/default.yaml`:

```yaml
name: default
description: Minimal setup — registers meta-mcp only
skills: []
servers: []
env_required: []
post_install:
  - "Add profiles to your skill repo under profiles/*.yaml"
```

- [ ] **Step 4: Create profiles/__init__.py**

Create `src/meta_mcp/profiles/__init__.py`:

```python
"""
Profile YAML loading for project bootstrap.

Profiles define which skills and MCP servers to install when bootstrapping
a project. They are discovered in order:
  1. Skill repo: <repo>/profiles/*.yaml
  2. Global: ~/.config/meta-mcp/profiles/*.yaml
  3. Built-in: this package's default.yaml
"""

import platform
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, field_validator

from ..settings import get_settings


class ProfileServerEntry(BaseModel):
    """A server entry within a profile."""
    name: str
    auto_install: bool = False


class ProfileConfig(BaseModel):
    """Validated profile configuration."""
    name: str
    description: str
    skills: List[str] = []
    servers: List[ProfileServerEntry] = []
    env_required: List[str] = []
    post_install: List[str] = []


class ProfileNotFoundError(FileNotFoundError):
    """Raised when a profile YAML cannot be found in any search location."""
    pass


_BUILTIN_DIR = Path(__file__).parent


def _search_dirs(extra_dirs: Optional[List[Path]] = None) -> List[Path]:
    """Return profile search directories in priority order."""
    dirs: List[Path] = []

    # 1. Extra dirs (skill repos)
    if extra_dirs:
        for d in extra_dirs:
            profiles_subdir = Path(d) / "profiles"
            if profiles_subdir.is_dir():
                dirs.append(profiles_subdir)

    # 2. Extra dirs from settings
    try:
        settings = get_settings()
        for d in settings.skills_extra_dirs:
            profiles_subdir = d / "profiles"
            if profiles_subdir.is_dir() and profiles_subdir not in dirs:
                dirs.append(profiles_subdir)
    except Exception:
        pass

    # 3. Global config dir
    if platform.system() == "Windows":
        import os
        global_profiles = Path(os.environ.get("APPDATA", "~")) / "meta-mcp" / "profiles"
    else:
        global_profiles = Path.home() / ".config" / "meta-mcp" / "profiles"
    if global_profiles.is_dir():
        dirs.append(global_profiles)

    # 4. Built-in
    dirs.append(_BUILTIN_DIR)

    return dirs


def load_profile(
    name: str,
    extra_dirs: Optional[List[Path]] = None,
) -> ProfileConfig:
    """Load a profile by name from the search path.

    Raises:
        ProfileNotFoundError: if no matching YAML found.
        ValueError: if YAML is malformed or missing required fields.
    """
    searched: List[str] = []

    for search_dir in _search_dirs(extra_dirs):
        candidate = search_dir / f"{name}.yaml"
        searched.append(str(candidate))
        if candidate.is_file():
            return _parse_profile(candidate)

    raise ProfileNotFoundError(
        f"Profile '{name}' not found. Searched:\n"
        + "\n".join(f"  - {p}" for p in searched)
    )


def list_profiles(extra_dirs: Optional[List[Path]] = None) -> List[ProfileConfig]:
    """List all available profiles across search dirs."""
    seen: set = set()
    profiles: List[ProfileConfig] = []

    for search_dir in _search_dirs(extra_dirs):
        if not search_dir.is_dir():
            continue
        for yaml_file in sorted(search_dir.glob("*.yaml")):
            name = yaml_file.stem
            if name not in seen:
                seen.add(name)
                try:
                    profiles.append(_parse_profile(yaml_file))
                except (ValueError, Exception):
                    pass  # Skip malformed profiles in listing

    return profiles


def _parse_profile(path: Path) -> ProfileConfig:
    """Parse and validate a single profile YAML file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"Profile {path} must be a YAML mapping, got {type(raw).__name__}")

    if "name" not in raw:
        raise ValueError(f"Profile {path} missing required field: name")
    if "description" not in raw:
        raise ValueError(f"Profile {path} missing required field: description")

    try:
        return ProfileConfig(**raw)
    except Exception as exc:
        raise ValueError(f"Profile validation error in {path}: {exc}") from exc
```

- [ ] **Step 5: Run tests**

Run:
```bash
cd D:/Home/meta-mcp && py -m pytest tests/test_profiles.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/meta_mcp/profiles/ tests/test_profiles.py
git commit -m "feat: add profile YAML system for project bootstrap

ProfileConfig Pydantic model with discovery chain:
skill_repo/profiles > global > built-in.
Includes default.yaml and full test coverage."
```

---

## Task 10: Rewire project_init.py to Use Profiles

**Files:**
- Modify: `src/meta_mcp/project_init.py`

- [ ] **Step 1: Read current project_init.py**

Read the file to understand the exact structure of `KNOWN_PROJECT_SERVERS` (~lines 38-85), `PROFILES` (~lines 87-91), and `_resolve_server_list` (~lines 259-271).

- [ ] **Step 2: Replace hardcoded dicts with profile loader**

At the top of the file, add:
```python
from .profiles import load_profile, list_profiles, ProfileNotFoundError
```

Delete `KNOWN_PROJECT_SERVERS` dict and `PROFILES` dict.

- [ ] **Step 3: Update _resolve_server_list to use profiles**

Replace the method body to load from YAML:

```python
    def _resolve_server_list(self, profile: Optional[str] = None) -> List[str]:
        """Resolve which servers to install from a profile name."""
        if not profile:
            profile = "default"
        try:
            config = load_profile(profile)
            return [s.name for s in config.servers if s.auto_install]
        except ProfileNotFoundError:
            logger.warning("Profile '%s' not found, using empty list", profile)
            return []
```

- [ ] **Step 4: Update the main init method to use ProfileConfig**

Find the main `project_init` or `initialize_project` method and update it to:
1. Load the profile
2. Check `env_required` and warn for missing vars
3. Install skills from `config.skills`
4. Install servers from `config.servers` where `auto_install=True`
5. Display `post_install` messages

- [ ] **Step 5: Verify**

Run:
```bash
cd D:/Home/meta-mcp && py -c "import ast; ast.parse(open('src/meta_mcp/project_init.py').read()); print('OK')"
```

- [ ] **Step 6: Commit**

```bash
git add src/meta_mcp/project_init.py
git commit -m "refactor: replace hardcoded profiles with YAML loader

project_init now reads profile YAML files from skill repos.
Profiles are shareable and customizable."
```

> **Follow-up (out of scope for this plan):** The `meta-mcp-repo` SKILL.md in the skill repo should be updated so Option 5 uses profile-based `project_init` instead of manual server config. See spec section 6.8.

---

## Task 11: Update test_tool_schema.py

**Files:**
- Modify: `tests/test_tool_schema.py`

- [ ] **Step 1: Read current test file**

Read `tests/test_tool_schema.py` to find any hardcoded tool names or counts.

- [ ] **Step 2: Remove references to deleted tools**

If any test references `DetectCapabilityGapsTool`, `SuggestWorkflowTool`, etc., remove those references.

- [ ] **Step 3: Add explicit 31-tool count assertion**

In the `TestFastMCPIntegration` class, update or add:

```python
def test_tool_count(self):
    """Verify exactly 31 tools are registered after scalpel refactor."""
    server = MetaMCPServer()
    assert len(server.tools) == 31, f"Expected 31 tools, got {len(server.tools)}"
```

- [ ] **Step 4: Run all tests**

Run:
```bash
cd D:/Home/meta-mcp && py -m pytest tests/ -v 2>&1 | tail -20
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_tool_schema.py
git commit -m "test: update test_tool_schema.py for 31-tool surface"
```

---

## Task 12: Delete Orphaned Test Files

**Files:**
- Delete: `tests/test_intent.py` (if exists)
- Delete: `tests/test_capability_stack.py` (if exists)

- [ ] **Step 1: Check which test files exist**

Run:
```bash
ls D:/Home/meta-mcp/tests/test_intent* D:/Home/meta-mcp/tests/test_capability* 2>&1
```

- [ ] **Step 2: Delete any that exist**

```bash
rm -f tests/test_intent.py tests/test_capability_stack.py
```

- [ ] **Step 3: Commit (if any deleted)**

```bash
git add -u tests/
git commit -m "test: remove test files for deleted modules"
```

---

## Task 13: Rewrite README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update positioning line**

Change the tagline under the ASCII art to:

> **Keep your MCP configuration in sync across all your AI tools, and bootstrap project environments instantly.**

- [ ] **Step 2: Update tool count badges**

Change `39` → `31` in the tools badge.

- [ ] **Step 3: Rewrite tool reference as 3 tiers**

Replace the current 11-section tool tables with 3 collapsible `<details>` sections matching the spec's Tier 1/2/3 structure with the exact tool lists from the spec.

- [ ] **Step 4: Update architecture listing**

Remove `intent.py` and `capability_stack.py`. Add `profiles/` directory. Update the module count.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: update README for 3-tier 31-tool surface

New positioning, updated badges, collapsible 3-tier tool reference.
Removes references to deleted modules."
```

---

## Task 14: Final Verification

- [ ] **Step 1: Syntax check all modified files**

Run:
```bash
cd D:/Home/meta-mcp && for f in src/meta_mcp/server.py src/meta_mcp/tools.py src/meta_mcp/orchestration.py src/meta_mcp/registry.py src/meta_mcp/skills.py src/meta_mcp/memory.py src/meta_mcp/models.py src/meta_mcp/project_init.py src/meta_mcp/profiles/__init__.py; do py -c "import ast; ast.parse(open('$f').read()); print('$f: OK')"; done
```

- [ ] **Step 2: Check no dead imports remain**

Run:
```bash
cd D:/Home/meta-mcp && grep -rn "from .intent\|from .capability_stack\|IntentEngine\|CapabilityStack[^R]" src/meta_mcp/ --include="*.py"
```

Expected: No output.

- [ ] **Step 3: Verify ai_fallback.py still imports correctly**

Run:
```bash
cd D:/Home/meta-mcp && py -c "from meta_mcp.ai_fallback import AIFallbackManager; print('ai_fallback OK')"
```

Expected: `ai_fallback OK` — confirms memory.py survived and its import resolves.

- [ ] **Step 4: Run full test suite**

Run:
```bash
cd D:/Home/meta-mcp && py -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 5: Verify tool count**

Run:
```bash
cd D:/Home/meta-mcp && py -c "from meta_mcp.server import MetaMCPServer; s = MetaMCPServer(); print(f'Tools: {len(s.tools)}')"
```

Expected: `Tools: 31`

- [ ] **Step 6: Push**

```bash
git push origin main
```
