# Meta-MCP v2: Disruptive Requirements Specification

## The Thesis

Every competing tool in the MCP management space — MCPM.sh, mcp-installer, Smithery, MetaMCP, MCP Hub — shares one fatal assumption: **a human is driving**. They build CLIs for terminals, GUIs for browsers, dashboards for monitoring. They are tools *for people who manage MCP servers*.

Meta-MCP rejects this assumption.

Meta-MCP is the only tool where **the AI is the operator**. It is an MCP server consumed by an LLM, not a human. This means the LLM can autonomously reason about what capabilities it lacks, find servers that provide them, install and configure them, verify they work, and compose them into workflows — all within a single conversation, without the user ever touching a terminal.

**The disruptive position: Meta-MCP is the AI's self-improvement runtime.** It transforms the LLM from a static tool-user into an agent that dynamically expands its own capabilities on demand.

No CLI can do this. No registry can do this. No dashboard can do this. Only an MCP-native conversational tool can.

---

## Core Design Principles

### 1. Intent Over Inventory

Users don't think in server names. They think in problems:
- "I need to research competitors" (not "install brave-search")
- "Help me monitor my PostgreSQL database" (not "install server-postgres")
- "I want to automate browser testing" (not "install playwright")

Meta-MCP must translate **intent into capability** through conversation, not through catalog browsing.

### 2. Zero-Configuration by Default

If the AI can infer it, the user shouldn't have to say it. API keys are the only thing a user should ever need to provide — and even then, Meta-MCP should detect existing keys from environment, `.env` files, and credential stores before asking.

### 3. Verify, Don't Trust

Every installation must be verified through an actual tool call, not just a successful `npm install`. Meta-MCP should confirm a server works before declaring success.

### 4. Compose, Don't Just Install

The real value isn't "install server X." It's "give me the capability to do Y," where Y requires orchestrating multiple servers together. Meta-MCP should think in workflows, not packages.

### 5. Conversational Memory

Meta-MCP should learn from the user's patterns. If they always work with Python projects and PostgreSQL, it should proactively suggest relevant servers. If an installation failed last time, it should remember why and avoid the same path.

---

## Requirements

### R1: Intent-Based Capability Resolution

**The Problem:**
Current tools require users to know what MCP server they want by name. This is like requiring someone to know the npm package name before they can describe what they need.

**The Requirement:**

#### R1.1 — Natural Language Capability Matching
The `search_mcp_servers` tool must accept freeform natural language intents and return ranked results based on **capability matching**, not just keyword search.

| User Says | Current Behavior | Required Behavior |
|-----------|-----------------|-------------------|
| "I need to scrape websites" | Searches for "scrape" in names/descriptions | Returns Firecrawl, Puppeteer, Playwright ranked by fit, with explanation of trade-offs ("Firecrawl handles JS-rendered pages; Puppeteer gives you full browser control; Playwright is best for testing workflows") |
| "Help me work with my GitHub repos" | Returns GitHub server | Returns GitHub server + suggests git-related servers + detects if user has `GITHUB_PERSONAL_ACCESS_TOKEN` already set |
| "I need memory across conversations" | No results | Returns Basic Memory, any knowledge-graph servers, with explanation of persistence models |

#### R1.2 — Capability Gap Detection
New tool: `detect_capability_gaps`

When invoked (or invoked automatically by the LLM), this tool analyzes the user's **current request context** and identifies which MCP servers would help fulfill it. The LLM calls this when it realizes it cannot complete a task with its current tools.

```
Input: { "task_description": "Research the top 5 competitors to Notion and create a comparison spreadsheet" }
Output: {
  "missing_capabilities": [
    { "capability": "web_search", "reason": "Need to research competitors", "servers": ["brave-search", "perplexity"] },
    { "capability": "web_scraping", "reason": "Need to extract feature data from competitor sites", "servers": ["firecrawl", "puppeteer"] },
    { "capability": "spreadsheet", "reason": "Need to create comparison spreadsheet", "servers": ["google-sheets-mcp", "excel-mcp"] }
  ],
  "suggested_workflow": "Install brave-search for research, firecrawl for data extraction, google-sheets for output"
}
```

