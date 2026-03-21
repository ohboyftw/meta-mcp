<p align="center">
<pre>
                ___  ___     _          ___  ___ _____ ____
               |  \/  |    | |         |  \/  |/  __ \  _ \
               | .  . | ___| |_ __ _   | .  . || /  \/ |_) |
               | |\/| |/ _ \ __/ _` |  | |\/| || |   |  __/
               | |  | |  __/ || (_| |  | |  | || \__/\ |
               \_|  |_/\___|\__\__,_|  \_|  |_/ \____/_|
</pre>
</p>

<p align="center">
  <strong>Keep your MCP configuration in sync across all your AI tools,<br>and bootstrap project environments instantly.</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#why-meta-mcp">Why?</a> &bull;
  <a href="#tool-reference">Tools</a> &bull;
  <a href="#client-support">Clients</a> &bull;
  <a href="#configuration">Config</a> &bull;
  <a href="#architecture">Architecture</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/protocol-MCP-8A2BE2?style=flat-square" alt="MCP Protocol">
  <img src="https://img.shields.io/badge/tools-31-green?style=flat-square" alt="31 Tools">
  <img src="https://img.shields.io/badge/clients-6-orange?style=flat-square" alt="6 Clients">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square" alt="MIT License">
</p>

---

## Why Meta MCP?

Every MCP client manages servers independently. You configure Claude Code's `.mcp.json`, then separately configure Claude Desktop, then Cursor, then VS Code. New project? Copy-paste the same config. New teammate? Walk them through every server. Something breaks? Check six different config files.

**Meta MCP is the missing orchestration layer.** One MCP server that manages all your other MCP servers.

```
  Without Meta MCP                          With Meta MCP
  ────────────────                          ─────────────

  Claude Code ─── .mcp.json                You ──> Meta MCP
  Claude Desktop ─ config.json                      │
  Cursor ──────── mcp.json                          ├── Claude Code
  VS Code ─────── mcp.json                          ├── Claude Desktop
  Windsurf ────── mcp.json                          ├── Cursor
  Zed ─────────── settings.json                     ├── VS Code
                                                    ├── Windsurf
  6 files. All out of sync.                         └── Zed
  Every project, every machine.
                                            One source of truth.
                                            Always in sync.
```

### What it actually does

| Problem | Meta MCP Solution |
|---------|-------------------|
| Config drift across 6 clients | `sync_configurations` detects and repairs drift |
| New project setup takes 30 minutes | `project_init(profile="my-stack")` — one call, done |
| Finding the right MCP server | `search_mcp_servers("database")` — searches 4 registries at once |
| Installing servers is manual | `install_mcp_server("postgres")` — auto-detects install command |
| Skills scattered across machines | `batch_install_from_repo(["beacon", "engram"])` — repo as source of truth |
| "Works on my machine" for AI tools | Profile YAMLs are shareable, versioned, reproducible |

---

## Quick Start

### One-line install

**Windows (PowerShell):**
```powershell
.\scripts\install.ps1
```

**Linux / macOS / Git Bash:**
```bash
bash scripts/install.sh
```

Both scripts install meta-mcp, register it in `~/.claude.json`, and verify. Restart Claude Code after.

### Manual install

```bash
pip install -e .
claude mcp add -s user meta-mcp -- python -m meta_mcp --stdio
```

### First thing to try

After install, ask Claude:

> "Detect all MCP clients on my machine and check if their configs are in sync."

Meta MCP will scan for Claude Code, Claude Desktop, Cursor, VS Code, Windsurf, and Zed — then report what's installed and any config drift.

---

## How It Works

### 1. Sync your clients

```
detect_clients()
  → Found: Claude Code, Claude Desktop, Cursor

sync_configurations()
  → Claude Code: 5 servers configured
  → Claude Desktop: 3 servers configured (missing: postgres, github)
  → Cursor: 5 servers configured
  → Fixed: synced 2 missing servers to Claude Desktop
```

### 2. Bootstrap a project

Define a profile YAML in your skill repo:

```yaml
# profiles/knowledge-stack.yaml
name: knowledge-stack
description: Full knowledge toolchain

