# Meta MCP Server

An MCP server that manages other MCP servers. Discovers, installs, configures, and orchestrates MCP servers across multiple clients (Claude Code, Claude Desktop, Cursor, VS Code, Windsurf, Zed) from a single interface.

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

Both scripts will:
1. Install meta-mcp in editable mode (`pip install -e .`)
2. Register it as a user-level MCP server in `~/.claude.json`
3. Verify the installation works

Restart Claude Code after running.

### Manual install

```bash
# 1. Install the package
pip install -e .

# 2. Register with Claude Code (user scope)
claude mcp add -s user meta-mcp -- python -m meta_mcp --stdio
```

## What It Does

Meta MCP exposes 35 tools across 10 capability areas. Once registered, your AI assistant can use these tools to manage its own MCP ecosystem.

### Core — Server lifecycle

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

### Intent Resolution (R1)

| Tool | Description |
|------|-------------|
| `detect_capability_gaps` | Analyze a task and identify missing MCP servers |
| `suggest_workflow` | Generate a multi-server workflow plan for a goal |

### Verification (R3)

| Tool | Description |
|------|-------------|
| `check_ecosystem_health` | Probe all servers — status, latency, fix suggestions |

### Project Context (R4)

| Tool | Description |
|------|-------------|
| `analyze_project_context` | Detect language, framework, services; recommend servers |
| `install_workflow` | Batch install multiple servers in one flow |

### Registry Federation (R5)

| Tool | Description |
|------|-------------|
| `search_federated` | Search Official Registry, Smithery, mcp.so with trust scoring |

### Multi-Client Configuration (R6)

| Tool | Description |
|------|-------------|
| `detect_clients` | Find installed MCP clients on this machine |
| `sync_configurations` | Detect and repair config drift across clients |

### Memory (R7)

| Tool | Description |
|------|-------------|
| `get_installation_history` | Installation history and learned preferences |

### Live Orchestration (R8)

| Tool | Description |
|------|-------------|
| `start_server` | Start an MCP server process |
| `stop_server` | Stop a running server |
| `restart_server` | Restart a server |
| `discover_server_tools` | Connect and enumerate a server's tools/prompts/resources |
| `execute_workflow` | Chain tool calls across multiple servers |

### Agent Skills (R9)

| Tool | Description |
|------|-------------|
| `search_capabilities` | Unified search across servers, skills, and prompts |
| `list_skills` | List installed Agent Skills (global + project) |
| `install_skill` | Install a skill from GitHub, registry, or local path |
| `uninstall_skill` | Remove an installed skill |
| `generate_workflow_skill` | Package a workflow as a reusable SKILL.md |
| `analyze_skill_trust` | Security analysis: prompt injection, broad permissions |
| `discover_prompts` | Surface MCP Prompts from configured servers |

### Capability Stack (R10)

| Tool | Description |
|------|-------------|
| `analyze_capability_stack` | Audit all 4 layers (Tools, Prompts, Skills, Context) |

### Project Init

| Tool | Description |
|------|-------------|
| `project_init` | Bootstrap a project's `.mcp.json` in one call |
| `project_validate` | Validate a project's MCP setup health |

## Client Support

Meta MCP can detect and write configuration for:

| Client | Config file | Notes |
|--------|------------|-------|
| Claude Code | `~/.claude.json` (user) / `.mcp.json` (project) | Requires `"type": "stdio"` |
| Claude Desktop | `claude_desktop_config.json` | Platform-specific path |
| Cursor | `~/.cursor/mcp.json` | |
| VS Code | `~/.vscode/mcp.json` | Also checks workspace |
| Windsurf | `~/.windsurf/mcp.json` | Also checks `~/.codeium/windsurf/` |
| Zed | `~/.config/zed/settings.json` | Uses `context_servers` key |

Use `detect_clients` to see what's installed, and `sync_configurations` to keep them in lockstep.

## Configuration

Meta MCP reads settings from a TOML config file, with environment variable overrides for backward compatibility.

### Config file location

| Platform | Path |
|----------|------|
| Linux / macOS | `~/.config/meta-mcp/config.toml` |
| Windows | `%APPDATA%\meta-mcp\config.toml` |

The install scripts create a default config file automatically. You can also create one manually.

### Config file reference

```toml
# ~/.config/meta-mcp/config.toml

[registry]
# Extra directories containing server definitions (.mcp.json, servers.json, or per-server .json)
extra_dirs = ["~/my-servers", "~/team-servers"]

[skills]
# Extra directories containing SKILL.md skill folders
extra_dirs = ["~/claudeSkills/Repo"]

[github]
# GitHub token for higher API rate limits during discovery
token = "ghp_..."

[install]
# Default target clients for install_mcp_server
default_clients = ["claude_code"]
```