#### R1.3 — Multi-Server Workflow Suggestion
New tool: `suggest_workflow`

Given a high-level goal, returns a complete **workflow plan** — which servers to install, in what order, and how they chain together.

```
Input: { "goal": "Set up a full CI/CD monitoring pipeline for my GitHub project" }
Output: {
  "workflow_name": "CI/CD Monitoring Pipeline",
  "steps": [
    { "order": 1, "server": "github", "role": "Source: monitor repo events, PRs, issues" },
    { "order": 2, "server": "brave-search", "role": "Research: look up error messages and solutions" },
    { "order": 3, "server": "slack-mcp", "role": "Notify: send alerts to team channel" }
  ],
  "estimated_setup_time": "3 minutes",
  "required_credentials": ["GITHUB_PERSONAL_ACCESS_TOKEN", "SLACK_BOT_TOKEN"]
}
```

---

### R2: Conversational Configuration Wizard

**The Problem:**
Current tools either silently use defaults or dump a wall of configuration options. Neither approach works when an AI is mediating the interaction.

**The Requirement:**

#### R2.1 — Progressive Disclosure Configuration
When installing a server, Meta-MCP must return structured configuration questions that the LLM presents conversationally to the user. Configuration happens through dialogue, not forms.

```
# Instead of:
"Server installed. Set BRAVE_API_KEY in your environment."

# Meta-MCP returns:
{
  "status": "installed_pending_config",
  "config_steps": [
    {
      "key": "BRAVE_API_KEY",
      "question": "Brave Search requires an API key. Do you have one?",
      "help": "You can get a free key at https://brave.com/search/api/. The free tier includes 2,000 queries/month.",
      "detection": { "checked_env": true, "checked_dotenv": true, "found": false },
      "required": true
    }
  ]
}
```

#### R2.2 — Credential Detection
Before asking for credentials, Meta-MCP must check:
1. Environment variables (current shell)
2. `.env` files (current directory and parents)
3. Common credential stores (`~/.config/`, `~/.aws/`, keychain)
4. Previously configured MCP servers (reuse tokens)

If credentials are found, report them (masked) and ask for confirmation rather than re-entry.

#### R2.3 — Configuration Conflict Detection
Before installing, check for conflicts:
- Port collisions with already-configured servers
- Duplicate capabilities (user already has a search server)
- Incompatible versions or runtimes
- Missing runtime prerequisites (with auto-install offer)

Return conflicts as structured data the LLM can present as a decision to the user:
```
{
  "conflicts": [
    {
      "type": "duplicate_capability",
      "existing": "brave-search",
      "proposed": "perplexity",
      "capability": "web_search",
      "recommendation": "Both can coexist. Brave is free-tier friendly. Perplexity gives deeper answers. Install both?"
    }
  ]
}
```

---

### R3: Post-Install Verification Loop

**The Problem:**
Current tools declare success after `npm install` exits 0. But "installed" does not mean "working." Servers can fail to start, misconfigure, or lack required permissions.

**The Requirement:**

#### R3.1 — Smoke Test on Install
After installation and configuration, Meta-MCP must verify the server actually works by:
1. Attempting to start the server process
2. Sending a basic MCP `initialize` handshake
3. Listing available tools from the server
4. Running one simple tool call if possible

Return verification results:
```
{
  "install_status": "success",
  "verification": {
    "process_started": true,
    "mcp_handshake": true,
    "tools_discovered": ["brave_web_search", "brave_local_search"],
    "smoke_test": { "tool": "brave_web_search", "input": "test", "result": "ok", "latency_ms": 450 },
    "verdict": "fully_operational"
  }
}
```

#### R3.2 — Self-Healing on Failure
If verification fails, Meta-MCP should attempt automatic remediation before reporting failure:
1. Check if the error is a known issue (missing dependency, wrong Node version, permission error)
2. Attempt fix (install dependency, suggest nvm, fix permissions)
3. Re-verify
4. If still failing, return structured diagnostic info the LLM can use to help the user debug

#### R3.3 — Health Dashboard Tool
New tool: `check_ecosystem_health`

Returns the health status of ALL configured MCP servers, not just Meta-MCP-installed ones. Reads the active `.mcp.json` or Claude Desktop config and probes each server.

