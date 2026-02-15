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

## Architecture

```
src/meta_mcp/
  server.py        # FastMCP server — registers all 35 tools
  tools.py         # Tool implementations (Tool.apply() -> str)
  tools_base.py    # Base class with auto-naming and schema extraction
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
