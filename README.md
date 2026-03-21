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
  <strong>The MCP server that manages all your other MCP servers.</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#features">Features</a> &bull;
  <a href="#tool-reference">Tool Reference</a> &bull;
  <a href="#client-support">Client Support</a> &bull;
  <a href="#configuration">Configuration</a> &bull;
  <a href="#architecture">Architecture</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/protocol-MCP-8A2BE2?style=flat-square" alt="MCP Protocol">
  <img src="https://img.shields.io/badge/tools-39-green?style=flat-square" alt="39 Tools">
  <img src="https://img.shields.io/badge/clients-6-orange?style=flat-square" alt="6 Clients">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square" alt="MIT License">
</p>

---

Meta MCP is a single MCP server that discovers, installs, configures, and orchestrates your entire MCP ecosystem. Register it once — your AI assistant handles the rest.

```
  You                          Meta MCP                        Your MCP Servers
  ───                          ────────                        ───────────────
   │                              │                                  │
   │  "I need a database tool"    │                                  │
   │─────────────────────────────>│                                  │
   │                              │──> Search registries             │
   │                              │──> Find best match               │
   │                              │──> Install & configure ─────────>│
   │                              │──> Verify health ───────────────>│
   │                              │<── All systems go ───────────────│
   │  "Done. postgres-mcp ready"  │                                  │
   │<─────────────────────────────│                                  │
```

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

Both scripts install meta-mcp in editable mode, register it as a user-level MCP server in `~/.claude.json`, and verify the installation. Restart Claude Code after running.

### Manual install

```bash
pip install -e .
claude mcp add -s user meta-mcp -- python -m meta_mcp --stdio
```

---

## Features

### Discover & Install

Search across the Official MCP Registry, Smithery, mcp.so, and your own local catalogs. Install with auto-detected commands, fallback chains, and zero manual config.

### Multi-Client Sync

Detect all MCP clients on your machine — Claude Code, Claude Desktop, Cursor, VS Code, Windsurf, Zed — and keep their configurations in lockstep.

### Live Orchestration

Start, stop, restart, and health-check running MCP servers. Chain tool calls across multiple servers in executable workflows.

### Agent Skills

Discover, install, and manage reusable SKILL.md files that encode workflows, procedures, and domain knowledge. Trust-score skills before installation.

### Skill Repository

Bootstrap entire development environments from a local skill repo. One call installs skills and their co-located MCP servers together.

### Capability Stack Audit

Audit all four layers of your agent's capabilities — Tools, Prompts, Skills, and Context — in a single view. Find gaps before they become blockers.

---

## Tool Reference

39 tools across 11 capability areas.

<details>
<summary><strong>Core &mdash; Server Lifecycle</strong> (8 tools)</summary>

| Tool | Description |
|------|-------------|
| `search_mcp_servers` | Natural language search across available servers |
| `get_server_info` | Detailed info: install options, credentials, docs |
| `install_mcp_server` | Install with fallback strategies and auto-configuration |
| `list_installed_servers` | Show installed servers and their status |
| `uninstall_mcp_server` | Remove a server and clean up config |
| `validate_config` | Check configuration for errors and missing credentials |
| `get_manager_stats` | Ecosystem statistics |
| `refresh_server_cache` | Refresh the discovery cache |

</details>

<details>
<summary><strong>Intent Resolution</strong> (2 tools)</summary>

| Tool | Description |
|------|-------------|
| `detect_capability_gaps` | Analyze a task and identify missing MCP servers |
| `suggest_workflow` | Generate a multi-server workflow plan for a goal |

</details>

<details>
<summary><strong>Verification</strong> (1 tool)</summary>

| Tool | Description |
|------|-------------|
| `check_ecosystem_health` | Probe all servers — status, latency, fix suggestions |

</details>

<details>
<summary><strong>Project Context</strong> (2 tools)</summary>

| Tool | Description |
|------|-------------|
| `analyze_project_context` | Detect language, framework, services; recommend servers |
| `install_workflow` | Batch install multiple servers in one flow |

</details>

<details>
<summary><strong>Registry Federation</strong> (1 tool)</summary>

| Tool | Description |
|------|-------------|
| `search_federated` | Search Official Registry, Smithery, mcp.so with trust scoring |