```
Output: {
  "servers": [
    { "name": "brave-search", "status": "healthy", "latency_ms": 200, "tools": 2 },
    { "name": "github", "status": "unhealthy", "error": "GITHUB_PERSONAL_ACCESS_TOKEN expired", "suggestion": "Regenerate token at github.com/settings/tokens" },
    { "name": "filesystem", "status": "healthy", "latency_ms": 50, "tools": 11 }
  ],
  "summary": { "healthy": 2, "unhealthy": 1, "total": 3 }
}
```

---

### R4: Project Context Awareness

**The Problem:**
Current tools are context-blind. They don't know what project the user is working on, what language it uses, what services it connects to, or what tools would be most relevant.

**The Requirement:**

#### R4.1 — Project Introspection
New tool: `analyze_project_context`

Scans the current working directory to understand the project:
- Language/framework detection (package.json, pyproject.toml, Cargo.toml, go.mod)
- Service dependencies (docker-compose.yml, .env files with DB/API references)
- Existing MCP configuration (.mcp.json)
- CI/CD setup (.github/workflows, .gitlab-ci.yml)
- Version control provider (GitHub, GitLab, Bitbucket)

#### R4.2 — Contextual Recommendations
Based on project analysis, proactively suggest relevant MCP servers:

```
{
  "project": { "language": "python", "framework": "fastapi", "services": ["postgresql", "redis"], "vcs": "github" },
  "recommendations": [
    { "server": "github", "reason": "Your project uses GitHub. This server enables PR management, issue tracking, and code review.", "priority": "high" },
    { "server": "server-postgres", "reason": "Detected PostgreSQL in docker-compose.yml. This server enables direct database queries.", "priority": "high" },
    { "server": "serena", "reason": "Python project detected. Serena provides semantic code navigation and refactoring.", "priority": "medium" },
    { "server": "context7", "reason": "FastAPI framework detected. Context7 provides up-to-date framework documentation.", "priority": "medium" }
  ],
  "one_command_setup": "Install all high-priority recommendations?"
}
```

#### R4.3 — Batch Installation
New tool: `install_workflow`

Accepts a list of servers and installs them all in sequence, handling dependencies, credential collection, and verification as a single conversational flow rather than N separate interactions.

```
Input: { "servers": ["github", "server-postgres", "serena"], "auto_detect_credentials": true }
Output: {
  "results": [
    { "server": "github", "status": "installed_verified", "credentials": "detected_from_env" },
    { "server": "server-postgres", "status": "installed_pending_config", "needs": ["DATABASE_URL"] },
    { "server": "serena", "status": "installed_verified", "credentials": "none_required" }
  ],
  "pending_actions": [{ "server": "server-postgres", "action": "Provide DATABASE_URL from your docker-compose.yml" }]
}
```

---

### R5: Registry Federation

**The Problem:**
Meta-MCP currently scrapes GitHub and hardcodes ~15 servers. The ecosystem has 17,000+ servers across Smithery, mcp.so, PulseMCP, and the Official MCP Registry. Scraping is fragile. Hardcoding is stale.

**The Requirement:**

#### R5.1 — Official MCP Registry Integration
Query the Official MCP Registry API (`registry.modelcontextprotocol.io`) as the primary discovery source. Fall back to GitHub scraping only when the registry is unavailable.

#### R5.2 — Smithery API Integration
Query the Smithery.ai API as a secondary discovery source. Smithery has 7,300+ tools with quality ratings, security scans, and usage data.

#### R5.3 — Federated Search
When the user searches, Meta-MCP queries ALL sources in parallel and merges results with deduplication. Each result carries a provenance tag:
```
{ "server": "brave-search", "sources": ["official_registry", "smithery", "curated"], "confidence": "high" }
{ "server": "obscure-tool", "sources": ["github_search"], "confidence": "low" }
```

#### R5.4 — Trust Scoring
Each discovered server gets a trust score based on:
- Source (official registry > smithery > awesome-list > github search)
- GitHub stars and activity
- Security scan results (from Smithery/Glama if available)
- Community reviews
- Whether it appears in multiple sources

