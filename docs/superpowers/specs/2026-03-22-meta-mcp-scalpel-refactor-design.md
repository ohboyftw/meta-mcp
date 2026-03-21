# Meta-MCP Scalpel Refactor — Design Spec

**Date:** 2026-03-22
**Status:** Draft (reviewed, issues fixed)
**Author:** Aravind + Claude

## 1. Problem Statement

Meta-MCP currently exposes 39 tools across 11 capability areas. The staff review
found that only 3 areas are production-solid, 4 are functional, and 4 are
scaffolded stubs that dilute the value proposition. The project claims to "manage
all your MCP servers" but half the promised features are incomplete.

The real value — multi-client configuration sync and project environment
bootstrapping — is buried under noise.

## 2. Goal

Reshape the codebase to match the positioning:

> **Meta-MCP: Keep your MCP configuration in sync across all your AI tools, and
> bootstrap project environments instantly.**

Specifically:
- Remove scaffolded modules that deliver no real value
- Promote config sync and bootstrap to the hero path
- Restructure the tool surface from 11 flat areas into 3 clear tiers
- Replace hardcoded bootstrap profiles with YAML-based profile system
- Reduce tool count from 39 to 31

## 3. Target Audience

Primary: Aravind's own workflow — syncing 6+ MCP clients, bootstrapping skill
repos (beacon, engram, rlm, code-graph), managing a multi-agent development
setup. Dogfood-first, open-source second.

## 4. Cuts

### 4.1 Modules Removed Entirely

| Module | Tools Removed | Reason |
|--------|---------------|--------|
| `intent.py` | `detect_capability_gaps`, `suggest_workflow` | Keyword matching pretending to be NLU. No semantic understanding. Users know what they need. |
| `capability_stack.py` | `analyze_capability_stack` | Lists capabilities without cross-layer analysis. Audit without insight. |

### 4.2 Modules Reclassified (Kept but Reduced)

**`memory.py`** — Reclassified from "delete entirely" to "keep as internal
module, remove its public tool."

`ConversationalMemory` is actively used by surviving tools:
- `InstallMcpServerTool` (`tools.py:159`) — calls `record_installation()`,
  `record_failure()`, `check_failure_memory()`
- `InstallWorkflowTool` (`tools.py:512`) — calls `record_installation()`
- `GetInstallationHistoryTool` (`tools.py:669`) — this tool is cut
- `AIFallbackManager` (`ai_fallback.py:19,36`) — calls `ConversationalMemory()`

**Action:** Keep `memory.py` as internal infrastructure. Only remove the
`GetInstallationHistoryTool` from the public tool surface.

### 4.3 Partial Cuts

| Module | Kept | Cut | Reason |
|--------|------|-----|--------|
| `orchestration.py` | `start_server`, `stop_server`, `restart_server`, `discover_server_tools` | `execute_workflow` method + `_substitute_previous_output` function + `_PREVIOUS_OUTPUT_TOKEN` constant | Server lifecycle is real. Workflow chaining is a stub — no state passing, no error handling, no rollback. |
| `registry.py` | `search_federated` (aggregation across 4 registries) | `compute_trust_score` function (module-level, line 446) and trust multiplier constants. The `FederatedSearchResult` model's `trust_score` field becomes a stub returning a neutral default. | Aggregation is valuable. Arbitrary scoring is theater. |
| `skills.py` | All skill management (search, list, install, uninstall, trust), `_KNOWN_SERVER_PROMPTS` (used by `search_capabilities`) | `generate_workflow_skill`, `discover_prompts` | Workflow-to-skill generation is half-baked. Prompt discovery as a standalone tool is cut, but prompt data stays for `search_capabilities`. |

### 4.4 Tool Classes Removed from tools.py

1. `DetectCapabilityGapsTool` (intent.py)
2. `SuggestWorkflowTool` (intent.py)
3. `GetInstallationHistoryTool` (memory.py — module kept, tool removed)
4. `AnalyzeCapabilityStackTool` (capability_stack.py)
5. `ExecuteWorkflowTool` (orchestration.py)
6. `DiscoverPromptsTool` (skills.py)
7. `GenerateWorkflowSkillTool` (skills.py)
8. `RepoCatalogTool` (folded into `ListRepoSkillsTool` output)