</details>

<details>
<summary><strong>Multi-Client Configuration</strong> (2 tools)</summary>

| Tool | Description |
|------|-------------|
| `detect_clients` | Find installed MCP clients on this machine |
| `sync_configurations` | Detect and repair config drift across clients |

</details>

<details>
<summary><strong>Memory</strong> (1 tool)</summary>

| Tool | Description |
|------|-------------|
| `get_installation_history` | Installation history and learned preferences |

</details>

<details>
<summary><strong>Live Orchestration</strong> (5 tools)</summary>

| Tool | Description |
|------|-------------|
| `start_server` | Start an MCP server process |
| `stop_server` | Stop a running server |
| `restart_server` | Restart a server |
| `discover_server_tools` | Connect and enumerate a server's tools/prompts/resources |
| `execute_workflow` | Chain tool calls across multiple servers |

</details>

<details>
<summary><strong>Agent Skills</strong> (7 tools)</summary>

| Tool | Description |
|------|-------------|
| `search_capabilities` | Unified search across servers, skills, and prompts |
| `list_skills` | List installed Agent Skills (global + project) |
| `install_skill` | Install a skill from GitHub, registry, or local path |
| `uninstall_skill` | Remove an installed skill |
| `generate_workflow_skill` | Package a workflow as a reusable SKILL.md |
| `analyze_skill_trust` | Security analysis: prompt injection, broad permissions |
| `discover_prompts` | Surface MCP Prompts from configured servers |

</details>

<details>
<summary><strong>Skill Repository</strong> (7 tools)</summary>

| Tool | Description |
|------|-------------|
| `list_repo_skills` | List all skills in the repository |
| `search_repo` | Search skills + servers by intent |
| `install_from_repo` | Install a skill and its co-located MCP server |
| `batch_install_from_repo` | Install multiple skills at once |
| `list_repo_servers` | List MCP servers defined in the repo |
| `add_skill_repo` | Add a new skill repository to the search path |
| `repo_catalog` | Full catalog of all repos, skills, and servers |

</details>

<details>
<summary><strong>Project Init & Capability Stack</strong> (3 tools)</summary>

| Tool | Description |
|------|-------------|
| `project_init` | Bootstrap a project's `.mcp.json` in one call |
| `project_validate` | Validate a project's MCP setup health |
| `analyze_capability_stack` | Audit all 4 layers (Tools, Prompts, Skills, Context) |

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

Use `detect_clients` to see what's installed, and `sync_configurations` to keep them in lockstep.

---

## Configuration

Meta MCP reads settings from a TOML config file with environment variable overrides.

### Config file location

| Platform | Path |
|----------|------|
| Linux / macOS | `~/.config/meta-mcp/config.toml` |
| Windows | `%APPDATA%\meta-mcp\config.toml` |

The install scripts create a default config file automatically.

### Reference

```toml
# ~/.config/meta-mcp/config.toml

[registry]
extra_dirs = ["~/my-servers", "~/team-servers"]

[skills]
extra_dirs = ["~/claudeSkills/repo"]

[github]
token = "ghp_..."

[install]
default_clients = ["claude_code"]
```

### Environment variable overrides

| Variable | Overrides | Format |
|----------|-----------|--------|
| `META_MCP_REGISTRY_DIRS` | `registry.extra_dirs` | Path-separator-delimited |
| `META_MCP_SKILLS_DIRS` | `skills.extra_dirs` | Path-separator-delimited |
| `GITHUB_TOKEN` | `github.token` | Token string |
| `CLAUDE_SKILLS_REPO` | First entry of `skills.extra_dirs` | Single path |

### Transport modes

| Flag | Description |
|------|-------------|
| `--stdio` | (Default) Stdio transport for Claude Code / Claude Desktop |
| `--http` | HTTP/SSE transport for remote or multi-client access |
| `--gateway` | Gateway mode — exposes all tools |

```bash
claude mcp add -s user meta-mcp -- python -m meta_mcp --stdio --gateway
```

---

## Skill Repository

Bootstrap an entire development environment from a local skill repo. Skills and their co-located MCP servers are discovered and installed together.

### Repository structure