The LLM uses trust scores to make install recommendations:
```
"I found 3 PostgreSQL MCP servers. server-postgres (trust: 95/100, official) is the recommended choice.
pg-mcp (trust: 60/100, community) has more features but less vetting.
postgres-ai-mcp (trust: 30/100, github-only) is new and unverified."
```

---

### R6: Multi-Client Configuration

**The Problem:**
Meta-MCP only writes to `.mcp.json` and Claude Desktop config. Users work across Claude Code, Cursor, VS Code Copilot, Windsurf, Codex, and more. Each has a different config format and location.

**The Requirement:**

#### R6.1 — Client Detection
Detect which MCP-capable clients are installed on the system:
- Claude Desktop (`~/Library/Application Support/Claude/`)
- Claude Code (`.mcp.json` in project root)
- Cursor (`~/.cursor/mcp.json`)
- VS Code / Copilot (`~/.vscode/mcp.json` or workspace settings)
- Windsurf (`~/.windsurf/mcp.json`)
- Zed (settings.json `context_servers` section)

#### R6.2 — Cross-Client Configuration
New tool parameter: `target_clients`

```
Input: { "server": "brave-search", "target_clients": ["claude-code", "cursor", "vscode"] }
```

Writes the correct configuration format for each client. If `target_clients` is omitted, configure all detected clients.

#### R6.3 — Configuration Sync
New tool: `sync_configurations`

Detects configuration drift between clients and offers to synchronize:
```
{
  "drift": [
    { "server": "github", "claude_code": "configured", "cursor": "missing", "vscode": "missing" },
    { "server": "brave-search", "claude_code": "configured", "cursor": "configured", "vscode": "missing" }
  ],
  "action": "Sync all servers to all detected clients?"
}
```

---

### R7: Conversational Memory and Learning

**The Problem:**
Every interaction with Meta-MCP starts from zero. The tool doesn't remember what was installed, what failed, what the user prefers, or what their project needs.

**The Requirement:**

#### R7.1 — Installation History
Persist a structured history of all Meta-MCP interactions:
- What was installed, when, and for which project
- What failed and why
- What the user preferred when given choices
- What credentials were used (references, not values)

#### R7.2 — Failure Memory
When an installation fails, record the failure signature (error message, system state, server version). On future attempts, check failure memory first:
```
"Note: Installing puppeteer failed on this system 3 days ago due to missing Chromium.
The fix was running 'npx puppeteer install chromium'. Apply this fix automatically?"
```

#### R7.3 — User Preference Learning
Track patterns in user behavior:
- Preferred installation method (npm vs uvx)
- Preferred client targets
- Common server combinations
- Whether they prefer official or enhanced/community variants

Use preferences to set smarter defaults:
```
"Based on your history, you prefer uvx installations and always configure for both Claude Code and Cursor. Using these defaults."
```

---

### R8: Live Server Orchestration

**The Problem:**
Current Meta-MCP only manages server *configurations*. It doesn't interact with running servers, can't restart them, and can't verify they're actually responding.

**The Requirement:**

#### R8.1 — Process Lifecycle Management
New tools: `start_server`, `stop_server`, `restart_server`

For stdio-based servers, Meta-MCP should be able to spawn, monitor, and terminate server processes. This is critical for the verification loop (R3) and health checks.

#### R8.2 — Live Tool Discovery
New tool: `discover_server_tools`

Connect to a running MCP server and list its available tools with schemas:
```
{
  "server": "brave-search",
  "tools": [
    { "name": "brave_web_search", "description": "Search the web", "parameters": { "query": "string", "count": "integer" } },
    { "name": "brave_local_search", "description": "Search local businesses", "parameters": { "query": "string", "location": "string" } }
  ]
}
```

This lets the LLM understand what a newly installed server can do and explain it to the user.

#### R8.3 — Cross-Server Workflow Execution
New tool: `execute_workflow`

Chain tool calls across multiple MCP servers in a defined sequence:
```
Input: {
  "workflow": [
    { "server": "brave-search", "tool": "brave_web_search", "input": { "query": "top Notion competitors 2025" } },
    { "server": "firecrawl", "tool": "scrape", "input": { "urls": "$previous.results[0:3].url" } },
    { "server": "google-sheets", "tool": "create_spreadsheet", "input": { "data": "$previous.content" } }
  ]
}
```

