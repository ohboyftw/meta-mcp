# Meta-MCP Scalpel Refactor — Design Spec

**Date:** 2026-03-22
**Status:** Draft
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
- Reduce tool count from 39 to 30

## 3. Target Audience

Primary: Aravind's own workflow — syncing 6+ MCP clients, bootstrapping skill
repos (beacon, engram, rlm, code-graph), managing a multi-agent development
setup. Dogfood-first, open-source second.

## 4. Cuts

### 4.1 Modules Removed Entirely

| Module | Tools Removed | Reason |
|--------|---------------|--------|
| `intent.py` | `detect_capability_gaps`, `suggest_workflow` | Keyword matching pretending to be NLU. No semantic understanding. Users know what they need. |
| `memory.py` | `get_installation_history` | Dict wrapper with no actual preference learning or pattern extraction. |
| `capability_stack.py` | `analyze_capability_stack` | Lists capabilities without cross-layer analysis. Audit without insight. |

### 4.2 Partial Cuts

| Module | Kept | Cut | Reason |
|--------|------|-----|--------|
| `orchestration.py` | `start_server`, `stop_server`, `restart_server`, `discover_server_tools` | `execute_workflow` + helpers (`_chain_results`, `_build_execution_plan`) | Server lifecycle is real. Workflow chaining is a stub — no state passing, no error handling, no rollback. |
| `registry.py` | `search_federated` (aggregation across 4 registries) | `_compute_trust_score` and trust multiplier constants | Aggregation is valuable. Arbitrary 30-point "official" vs 10-point "local" scoring is theater. |
| `skills.py` | All skill management (search, list, install, uninstall, trust) | `generate_workflow_skill`, `discover_prompts`, `_KNOWN_SERVER_PROMPTS` dict | Workflow-to-skill generation is half-baked. Prompt discovery is hardcoded patterns, not real MCP prompt enumeration. |
| `tools.py` | 30 surviving tool classes | 9 tool classes (see section 4.3) | Matches module cuts. |

### 4.3 Tool Classes Removed from tools.py

1. `DetectCapabilityGapsTool` (intent.py)
2. `SuggestWorkflowTool` (intent.py)
3. `GetInstallationHistoryTool` (memory.py)
4. `AnalyzeCapabilityStackTool` (capability_stack.py)
5. `ExecuteWorkflowTool` (orchestration.py)
6. `DiscoverPromptsTool` (skills.py)
7. `GenerateWorkflowSkillTool` (skills.py)
8. `RepoCatalogTool` (folded into `list_repo_skills` output)
9. `CheckEcosystemHealthTool` — **keep** (correction: this stays, it's real health checking)

**Revised cut: 8 tool classes removed. 1 tool (`repo_catalog`) folded into `list_repo_skills`. Net: 39 → 30 tools.**

### 4.4 Models Removed from models.py

Remove Pydantic models only referenced by deleted modules:
- `CapabilityGap`
- `WorkflowSuggestion`
- `InstallationHistoryEntry`
- `CapabilityStackResult`

Verify no surviving code references them before deletion.

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

### Tier 3 — Server Lifecycle (14 tools)

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

## 7. Files Changed

### 7.1 Deleted

| File | Reason |
|------|--------|
| `src/meta_mcp/intent.py` | Module cut |
| `src/meta_mcp/memory.py` | Module cut |
| `src/meta_mcp/capability_stack.py` | Module cut |

### 7.2 Modified

| File | Changes |
|------|---------|
| `server.py` | Remove imports/registrations for 8 cut tools. Reorganize remaining 30 with tier comments. |
| `tools.py` | Delete 8 tool classes. Remove dead imports (`IntentEngine`, `ConversationalMemory`, `CapabilityStack`, `ServerOrchestrator.execute_workflow`). Fold `RepoCatalogTool` output into `ListRepoSkillsTool`. |
| `orchestration.py` | Delete `execute_workflow` method and helpers. Keep server start/stop/restart/discover. |
| `registry.py` | Remove `_compute_trust_score` and trust multiplier constants. `search_federated` returns raw aggregated results. |
| `skills.py` | Remove `generate_workflow_skill`, `discover_prompts`, `_KNOWN_SERVER_PROMPTS`. |
| `project_init.py` | Replace hardcoded profile dicts with YAML loader. Add profile discovery chain. |
| `models.py` | Remove `CapabilityGap`, `WorkflowSuggestion`, `InstallationHistoryEntry`, `CapabilityStackResult`. |
| `README.md` | Rewrite tool reference as 3 tiers. Update counts. Update architecture listing. |

### 7.3 Added

| File | Purpose |
|------|---------|
| `src/meta_mcp/profiles/__init__.py` | `load_profile(name, extra_dirs) -> dict` — profile discovery and YAML loading. |
| `src/meta_mcp/profiles/default.yaml` | Minimal built-in profile. |

### 7.4 Untouched

These files are not modified:

`_parsing.py`, `skill_repo.py`, `clients.py`, `config.py`, `discovery.py`,
`installer.py`, `verification.py`, `project.py`, `tools_base.py`, `settings.py`,
`cli.py`

## 8. Test Impact

- Delete test files for removed modules (`test_intent.py`, `test_memory.py`,
  `test_capability_stack.py` — if they exist).
- Update `test_tools.py` to remove references to deleted tool classes.
- Update `test_server.py` to reflect the 30-tool registration.
- Add `test_profiles.py` — test YAML loading, discovery order, missing env
  warnings, and the default profile.
- Existing tests for `clients.py`, `skills.py`, `installer.py` should pass
  without modification (verify, don't assume).

## 9. Migration & Backward Compatibility

- **No breaking changes to the MCP protocol interface.** Removed tools simply
  stop being advertised. Clients that never used them see no difference.
- **Config file (`config.toml`) is unchanged.** No settings removed.
- **`.mcp.json` format unchanged.** Projects using existing configs keep working.
- **`project_init` API change:** The `profile` parameter now expects a YAML
  profile name instead of a hardcoded enum. The `default` profile provides
  backward-compatible minimal behavior.

## 10. Success Criteria

1. `python -m meta_mcp --stdio` starts and advertises exactly 30 tools.
2. `detect_clients` and `sync_configurations` work unchanged.
3. `project_init(profile="default")` works with built-in YAML.
4. `project_init(profile="knowledge-stack")` works when the profile YAML exists
   in a configured skill repo.
5. All surviving tests pass.
6. README accurately describes the 3-tier tool surface.
7. No imports of deleted modules remain anywhere in the codebase.