skills:
  - beacon
  - engram
  - code-graph

servers:
  - name: beacon
    auto_install: true
  - name: engram
    auto_install: true

env_required:
  - ENGRAM_NEO4J_URI
```

Then one call sets up the entire environment:

```
project_init(profile="knowledge-stack")
  → Installed 3 skills
  → Configured 2 MCP servers in .mcp.json
  → Warning: ENGRAM_NEO4J_URI not set
```

### 3. Discover and install servers

```
search_mcp_servers("I need to query a database")
  → postgres-mcp (Official Registry, recommended)
  → sqlite-mcp (Smithery)
  → supabase-mcp (mcp.so)

install_mcp_server("postgres-mcp")
  → Auto-detected: uvx postgres-mcp
  → Configured in .mcp.json
  → Health check: passing
```

---

## Tool Reference

31 tools across 3 tiers.

<details>
<summary><strong>Tier 1 &mdash; Sync & Bootstrap</strong> (5 tools) &mdash; the reason you install Meta MCP</summary>

| Tool | Description |
|------|-------------|
| `detect_clients` | Find all MCP clients installed on this machine |
| `sync_configurations` | Detect config drift and repair across all clients |
| `validate_config` | Check config for errors and missing credentials |
| `project_init` | Bootstrap `.mcp.json` from a profile YAML |
| `project_validate` | Health-check a project's MCP setup |

</details>

<details>
<summary><strong>Tier 2 &mdash; Skills & Repo</strong> (11 tools) &mdash; the distribution layer</summary>

| Tool | Description |
|------|-------------|
| `search_capabilities` | Unified search across servers + skills |
| `list_skills` | List installed skills (global + project + extra) |
| `install_skill` | Install from GitHub, registry, or local path |
| `uninstall_skill` | Remove an installed skill |
| `analyze_skill_trust` | Security scan before install |
| `list_repo_skills` | List skills in configured repo (includes catalog) |
| `search_repo` | Search repo skills + servers by intent |
| `install_from_repo` | Install skill + co-located MCP server |
| `batch_install_from_repo` | Install multiple skills at once |
| `list_repo_servers` | List MCP servers defined in the repo |
| `add_skill_repo` | Add a new skill repository to the search path |

</details>

<details>
<summary><strong>Tier 3 &mdash; Server Lifecycle</strong> (15 tools) &mdash; discovery, install, and runtime</summary>

| Tool | Description |
|------|-------------|
| `search_mcp_servers` | Natural language search across registries |
| `get_server_info` | Detailed info and install options |
| `install_mcp_server` | Install with 4-phase fallback chain |
| `list_installed_servers` | Show installed servers |
| `uninstall_mcp_server` | Remove and clean up |
| `search_federated` | Search Official Registry, Smithery, mcp.so |
| `refresh_server_cache` | Refresh discovery cache |
| `get_manager_stats` | Ecosystem statistics |
| `analyze_project_context` | Detect stack, recommend servers |
| `install_workflow` | Batch install multiple servers |
| `check_ecosystem_health` | Probe all servers for health |
| `start_server` | Start a server process |
| `stop_server` | Stop a running server |
| `restart_server` | Restart a server |
| `discover_server_tools` | Connect and enumerate a server's tools |

</details>

---

## Client Support

Meta MCP detects and writes configuration for 6 clients:

| Client | Config File | Notes |
|--------|-------------|-------|
| **Claude Code** | `~/.claude.json` / `.mcp.json` | Requires `"type": "stdio"` |
| **Claude Desktop** | `claude_desktop_config.json` | Platform-specific path |
| **Cursor** | `~/.cursor/mcp.json` | |
| **VS Code** | `~/.vscode/mcp.json` | Also checks workspace settings |
| **Windsurf** | `~/.windsurf/mcp.json` | Also checks `~/.codeium/windsurf/` |
| **Zed** | `~/.config/zed/settings.json` | Uses `context_servers` key |

---

## Configuration

### Config file

| Platform | Path |
|----------|------|
| Linux / macOS | `~/.config/meta-mcp/config.toml` |
| Windows | `%APPDATA%\meta-mcp\config.toml` |

```toml
[registry]
extra_dirs = ["~/my-servers", "~/team-servers"]