### Environment variable overrides

Environment variables take priority over the config file when set:

| Env var | Overrides | Format |
|---------|-----------|--------|
| `META_MCP_REGISTRY_DIRS` | `registry.extra_dirs` | Path-separator-delimited list (`;` on Windows, `:` on POSIX) |
| `META_MCP_SKILLS_DIRS` | `skills.extra_dirs` | Path-separator-delimited list |
| `GITHUB_TOKEN` | `github.token` | Token string |
| `CLAUDE_SKILLS_REPO` | First entry of `skills.extra_dirs` (used by `project_init`) | Single path |

### Transport modes

| Flag | Description |
|------|-------------|
| `--stdio` | (Default) Stdio transport for Claude Code / Claude Desktop |
| `--http` | HTTP/SSE transport for remote or multi-client access |
| `--gateway` | Gateway mode — exposes all 35 tools |

Example registration (user scope):
```bash
claude mcp add -s user meta-mcp -- python -m meta_mcp --stdio --gateway
```

## Extending the Registry

Meta MCP discovers servers from online registries (Official MCP Registry, Smithery, mcp.so) **and** from local directories you configure.

### Adding a local server catalog

1. Set `registry.extra_dirs` in your config file (or `META_MCP_REGISTRY_DIRS` env var) to include your directory.

2. Place server definitions in that directory using any of these formats:

**Option A — `.mcp.json` or `servers.json` (mcpServers format):**
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

**Option B — Standalone per-server JSON files (`my-server.json`):**
```json
{
  "name": "my-server",
  "description": "My custom MCP server",
  "repository_url": "https://github.com/me/my-server",
  "install_command": "uvx my-server"
}
```

3. Run `search_mcp_servers` — your servers will appear in results.

### Auto-detect install

When `install_mcp_server` is called for a server with no predefined recipe:

1. **Repository auto-detect** — if the server has a `repository_url`, meta-mcp checks the GitHub repo for `pyproject.toml` or `package.json` to infer `uvx` or `npx` commands.
2. **AI fallback** — searches npm, PyPI, and GitHub for matching packages.
3. **Ask the user** — if nothing works, returns a message asking for the manual install command.

## Custom Skills

Skills are reusable SKILL.md files that encode workflows, procedures, and domain knowledge for Claude Code.

### Skill directories

| Scope | Location | Notes |
|-------|----------|-------|
| Global | `~/.claude/skills/` | Available in all projects |
| Project | `.claude/skills/` (relative to project root) | Project-specific |
| Extra | Configured via `skills.extra_dirs` or `META_MCP_SKILLS_DIRS` | Additional directories |

### SKILL.md format

Each skill lives in its own directory with a `SKILL.md` file:

```
my-skill/
  SKILL.md
  helper-script.py   # optional supporting files
```

The `SKILL.md` uses YAML frontmatter:

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

### Frontmatter fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Skill identifier |
| `description` | string | Human-readable description |
| `version` | string | Semver version |
| `disable-model-invocation` | bool | If true, skill won't be auto-invoked |
| `allowed-tools` | list | Tools this skill may use |
| `tags` | list | Searchable tags |
| `required-servers` | list | MCP servers this skill depends on |

## Architecture

```
src/meta_mcp/
  server.py        # FastMCP server — registers all 35 tools
  tools.py         # Tool implementations (Tool.apply() -> str)
  tools_base.py    # Base class with auto-naming and schema extraction
  settings.py      # Central config file reader (~/.config/meta-mcp/config.toml)
  installer.py     # Install/uninstall with fallback chains + AI fallback
  config.py        # Per-client config read/write/validate
  clients.py       # Multi-client detection, drift sync (R6)
  discovery.py     # Server discovery and search
  intent.py        # Intent-based capability resolution (R1)
  verification.py  # Post-install smoke testing (R3)
  project.py       # Project context analysis (R4)
  registry.py      # Federated registry search (R5)
  memory.py        # Installation history and preferences (R7)
  orchestration.py # Live server management (R8)
  skills.py        # Agent Skills management (R9)
  capability_stack.py # 4-layer capability audit (R10)
  project_init.py  # One-call project bootstrap
  models.py        # All Pydantic models
  cli.py           # Click CLI entry point
```

Tools use `apply() -> str` — FastMCP handles MCP protocol wrapping.

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

- Python 3.10+
- Dependencies: `mcp`, `httpx`, `click`, `pydantic`, `aiohttp`, `GitPython`, `PyYAML`, `jinja2`

## License

MIT