This is the highest-value feature: the LLM orchestrates a multi-server pipeline through a single Meta-MCP call.

---

### R9: Agent Skills and Capability Stack Management

**The Problem:**
MCP servers provide **tools** — atomic operations like "search the web" or "query a database." But tools alone don't make an agent capable. Real capability requires **procedural knowledge** (how to use tools effectively), **workflow patterns** (how to chain tools together), and **project context** (how to behave in a specific codebase). Today these layers are managed separately or not at all:

- **MCP Servers** = tools (managed by Meta-MCP, mcp-installer, etc.)
- **Agent Skills (SKILL.md)** = procedural knowledge (manually installed to `~/.claude/skills/`)
- **MCP Prompts** = workflow templates (almost universally ignored by every tool)
- **AGENTS.md** = project context (manually written, never managed)

No tool manages the full stack. Meta-MCP should.

**The Landscape:**

The Agent Skills standard (SKILL.md) was released by Anthropic in December 2025 as an open standard, now adopted by Claude Code, OpenAI Codex CLI, Cursor, VS Code/GitHub Copilot, and others. Marketplaces have emerged: SkillsMP (66,000+ skills), SkillHub (7,000+ skills), Anthropic's official skills repo, and CCPM (Claude Code Plugin Manager). MCP Prompts — a first-class MCP protocol primitive for reusable prompt templates — remain almost entirely unused by existing tools despite being well-specified. The Agentic AI Foundation (AAIF), formed December 2025 under the Linux Foundation by Anthropic, Block, and OpenAI, now governs MCP, A2A, and AGENTS.md as complementary standards.

**The Opportunity:**

Meta-MCP becomes the **unified capability manager** — not just for tools (MCP servers) but for the entire capability stack: tools + skills + prompts + project context.

#### R9.1 — Federated Skill Discovery
Extend the discovery engine (R5) to search Agent Skills marketplaces alongside MCP server registries. When a user expresses an intent, return BOTH relevant MCP servers and relevant Agent Skills, ranked together.

New tool: `search_capabilities`

```
Input: { "intent": "I need to do code reviews" }
Output: {
  "mcp_servers": [
    { "name": "github", "type": "tool", "provides": "PR access, diff viewing, commenting" }
  ],
  "agent_skills": [
    { "name": "anthropics/skills/code-review", "type": "skill", "provides": "Structured code review procedure with security checklist", "source": "anthropic_official" },
    { "name": "engineering-workflow-plugin", "type": "skill", "provides": "Full engineering workflow including review, testing, deployment", "source": "skillsmp" }
  ],
  "mcp_prompts": [
    { "name": "github/review-pr", "type": "prompt", "provides": "Pre-built prompt template for PR review with embedded diff context", "source": "github_mcp_server" }
  ],
  "recommendation": "Install github MCP server for PR access + code-review skill for review procedure. The github server also exposes a review-pr prompt that chains them together."
}
```

Sources to federate:
- Anthropic's official skills repo (`github.com/anthropics/skills`)
- SkillsMP API (`skillsmp.com`)
- SkillHub (`skillhub.club`)
- CCPM registry (`github.com/daymade/claude-code-skills`)
- MCP server prompt manifests (discovered from installed servers)

#### R9.2 — Skill + Server Bundling
When installing an MCP server, automatically discover and suggest complementary Agent Skills. When installing a skill, detect if it requires MCP servers that aren't installed and offer to install them.

```
# User installs an MCP server
install_mcp_server("server-postgres")
→ "Installed server-postgres. I also found 2 skills that work well with it:
    - 'database-query-optimization' — Teaches the agent how to write efficient queries
    - 'schema-migration-review' — Procedure for reviewing database migrations safely
    Install these skills too?"

# User installs a skill
install_skill("code-review")
→ "The code-review skill references GitHub PR tools. You don't have the github MCP server installed.
    Install it now? (requires GITHUB_PERSONAL_ACCESS_TOKEN)"
```

New tool: `install_capability_bundle`

Accepts a mix of MCP servers and Agent Skills and installs them as a cohesive unit:
```
Input: {
  "bundle": [
    { "type": "mcp_server", "name": "github" },
    { "type": "skill", "name": "anthropics/skills/code-review" },
    { "type": "skill", "name": "engineering-workflow-plugin" }
  ],
  "auto_detect_credentials": true
}
```