[skills]
extra_dirs = ["~/claudeSkills/repo"]

[github]
token = "ghp_..."

[install]
default_clients = ["claude_code"]
```

### Environment overrides

| Variable | Overrides | Format |
|----------|-----------|--------|
| `META_MCP_REGISTRY_DIRS` | `registry.extra_dirs` | Path-separator-delimited |
| `META_MCP_SKILLS_DIRS` | `skills.extra_dirs` | Path-separator-delimited |
| `GITHUB_TOKEN` | `github.token` | Token string |

### Transport modes

```bash
# Default: stdio (Claude Code / Claude Desktop)
claude mcp add -s user meta-mcp -- python -m meta_mcp --stdio

# HTTP/SSE for remote access
python -m meta_mcp --http

# Gateway mode: exposes all tools
python -m meta_mcp --stdio --gateway
```

---

## Skill Repository

Package skills + their MCP servers together. Distribute via git.

```
your-skill-repo/
  ├── profiles/
  │   └── knowledge-stack.yaml    # Bootstrap profiles
  ├── beacon/
  │   ├── SKILL.md                # Skill definition
  │   └── mcp_server.py           # Co-located server
  ├── code-graph/
  │   ├── SKILL.md
  │   └── mcp_server.py
  └── expert-panel/
      └── SKILL.md                # Skills without servers work too
```

```python
# Install one skill + its MCP server
install_from_repo(name="beacon")

# Install everything at once
batch_install_from_repo(names=["beacon", "code-graph", "expert-panel"])

# Search by what you need
search_repo(intent="code review")
```

When you call `install_from_repo("code-graph")`:
1. Locates `code-graph/SKILL.md` in the repo
2. Copies the skill to `.claude/skills/code-graph/`
3. Detects the co-located `mcp_server.py`
4. Writes the server config to `.mcp.json`

---

## Custom Skills

Skills are reusable SKILL.md files — workflows, procedures, and domain knowledge for your AI agent.

```markdown
---
name: my-skill
description: What this skill does
version: 1.0.0
tags: [automation, deployment]
required-servers: [github]
allowed-tools: [Bash, Read]
---

# My Skill

Instructions for Claude to follow when this skill is invoked...
```

| Scope | Location | Notes |
|-------|----------|-------|
| Global | `~/.claude/skills/` | Available in all projects |
| Project | `.claude/skills/` | Project-specific |
| Extra | Configured via `skills.extra_dirs` | Skill repositories |

---

## Architecture

```
src/meta_mcp/
  ├── server.py            FastMCP server entry point (31 tools)
  ├── tools.py             Tool implementations (Tool.apply() -> str)
  ├── tools_base.py        Base class with auto-naming and schema extraction
  │
  ├── _parsing.py          Shared SKILL.md parsing and name normalisation
  ├── models.py            Pydantic models
  ├── settings.py          Config file reader (TOML + env overrides)
  ├── cli.py               Click CLI entry point
  │
  ├── discovery.py         Server discovery and search
  ├── installer.py         Install / uninstall with fallback chains
  ├── config.py            Per-client config read / write / validate
  ├── registry.py          Federated registry search
  ├── memory.py            Installation tracking (internal)
  │
  ├── orchestration.py     Live server start / stop / restart
  ├── clients.py           Multi-client detection and drift sync
  ├── skills.py            Agent Skills management
  ├── skill_repo.py        Skill repository discovery and installation
  ├── profiles/            Profile YAML loader for project bootstrapping
  └── project_init.py      One-call project bootstrap
```

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v       # 256 tests
ruff check src/
mypy src/
```

## Requirements

- **Python 3.10+**
- `mcp`, `httpx`, `click`, `pydantic`, `aiohttp`, `GitPython`, `PyYAML`, `jinja2`

---

<p align="center">
  <sub>MIT License &bull; Built with <a href="https://modelcontextprotocol.io">Model Context Protocol</a></sub>
</p>