**8 tool classes removed, 1 folded. Net: 39 → 31 tools.**

### 4.5 Models Removed from models.py

Remove Pydantic models only referenced by deleted modules (13 models total).
Verify each has no surviving references before deletion.

**From intent.py (deleted):**
- `MissingCapability`
- `CapabilityGapResult`
- `WorkflowStep`
- `WorkflowStepStatus` (enum)
- `WorkflowSuggestion`

**From capability_stack.py (deleted):**
- `CapabilityGap`
- `CapabilityStackReport`
- `CapabilityBundleItem`
- `CapabilityBundleResult`
- `CapabilityLayer` (enum)

**From orchestration.py (execute_workflow cut):**
- `WorkflowExecutionStep`
- `WorkflowExecutionResult`

**From skills.py (methods removed):**
- `GeneratedSkill`

**Models that survive** (used by surviving code):
- `InstallationRecord` — used by `memory.py` (kept)
- `TrustScore`, `FederatedSearchResult` — used by `registry.py` (kept, but
  `compute_trust_score` is replaced with a neutral default)
- `MCPPrompt` — used by surviving `search_capabilities` in `skills.py` and
  by `CapabilitySearchResult` model. Keep alive.

**Note:** `_KNOWN_SERVER_PROMPTS` dict in `skills.py` also survives — it is
used by the surviving `search_capabilities` method. Only `discover_prompts`
(the standalone tool) is cut.

## 5. Restructured Tool Surface

### Tier 1 — Sync & Bootstrap (5 tools)

The hero path. The reason someone installs meta-mcp.

| Tool | Description |
|------|-------------|
| `detect_clients` | Find all MCP clients installed on this machine |
| `sync_configurations` | Detect config drift and repair across all clients |
| `validate_config` | Check config for errors and missing credentials |
| `project_init` | Bootstrap `.mcp.json` from a profile YAML |
| `project_validate` | Health-check a project's MCP setup |

### Tier 2 — Skills & Repo (11 tools)

The distribution layer. How skills and co-located MCP servers are discovered,
searched, and installed.

| Tool | Description |
|------|-------------|
| `search_capabilities` | Unified search across servers + skills |
| `list_skills` | List installed skills (global + project + extra) |
| `install_skill` | Install from GitHub, registry, or local path |
| `uninstall_skill` | Remove an installed skill |
| `analyze_skill_trust` | Security scan before install |
| `list_repo_skills` | List skills in configured repo (includes catalog view) |
| `search_repo` | Search repo by intent |
| `install_from_repo` | Install skill + co-located MCP server |
| `batch_install_from_repo` | Install multiple at once |
| `list_repo_servers` | List repo's MCP servers |
| `add_skill_repo` | Add a repo to the search path |

### Tier 3 — Server Lifecycle (15 tools)

Discovery, installation, and runtime management of individual MCP servers.

| Tool | Description |
|------|-------------|
| `search_mcp_servers` | Natural language search |
| `get_server_info` | Detailed info and install options |
| `install_mcp_server` | Install with fallback chain |
| `list_installed_servers` | Show installed servers |
| `uninstall_mcp_server` | Remove and clean up |
| `search_federated` | Search across registries (plain aggregation) |
| `refresh_server_cache` | Refresh discovery cache |
| `get_manager_stats` | Ecosystem statistics |
| `analyze_project_context` | Detect stack, recommend servers |
| `install_workflow` | Batch install multiple servers |
| `check_ecosystem_health` | Probe all servers for health |
| `start_server` | Start a server process |
| `stop_server` | Stop a running server |
| `restart_server` | Restart a server |
| `discover_server_tools` | Connect and enumerate a server's tools/prompts/resources |

**Total: 5 + 11 + 15 = 31 tools.**

## 6. Profile YAML System

### 6.1 Motivation