#### R9.3 — MCP Prompt Surfacing
Most MCP clients (including Claude Code) ignore the Prompts primitive that MCP servers expose. Meta-MCP should be the first tool to systematically discover, catalog, and surface these.

New tool: `discover_prompts`

Connects to all configured MCP servers and lists their available prompts alongside their tools:
```
Output: {
  "servers_with_prompts": [
    {
      "server": "github",
      "prompts": [
        { "name": "review-pr", "description": "Review a pull request with embedded diff", "arguments": ["pr_number", "repo"] },
        { "name": "create-issue", "description": "Create a well-structured issue from a bug description", "arguments": ["description"] }
      ],
      "tools": ["get_pr", "list_issues", "create_comment", "..."]
    }
  ],
  "summary": "3 of 7 configured servers expose prompts. Most clients ignore these — Meta-MCP surfaces them for you."
}
```

The LLM can then use these prompts as pre-built workflows, combining them with direct tool calls for complex tasks.

#### R9.4 — Workflow-to-Skill Generation
After the user completes a multi-server workflow through Meta-MCP (R8.3), offer to **package that workflow as a reusable Agent Skill**.

```
# After user completes: brave-search → firecrawl → google-sheets pipeline
"You just ran a competitive research workflow across 3 servers. Want me to save this as a reusable skill?

I'll generate a SKILL.md at .claude/skills/competitive-research/SKILL.md that:
- Describes the workflow so the agent auto-invokes it for similar requests
- Encodes the server chain: brave-search → firecrawl → google-sheets
- Includes the prompt patterns you used
- Lists required MCP servers as prerequisites (with auto-install via Meta-MCP)"
```

Generated skill structure:
```
.claude/skills/competitive-research/
├── SKILL.md          # Frontmatter + procedure instructions
├── workflow.yaml     # Server chain definition (mcpn-compatible)
└── templates/
    └── comparison.csv  # Output template
```

This creates a **flywheel**: the more you use Meta-MCP, the more skills it generates, the more capable the agent becomes, the more workflows it runs, the more skills it generates.

#### R9.5 — Skill Lifecycle Management
Manage installed Agent Skills with the same rigor as MCP servers:

New tools: `list_skills`, `install_skill`, `uninstall_skill`, `update_skills`

```
list_skills() → {
  "global_skills": [
    { "name": "code-review", "path": "~/.claude/skills/code-review", "source": "anthropic_official", "version": "1.2.0", "auto_invocation": true }
  ],
  "project_skills": [
    { "name": "competitive-research", "path": ".claude/skills/competitive-research", "source": "meta-mcp-generated", "version": "local", "auto_invocation": true },
    { "name": "deploy-to-staging", "path": ".claude/skills/deploy-to-staging", "source": "team-shared", "version": "0.3.0", "auto_invocation": false }
  ],
  "total": 3,
  "auto_invocable": 2
}
```

Key lifecycle operations:
- **Install** from marketplace URL, GitHub repo, or local path
- **Update** skills to latest version from source
- **Audit** which skills are auto-invocable (security review)
- **Scope** skills to project vs. global vs. enterprise level
- **Dependency check** — verify required MCP servers are installed

#### R9.6 — AGENTS.md Integration
Detect and respect the project's `AGENTS.md` file. Use it to inform capability recommendations:

```
# If AGENTS.md says: "This project uses PostgreSQL and deploys to AWS"
analyze_project_context() → also parses AGENTS.md → recommends:
  - server-postgres MCP server
  - aws-mcp MCP server
  - "database-migration" skill
  - "aws-deployment" skill
```

When Meta-MCP installs MCP servers for a project, offer to add relevant guidance to the project's `AGENTS.md`:
```
"I installed server-postgres and the database-migration skill for this project.
Should I add a section to AGENTS.md documenting the available database tools and
the approved migration procedure? This ensures all agents working on this project
know these capabilities exist."
```

#### R9.7 — Trust and Security Scoring for Skills
Extend the trust scoring system (R5.4) to Agent Skills. Skills are a significant security surface — a malicious skill loaded into an agent's context can manipulate its behavior.