```
your-skill-repo/
  ├── servers.json              # Optional: standalone MCP server definitions
  ├── beacon/
  │   ├── SKILL.md              # Skill definition (YAML frontmatter + instructions)
  │   └── mcp_server.py         # Co-located MCP server (auto-discovered)
  ├── code-graph/
  │   ├── SKILL.md
  │   └── mcp_server.py
  └── expert-panel/
      └── SKILL.md              # Skills without servers work too
```

### Configure

```toml
# config.toml
[skills]
extra_dirs = ["/path/to/your-skill-repo"]
```

### Usage

```python
# Install one skill + its MCP server
install_from_repo(name="beacon")

# Install a full stack at once
batch_install_from_repo(names=["beacon", "code-graph", "expert-panel"])

# Search by intent
search_repo(intent="code review")
```

### How it works

When you call `install_from_repo("code-graph")`:

1. Locates `code-graph/SKILL.md` in the repo
2. Copies the skill to `.claude/skills/code-graph/`
3. Detects the co-located `mcp_server.py`
4. Infers the run command and writes it to `.mcp.json`
5. The skill and server are ready to use immediately

---

## Extending the Registry

Meta MCP discovers servers from online registries **and** from local directories you configure.

### Adding a local server catalog

Set `registry.extra_dirs` in your config file, then place server definitions in any of these formats:

**mcpServers format** (`.mcp.json` or `servers.json`):
```json
{
  "mcpServers": {
    "my-server": {
      "command": "uvx",
      "args": ["my-server"],
      "description": "My custom MCP server"
    }
  }
}
```

**Standalone per-server** (`my-server.json`):
```json
{
  "name": "my-server",
  "description": "My custom MCP server",
  "repository_url": "https://github.com/me/my-server",
  "install_command": "uvx my-server"
}
```

### Auto-detect install

When `install_mcp_server` is called for a server with no predefined recipe:

1. **Repository auto-detect** — checks the GitHub repo for `pyproject.toml` or `package.json` to infer `uvx` or `npx` commands
2. **AI fallback** — searches npm, PyPI, and GitHub for matching packages
3. **Ask the user** — if nothing works, prompts for the manual install command

---

## Custom Skills

Skills are reusable SKILL.md files that encode workflows, procedures, and domain knowledge.

### Skill directories

| Scope | Location | Notes |
|-------|----------|-------|
| Global | `~/.claude/skills/` | Available in all projects |
| Project | `.claude/skills/` | Project-specific |
| Extra | Configured via `skills.extra_dirs` | Additional repositories |

### SKILL.md format

```markdown
---
name: my-skill
description: What this skill does
version: 1.0.0
disable-model-invocation: false
allowed-tools:
  - Bash
  - Read
tags:
  - automation
  - deployment
required-servers:
  - github
---

# My Skill

Instructions for Claude to follow when this skill is invoked...
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Skill identifier |
| `description` | string | Human-readable description |
| `version` | string | Semver version |
| `disable-model-invocation` | bool | If `true`, skill won't be auto-invoked |
| `allowed-tools` | list | Tools this skill may use |
| `tags` | list | Searchable tags |
| `required-servers` | list | MCP servers this skill depends on |

---

## Architecture

```
src/meta_mcp/
  ├── server.py            FastMCP server entry point
  ├── tools.py             39 tool implementations (Tool.apply() -> str)
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
  ├── intent.py            Intent-based capability resolution
  ├── verification.py      Post-install health checking
  ├── project.py           Project context analysis
  ├── registry.py          Federated registry search
  ├── memory.py            Installation history and preferences
  │
  ├── orchestration.py     Live server start / stop / restart
  ├── clients.py           Multi-client detection and drift sync
  ├── skills.py            Agent Skills management
  ├── skill_repo.py        Skill repository discovery and installation
  ├── capability_stack.py  4-layer capability audit
  └── project_init.py      One-call project bootstrap
```

Tools implement `apply() -> str`. FastMCP handles MCP protocol wrapping.

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/

# Type check
mypy src/
```

## Requirements

- **Python 3.10+**
- **Dependencies:** `mcp`, `httpx`, `click`, `pydantic`, `aiohttp`, `GitPython`, `PyYAML`, `jinja2`

---

<p align="center">
  <sub>MIT License &bull; Built with <a href="https://modelcontextprotocol.io">Model Context Protocol</a></sub>
</p>