`project_init.py` currently has hardcoded profile dicts tied to specific skill
repos (beacon, engram, rlm). This limits bootstrap to one person's setup.

Profile YAML files decouple profile definitions from the meta-mcp package.
Profiles live alongside skill repos, making them shareable and customizable.

### 6.2 Discovery Order

1. **Skill repo:** `<skill_repo>/profiles/*.yaml`
2. **Global:** `~/.config/meta-mcp/profiles/*.yaml`
3. **Built-in:** `src/meta_mcp/profiles/default.yaml` (ships with package)

First match wins. Skill repo profiles take priority so users can override
built-in defaults.

### 6.3 Profile Format

```yaml
# profiles/knowledge-stack.yaml
name: knowledge-stack
description: Full knowledge toolchain — docs, memory, code intelligence

skills:
  - beacon
  - engram
  - code-graph
  - rlm
  - expert-panel

servers:
  - name: beacon
    auto_install: true
  - name: engram
    auto_install: true

env_required:
  - ENGRAM_NEO4J_URI
  - ENGRAM_NEO4J_PASSWORD

post_install:
  - "Run beacon_garden() to verify docs are indexed"
```

### 6.4 Profile Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Profile identifier (matches filename without `.yaml`) |
| `description` | string | yes | Human-readable description |
| `skills` | list[str] | no | Skill names to install from repo |
| `servers` | list[object] | no | MCP servers to install. Each has `name` (required) and `auto_install` (default: false). |
| `env_required` | list[str] | no | Environment variables that must be set. Warn if missing, don't block. |
| `post_install` | list[str] | no | Messages to display after successful install. |

### 6.5 How project_init Changes

```
project_init(profile="knowledge-stack")
  │
  ├── 1. Find profile YAML (repo > global > built-in)
  ├── 2. Validate env_required — warn if missing, continue
  ├── 3. batch_install_from_repo(skills=[...])
  ├── 4. For each server with auto_install: install_from_repo(name)
  ├── 5. Write .mcp.json with server entries
  ├── 6. Display post_install messages
  └── 7. Return summary
```

### 6.6 Built-in Profile

```yaml
# src/meta_mcp/profiles/default.yaml
name: default
description: Minimal setup — registers meta-mcp only
skills: []
servers: []
env_required: []
post_install:
  - "Add profiles to your skill repo under profiles/*.yaml"
```

### 6.7 Error Handling

- **Malformed YAML:** Return clear error including file path and YAML parse
  error message. Do not fall through to the next profile in the discovery chain.
- **Profile not found:** Return error listing all searched locations (repo,
  global, built-in) so the user knows where to put the file.
- **Unknown skill names:** Passed through to `batch_install_from_repo`, which
  reports each unknown name as "not found" in its results. No pre-validation.
- **Missing required fields:** `name` and `description` are required. If absent,
  return a validation error naming the missing field(s) and file path.
- **Profile name collision:** First match wins (skill repo > global > built-in).
  No warning — this is intentional override behavior.
- **Validation model:** Use a Pydantic `ProfileConfig` model for validation
  rather than raw dict, consistent with the rest of the codebase.

### 6.8 Skill Integration: meta-mcp-repo Option 5

The `meta-mcp-repo` skill (installed at `~/.claude/skills/`) presents an
interactive menu including "Option 5: Configure MCP servers in .mcp.json".

With the profile YAML system, option 5 should:

1. Call `list_repo_skills` or scan `<skill_repo>/profiles/*.yaml` to discover
   available profiles.
2. Present profiles to the user (name + description).
3. Call `project_init(profile="<chosen>")` which handles the full install +
   config write flow.

This makes the skill a thin interactive wrapper around the `project_init` tool.
The skill handles UX (presenting choices), the tool handles execution (profile
loading, installing, writing `.mcp.json`).

**Skill update required:** The `meta-mcp-repo` SKILL.md in the skill repo
should be updated to reference profile-based `project_init` instead of manual
server-by-server config. This change lives in the skill repo, not in this
package.

## 7. Files Changed

### 7.1 Deleted