Trust signals for skills:
- **Source verification**: Official (Anthropic/partner) > marketplace-reviewed > community > unknown
- **Permission scope**: Does the skill request `allowed-tools`? Which tools? Why?
- **Auto-invocation risk**: Skills with `disable-model-invocation: false` are higher risk
- **Content analysis**: Flag skills that contain prompt injection patterns or suspicious instructions
- **Community signals**: Download count, ratings, report history from marketplaces

```
install_skill("suspicious-helper") → {
  "trust_score": 25,
  "warnings": [
    "This skill requests allowed-tools: [Bash] with no restrictions",
    "Auto-invocation is enabled — it will load into context automatically",
    "Source: unknown GitHub user with 2 followers, repo created 3 days ago",
    "Content analysis: contains instructions to ignore previous system prompts"
  ],
  "recommendation": "DO NOT INSTALL. This skill has characteristics consistent with prompt injection attacks."
}
```

---

### R10: The Capability Stack Model

**The Unifying Abstraction:**

Meta-MCP's data model should evolve from "MCP servers" to a **capability stack** that treats tools, skills, prompts, and project context as layers of a unified system:

```
┌─────────────────────────────────────────────┐
│  Layer 4: Project Context (AGENTS.md)       │  "How should agents behave HERE?"
├─────────────────────────────────────────────┤
│  Layer 3: Agent Skills (SKILL.md)           │  "HOW to accomplish tasks"
├─────────────────────────────────────────────┤
│  Layer 2: MCP Prompts                       │  "Pre-built workflow templates"
├─────────────────────────────────────────────┤
│  Layer 1: MCP Servers (Tools)               │  "WHAT tools are available"
└─────────────────────────────────────────────┘
```

Every Meta-MCP operation — search, install, verify, compose — should work across all four layers. The `detect_capability_gaps` tool (R1.2) should identify gaps at any layer:

```
{
  "gaps": [
    { "layer": "tools", "gap": "No database access", "fix": "Install server-postgres" },
    { "layer": "skills", "gap": "No code review procedure", "fix": "Install anthropics/skills/code-review" },
    { "layer": "prompts", "gap": "GitHub server has unused review-pr prompt", "fix": "Surface it to the agent" },
    { "layer": "context", "gap": "AGENTS.md doesn't mention available database tools", "fix": "Update AGENTS.md" }
  ]
}
```

This positions Meta-MCP not as a package manager for MCP servers, but as the **operating system for agent capabilities** — the layer that makes everything above it discoverable, installable, verifiable, and composable.

---

## Non-Requirements (What Meta-MCP Should NOT Do)

1. **Should NOT become a proxy/gateway** — MetaMCP (metatool-ai) already does this well. Meta-MCP aggregates, it doesn't proxy.
2. **Should NOT build a web GUI** — The AI IS the interface. A dashboard would betray the thesis.
3. **Should NOT host servers** — Smithery does this. Meta-MCP is local-first.
4. **Should NOT replace the Official Registry** — It should be the best *client* of the registry, not a competing registry.
5. **Should NOT require an account or subscription** — Zero-friction, fully local, fully open.

---

## Priority Tiers

### Tier 1 — The Differentiators (Build First)
These features make Meta-MCP categorically different from every competitor:

| Requirement | Why It's Disruptive |
|-------------|-------------------|
| R1.1 Intent-Based Matching | No other tool translates "I need to..." into server recommendations |
| R1.2 Capability Gap Detection | The AI identifies its own missing capabilities — no other tool enables this |
| R2.1 Conversational Config | Configuration through dialogue, not forms or flags |
| R3.1 Smoke Test on Install | "Installed and verified" vs. just "installed" |
| R4.1-R4.2 Project Context | Recommendations based on YOUR project, not a generic catalog |
| R9.1 Federated Skill Discovery | The only tool that searches MCP servers AND Agent Skills AND MCP Prompts together |
| R10 Capability Stack Model | No tool thinks in layers — everyone else manages one thing. Meta-MCP manages the full stack. |

### Tier 2 — The Force Multipliers (Build Next)
These features make Meta-MCP dramatically more useful:

| Requirement | Why It Matters |
|-------------|---------------|
| R5.1-R5.3 Registry Federation | Access 17,000+ servers instead of 15 hardcoded ones |
| R5.4 Trust Scoring | Help the AI make safe recommendations |
| R6.1-R6.2 Multi-Client | Install once, configure everywhere |
| R3.3 Health Dashboard | The only tool that probes ALL your MCP servers |
| R4.3 Batch Installation | One conversation to set up an entire workflow |
| R9.2 Skill + Server Bundling | Install a server, get the skill that teaches the AI how to use it well |
| R9.3 MCP Prompt Surfacing | Unlock the most ignored MCP primitive — first-mover advantage |
| R9.5 Skill Lifecycle | Full CRUD for skills, not just servers — unified management |

### Tier 3 — The Moat (Build for Defensibility)
These features create long-term competitive advantage:

| Requirement | Why It's a Moat |
|-------------|----------------|
| R7.1-R7.3 Memory and Learning | Gets better the more you use it — network effect of one |
| R8.1-R8.3 Live Orchestration | Cross-server workflows are what no CLI or registry can offer |
| R1.3 Workflow Suggestion | The AI becomes a solutions architect, not a package manager |
| R3.2 Self-Healing | The tool that fixes itself |
| R6.3 Config Sync | Lock-in through convenience |
| R9.4 Workflow-to-Skill Generation | Every workflow becomes a reusable skill — compounding flywheel |
| R9.7 Trust Scoring for Skills | Critical security gap no one else fills — skills are an attack surface |
| R9.6 AGENTS.md Integration | Cements Meta-MCP as the project-level capability manager |

---

## Competitive Positioning After Implementation

| Tool | What It Is | What Meta-MCP Becomes |
|------|-----------|----------------------|
| **mcp-installer** | "Install this package" | "What do you need? Let me figure out the servers, skills, prompts, and project config — install, configure, and verify everything." |
| **MCPM.sh** | Human-operated CLI package manager | AI-operated capability expansion runtime across the full stack |
| **Smithery** | Hosted registry with web UI | The best local client of Smithery's API, plus intent-matching + project awareness |
| **MetaMCP** | Server aggregation proxy | Complementary — Meta-MCP manages what MetaMCP proxies |
| **MCP Hub** | Runtime monitoring dashboard | Conversational monitoring with self-healing |
| **SkillsMP / SkillHub** | Skill marketplace websites | Federated skill discovery integrated with server discovery — AI-operated, not browser-operated |
| **CCPM** | CLI skill installer | Full lifecycle management (install, update, audit, generate) with MCP server bundling |
| **CrewAI / LangGraph** | Agent orchestration frameworks | Meta-MCP provides the dynamic capability expansion layer these frameworks lack |

**The one-line pitch:** Meta-MCP is the operating system for agent capabilities — tools, skills, prompts, and project context, managed as one stack.

---

## Success Metrics

### Core Metrics
1. **Time-to-capability**: From user expressing a need to having a verified, working capability. Target: <60 seconds for curated servers/skills, <3 minutes for discovered ones.
2. **Zero-touch installs**: Percentage of installations requiring zero user input beyond the initial intent. Target: >50% for capabilities with no required API keys.
3. **First-try success rate**: Percentage of installations that pass smoke test on first attempt. Target: >80%.
4. **Discovery coverage**: Percentage of mcp.so-listed servers discoverable through Meta-MCP. Target: >90% through registry federation.
5. **Conversation turns**: Average turns from "I need X" to "X is working." Target: <4 turns.

### Capability Stack Metrics
6. **Skill bundling rate**: Percentage of server installs that include a relevant skill suggestion. Target: >60%.
7. **Prompt surfacing**: Percentage of installed MCP servers whose prompts are discovered and cataloged. Target: >90%.
8. **Workflow-to-skill conversion**: Number of completed multi-server workflows converted to reusable skills. Target: >1 per active user per week.
9. **Cross-layer gap detection**: Percentage of `detect_capability_gaps` calls that identify gaps across 2+ layers (tools, skills, prompts, context). Target: >40%.
10. **Trust score coverage**: Percentage of recommended skills with a computed trust score. Target: 100% for auto-invocable skills.