| File | Reason |
|------|--------|
| `src/meta_mcp/intent.py` | Module cut — NLU theater |
| `src/meta_mcp/capability_stack.py` | Module cut — audit without insight |

### 7.2 Modified

| File | Changes |
|------|---------|
| `server.py` | Remove imports/registrations for 8 cut tools. Reorganize remaining 31 with tier comments. |
| `tools.py` | Delete 8 tool classes. Remove dead imports (`IntentEngine`, `CapabilityStack`). **Keep** `ConversationalMemory` import (still used by surviving tools). Fold `RepoCatalogTool` output into `ListRepoSkillsTool`. |
| `orchestration.py` | Delete `execute_workflow` method, `_substitute_previous_output` function, and `_PREVIOUS_OUTPUT_TOKEN` constant. Keep server start/stop/restart/discover. |
| `registry.py` | Remove `compute_trust_score` function (module-level, line 446) and trust multiplier constants. Replace call site in `search_federated` with neutral default `TrustScore`. |
| `skills.py` | Remove `generate_workflow_skill` and `discover_prompts` methods. Keep `_KNOWN_SERVER_PROMPTS` (used by surviving `search_capabilities`). |
| `memory.py` | **Keep** module. Only remove `get_history()` method (backing the deleted `GetInstallationHistoryTool`). |
| `ai_fallback.py` | No changes needed (it imports `ConversationalMemory` from `memory.py` which survives). Verify import still resolves after memory.py changes. |
| `project_init.py` | Replace hardcoded profile dicts with YAML loader. Add profile discovery chain. |
| `models.py` | Remove 13 models (see section 4.5). Keep `InstallationRecord`, `TrustScore`, `FederatedSearchResult`, `MCPPrompt`. |
| `README.md` | Rewrite tool reference as 3 tiers. Update counts to 31. Update architecture listing. |

### 7.3 Added

| File | Purpose |
|------|---------|
| `src/meta_mcp/profiles/__init__.py` | `load_profile(name, extra_dirs) -> ProfileConfig` — profile discovery, YAML loading, Pydantic validation. |
| `src/meta_mcp/profiles/default.yaml` | Minimal built-in profile. |

### 7.4 Untouched

These files are not modified:

`_parsing.py`, `skill_repo.py`, `clients.py`, `config.py`, `discovery.py`,
`installer.py`, `verification.py`, `project.py`, `tools_base.py`, `settings.py`,
`cli.py`, `gateway.py`, `gateway_registry.py`

## 8. Test Impact

- Delete test files for removed modules (`test_intent.py`,
  `test_capability_stack.py` — if they exist).
- Update `test_tool_schema.py` to remove references to deleted tool classes
  and reflect 31-tool registration.
- Add `test_profiles.py` — test YAML loading, discovery order, missing env
  warnings, malformed YAML error, missing required fields, and the default
  profile.
- Existing tests for `clients.py`, `skills.py`, `installer.py` should pass
  without modification (verify, don't assume).

## 9. Migration & Backward Compatibility

- **No breaking changes to the MCP protocol interface.** Removed tools simply
  stop being advertised. Clients that never used them see no difference.
- **Config file (`config.toml`) is unchanged.** No settings removed.
- **`.mcp.json` format unchanged.** Projects using existing configs keep working.
- **`memory.py` stays as internal module.** Installation tracking continues to
  work for surviving tools.
- **`project_init` API change:** The `profile` parameter now expects a YAML
  profile name instead of a hardcoded enum. The `default` profile provides
  backward-compatible minimal behavior.

## 10. Success Criteria

1. `python -m meta_mcp --stdio` starts and advertises exactly 31 tools.
2. `detect_clients` and `sync_configurations` work unchanged.
3. `project_init(profile="default")` works with built-in YAML.
4. `project_init(profile="knowledge-stack")` works when the profile YAML exists
   in a configured skill repo.
5. All surviving tests pass.
6. `install_mcp_server` still records to `ConversationalMemory` (memory.py
   survived as internal module).
7. README accurately describes the 3-tier tool surface.
8. No imports of deleted modules (`intent`, `capability_stack`) remain anywhere
   in the codebase.
