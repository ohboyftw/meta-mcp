"""
Data models for Meta MCP Server.

Covers R1-R10: Intent resolution, configuration, verification, project context,
registry federation, multi-client, memory, orchestration, skills, and capability stack.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ─── Core Enums ───────────────────────────────────────────────────────────────

class MCPServerCategory(str, Enum):
    ORCHESTRATION = "orchestration"
    CONTEXT = "context"
    CODING = "coding"
    SEARCH = "search"
    AUTOMATION = "automation"
    VERSION_CONTROL = "version_control"
    DATABASE = "database"
    COMMUNICATION = "communication"
    MONITORING = "monitoring"
    SECURITY = "security"
    OTHER = "other"


class MCPServerStatus(str, Enum):
    AVAILABLE = "available"
    INSTALLED = "installed"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    UPDATING = "updating"
    UNKNOWN = "unknown"


class CapabilityLayer(str, Enum):
    """R10: Layers in the capability stack."""
    TOOLS = "tools"
    PROMPTS = "prompts"
    SKILLS = "skills"
    CONTEXT = "context"


class TrustLevel(str, Enum):
    OFFICIAL = "official"
    VERIFIED = "verified"
    COMMUNITY = "community"
    UNKNOWN = "unknown"


class ClientType(str, Enum):
    """R6: Supported MCP client types."""
    CLAUDE_DESKTOP = "claude_desktop"
    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    VSCODE = "vscode"
    WINDSURF = "windsurf"
    ZED = "zed"


class ClaudeCodeScope(str, Enum):
    """Scope for Claude Code MCP server registration.

    Claude Code has three separate scopes, each stored in a different file:
    - USER:    ~/.claude.json  (user-global)
    - PROJECT: .mcp.json       (project root)
    - LOCAL:   ~/.claude.json   (per-project override under ``projects.{path}.mcpServers``)
    """
    USER = "user"
    PROJECT = "project"
    LOCAL = "local"


class SkillScope(str, Enum):
    """R9: Skill installation scope."""
    GLOBAL = "global"
    PROJECT = "project"
    ENTERPRISE = "enterprise"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class WorkflowStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ─── Core Server Models ──────────────────────────────────────────────────────

class MCPServerInfo(BaseModel):
    name: str = Field(description="Server name")
    display_name: str = Field(description="Human-readable display name")
    description: str = Field(description="Server description")
    category: MCPServerCategory = Field(description="Server category")
    repository_url: Optional[str] = Field(None, description="Source repository URL")
    documentation_url: Optional[str] = Field(None, description="Documentation URL")
    version: Optional[str] = Field(None, description="Latest version")
    author: Optional[str] = Field(None, description="Author name")
    license: Optional[str] = Field(None, description="License type")
    keywords: List[str] = Field(default_factory=list, description="Search keywords")
    created_at: Optional[datetime] = Field(None, description="Creation date")
    updated_at: Optional[datetime] = Field(None, description="Last update date")
    stars: Optional[int] = Field(None, description="GitHub stars count")
    status: MCPServerStatus = Field(MCPServerStatus.AVAILABLE, description="Current status")


class MCPServerOption(BaseModel):
    name: str = Field(description="Option name")
    display_name: str = Field(description="Human-readable option name")
    description: Optional[str] = Field(None, description="Option description")
    install_command: str = Field(description="Installation command")
    config_name: str = Field(description="Configuration name for Claude")
    env_vars: List[str] = Field(default_factory=list, description="Required environment variables")
    repository_url: Optional[str] = Field(None, description="Specific repository for this option")
    recommended: bool = Field(False, description="Whether this is the recommended option")


class MCPServerWithOptions(MCPServerInfo):
    options: List[MCPServerOption] = Field(default_factory=list, description="Installation options")


class MCPSearchQuery(BaseModel):
    query: Optional[str] = Field(None, description="Search query text")
    category: Optional[MCPServerCategory] = Field(None, description="Filter by category")
    keywords: Optional[List[str]] = Field(None, description="Filter by keywords")
    sort_by: Optional[str] = Field("relevance", description="Sort order")
    limit: Optional[int] = Field(20, description="Maximum results to return")


class MCPSearchResult(BaseModel):
    query: MCPSearchQuery = Field(description="Original search query")
    total_count: int = Field(description="Total number of results")
    servers: List[MCPServerWithOptions] = Field(description="Found servers")
    search_time_ms: int = Field(description="Search execution time in milliseconds")


class MCPInstallationRequest(BaseModel):
    server_name: str = Field(description="Server name to install")
    option_name: str = Field(description="Installation option to use")
    env_vars: Optional[Dict[str, str]] = Field(None, description="Environment variables")
    auto_configure: bool = Field(True, description="Automatically update Claude configuration")
    target_clients: Optional[List[str]] = Field(None, description="R6: Target clients to configure")


class MCPInstallationResult(BaseModel):
    success: bool = Field(description="Whether installation succeeded")
    server_name: str = Field(description="Server name that was installed")
    option_name: str = Field(description="Installation option used")
    config_name: str = Field(description="Configuration name in Claude")
    message: str = Field(description="Installation message or error")
    installed_at: datetime = Field(default_factory=datetime.now, description="Installation timestamp")
    verification: Optional["VerificationResult"] = Field(None, description="R3: Post-install verification")


class MCPConfigEntry(BaseModel):
    """MCP server configuration entry.

    The ``type`` field is **required** by Claude Code (``~/.claude.json``) but
    is not used by Claude Desktop or most other clients.  When writing configs
    for Claude Code, callers must set ``type="stdio"`` (or the appropriate
    transport type).  For other clients the field should be omitted.
    """
    type: Optional[str] = Field(None, description="Transport type (required for Claude Code, e.g. 'stdio')")
    command: str = Field(description="Command to execute")
    args: List[str] = Field(default_factory=list, description="Command arguments")
    cwd: Optional[str] = Field(None, description="Working directory")
    env: Optional[Dict[str, str]] = Field(None, description="Environment variables")


class MCPConfiguration(BaseModel):
    mcpServers: Dict[str, MCPConfigEntry] = Field(default_factory=dict, description="Configured MCP servers")


class MCPServerHealth(BaseModel):
    is_running: bool = Field(description="Whether the server is running")
    response_time_ms: Optional[int] = Field(None, description="Response time in milliseconds")
    error_message: Optional[str] = Field(None, description="Error message if unhealthy")
    last_checked: datetime = Field(default_factory=datetime.now, description="Last health check time")


# ─── R1: Intent-Based Resolution Models ──────────────────────────────────────

class MissingCapability(BaseModel):
    capability: str = Field(description="Name of the missing capability")
    reason: str = Field(description="Why this capability is needed")
    servers: List[str] = Field(description="Servers that provide this capability")
    priority: str = Field("medium", description="Priority: high, medium, low")


class CapabilityGapResult(BaseModel):
    task_description: str = Field(description="Original task description")
    missing_capabilities: List[MissingCapability] = Field(description="Identified gaps")
    suggested_workflow: str = Field(description="Suggested workflow to fill gaps")
    currently_available: List[str] = Field(default_factory=list, description="Currently available capabilities")


class WorkflowStep(BaseModel):
    order: int = Field(description="Step order")
    server: str = Field(description="Server name")
    role: str = Field(description="Role in the workflow")
    required: bool = Field(True, description="Whether step is required")


class WorkflowSuggestion(BaseModel):
    workflow_name: str = Field(description="Name of the workflow")
    description: str = Field(description="Workflow description")
    steps: List[WorkflowStep] = Field(description="Ordered workflow steps")
    required_credentials: List[str] = Field(default_factory=list, description="Required credentials")
    estimated_setup_time: str = Field(description="Estimated setup time")


# ─── R2: Conversational Config Models ────────────────────────────────────────

class ConfigStep(BaseModel):
    key: str = Field(description="Configuration key")
    question: str = Field(description="Question to ask the user")
    help: str = Field(description="Help text with instructions")
    detection: Dict[str, Any] = Field(default_factory=dict, description="Auto-detection results")
    required: bool = Field(True, description="Whether this config is required")
    detected_value: Optional[str] = Field(None, description="Auto-detected value (masked)")


class ConfigConflict(BaseModel):
    conflict_type: str = Field(description="Type of conflict")
    existing: str = Field(description="Existing server/config")
    proposed: str = Field(description="Proposed server/config")
    capability: str = Field(description="Overlapping capability")
    recommendation: str = Field(description="Recommended resolution")


class ConversationalConfigResult(BaseModel):
    status: str = Field(description="installed, installed_pending_config, conflict")
    config_steps: List[ConfigStep] = Field(default_factory=list, description="Config steps needed")
    conflicts: List[ConfigConflict] = Field(default_factory=list, description="Detected conflicts")
    auto_detected: Dict[str, str] = Field(default_factory=dict, description="Auto-detected values")


# ─── R3: Verification Models ─────────────────────────────────────────────────

class SmokeTestResult(BaseModel):
    tool: str = Field(description="Tool tested")
    input_used: str = Field(description="Test input")
    result: str = Field(description="Test result: ok, error, timeout")
    latency_ms: Optional[int] = Field(None, description="Response latency")
    error: Optional[str] = Field(None, description="Error message if failed")


class VerificationResult(BaseModel):
    process_started: bool = Field(description="Whether server process started")
    mcp_handshake: bool = Field(description="Whether MCP handshake succeeded")
    tools_discovered: List[str] = Field(default_factory=list, description="Discovered tool names")
    smoke_test: Optional[SmokeTestResult] = Field(None, description="Smoke test result")
    verdict: str = Field(description="fully_operational, partially_working, failed")
    errors: List[str] = Field(default_factory=list, description="Errors encountered")


class ServerHealthReport(BaseModel):
    name: str = Field(description="Server name")
    status: HealthStatus = Field(description="Health status")
    latency_ms: Optional[int] = Field(None, description="Response latency")
    tools_count: Optional[int] = Field(None, description="Number of tools")
    error: Optional[str] = Field(None, description="Error message")
    suggestion: Optional[str] = Field(None, description="Fix suggestion")


class EcosystemHealthResult(BaseModel):
    servers: List[ServerHealthReport] = Field(description="Health of all servers")
    summary: Dict[str, int] = Field(description="Summary counts by status")
    checked_at: datetime = Field(default_factory=datetime.now)


# ─── R4: Project Context Models ──────────────────────────────────────────────

class ProjectContext(BaseModel):
    language: Optional[str] = Field(None, description="Primary language")
    framework: Optional[str] = Field(None, description="Primary framework")
    services: List[str] = Field(default_factory=list, description="Detected services")
    vcs: Optional[str] = Field(None, description="Version control system")
    ci_cd: Optional[str] = Field(None, description="CI/CD system")
    has_docker: bool = Field(False, description="Docker detected")
    has_mcp_config: bool = Field(False, description="Existing MCP config found")
    detected_env_vars: Dict[str, str] = Field(default_factory=dict, description="Detected env vars (masked)")
    project_root: Optional[str] = Field(None, description="Project root path")


class ContextualRecommendation(BaseModel):
    server: str = Field(description="Recommended server name")
    reason: str = Field(description="Why this server is recommended")
    priority: str = Field(description="high, medium, low")
    category: MCPServerCategory = Field(description="Server category")


class ProjectAnalysisResult(BaseModel):
    project: ProjectContext = Field(description="Detected project context")
    recommendations: List[ContextualRecommendation] = Field(description="Server recommendations")
    agents_md: Optional[str] = Field(None, description="AGENTS.md content if found")
    one_command_setup: str = Field(description="Summary action")


class BatchInstallResult(BaseModel):
    results: List[MCPInstallationResult] = Field(description="Individual results")
    pending_actions: List[Dict[str, str]] = Field(default_factory=list, description="Actions needing user input")
    summary: str = Field(description="Overall summary")


# ─── R5: Registry Federation Models ──────────────────────────────────────────

class RegistrySource(BaseModel):
    name: str = Field(description="Registry name")
    url: str = Field(description="Registry URL")
    server_count: Optional[int] = Field(None, description="Number of servers")
    last_queried: Optional[datetime] = Field(None, description="Last query time")
    available: bool = Field(True, description="Whether registry is reachable")


class TrustScore(BaseModel):
    score: int = Field(description="Trust score 0-100")
    level: TrustLevel = Field(description="Trust level")
    signals: Dict[str, Any] = Field(default_factory=dict, description="Individual trust signals")
    explanation: str = Field(description="Human-readable explanation")


class FederatedSearchResult(BaseModel):
    server: str = Field(description="Server name")
    sources: List[str] = Field(description="Registries where found")
    trust_score: TrustScore = Field(description="Trust score")
    confidence: str = Field(description="high, medium, low")


# ─── R6: Multi-Client Models ─────────────────────────────────────────────────

class DetectedClient(BaseModel):
    client_type: ClientType = Field(description="Client type")
    name: str = Field(description="Client display name")
    config_path: str = Field(description="Configuration file path")
    installed: bool = Field(description="Whether client is installed")
    configured_servers: List[str] = Field(default_factory=list, description="Servers in config")


class ConfigDrift(BaseModel):
    server: str = Field(description="Server name")
    status: Dict[str, str] = Field(description="Status per client: configured/missing")


class ConfigSyncResult(BaseModel):
    drift: List[ConfigDrift] = Field(description="Configuration drift detected")
    synced: int = Field(0, description="Number of configs synced")
    action: str = Field(description="Recommended action")


# ─── R7: Memory Models ───────────────────────────────────────────────────────

class InstallationRecord(BaseModel):
    server_name: str
    option_name: str
    project_path: Optional[str] = None
    installed_at: datetime = Field(default_factory=datetime.now)
    success: bool = True
    credentials_source: Optional[str] = None
    client_targets: List[str] = Field(default_factory=list)


class FailureRecord(BaseModel):
    server_name: str
    error_signature: str
    error_message: str
    system_state: Dict[str, Any] = Field(default_factory=dict)
    fix_applied: Optional[str] = None
    fixed: bool = False
    occurred_at: datetime = Field(default_factory=datetime.now)


class UserPreferences(BaseModel):
    preferred_install_method: Optional[str] = None  # npm, uvx
    preferred_clients: List[str] = Field(default_factory=list)
    common_server_combos: List[List[str]] = Field(default_factory=list)
    prefers_official: bool = True
    interaction_count: int = 0


class MemoryState(BaseModel):
    installations: List[InstallationRecord] = Field(default_factory=list)
    failures: List[FailureRecord] = Field(default_factory=list)
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    last_updated: datetime = Field(default_factory=datetime.now)


# ─── R8: Orchestration Models ────────────────────────────────────────────────

class ServerProcess(BaseModel):
    server_name: str = Field(description="Server name")
    pid: Optional[int] = Field(None, description="Process ID")
    status: MCPServerStatus = Field(description="Current status")
    started_at: Optional[datetime] = Field(None, description="Start time")
    command: str = Field(description="Command used to start")
    port: Optional[int] = Field(None, description="Port if applicable")


class DiscoveredTool(BaseModel):
    name: str = Field(description="Tool name")
    description: str = Field(description="Tool description")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parameter schema")


class ServerToolsResult(BaseModel):
    server: str = Field(description="Server name")
    tools: List[DiscoveredTool] = Field(description="Discovered tools")
    prompts: List[Dict[str, Any]] = Field(default_factory=list, description="Discovered prompts")
    resources: List[Dict[str, Any]] = Field(default_factory=list, description="Discovered resources")


class WorkflowExecutionStep(BaseModel):
    server: str = Field(description="Server name")
    tool: str = Field(description="Tool name")
    input: Dict[str, Any] = Field(description="Tool input")
    output: Optional[Any] = Field(None, description="Tool output")
    status: WorkflowStepStatus = Field(WorkflowStepStatus.PENDING)
    error: Optional[str] = None
    latency_ms: Optional[int] = None


class WorkflowExecutionResult(BaseModel):
    workflow_name: str = Field(description="Workflow name")
    steps: List[WorkflowExecutionStep] = Field(description="Execution steps")
    overall_status: str = Field(description="completed, partial, failed")
    total_time_ms: int = Field(description="Total execution time")


# ─── R9: Skills Models ───────────────────────────────────────────────────────

class AgentSkill(BaseModel):
    name: str = Field(description="Skill name")
    description: str = Field(description="Skill description")
    path: Optional[str] = Field(None, description="Local path to SKILL.md")
    source: str = Field("unknown", description="Source: anthropic_official, skillsmp, community, local")
    version: Optional[str] = Field(None, description="Skill version")
    auto_invocation: bool = Field(True, description="Whether skill auto-invokes")
    allowed_tools: List[str] = Field(default_factory=list, description="Tools the skill grants access to")
    scope: SkillScope = Field(SkillScope.PROJECT, description="Installation scope")
    required_servers: List[str] = Field(default_factory=list, description="MCP servers needed")
    tags: List[str] = Field(default_factory=list, description="Categorization tags")


class SkillSearchResult(BaseModel):
    name: str = Field(description="Skill name")
    skill_type: str = Field("skill", description="Type: skill")
    provides: str = Field(description="What the skill provides")
    source: str = Field(description="Source registry/repo")
    trust_score: Optional[int] = Field(None, description="Trust score 0-100")


class MCPPrompt(BaseModel):
    name: str = Field(description="Prompt name")
    description: str = Field(description="Prompt description")
    arguments: List[str] = Field(default_factory=list, description="Required arguments")
    server: str = Field(description="Server that exposes this prompt")


class CapabilitySearchResult(BaseModel):
    mcp_servers: List[Dict[str, Any]] = Field(default_factory=list, description="Matching MCP servers")
    agent_skills: List[SkillSearchResult] = Field(default_factory=list, description="Matching skills")
    mcp_prompts: List[MCPPrompt] = Field(default_factory=list, description="Matching prompts")
    recommendation: str = Field(description="Overall recommendation")


class SkillListResult(BaseModel):
    global_skills: List[AgentSkill] = Field(default_factory=list, description="Global skills")
    project_skills: List[AgentSkill] = Field(default_factory=list, description="Project skills")
    total: int = Field(description="Total skill count")
    auto_invocable: int = Field(description="Auto-invocable skill count")


class SkillTrustResult(BaseModel):
    skill_name: str
    trust_score: int = Field(description="0-100")
    warnings: List[str] = Field(default_factory=list)
    recommendation: str = Field(description="Recommendation")


class GeneratedSkill(BaseModel):
    name: str = Field(description="Generated skill name")
    path: str = Field(description="Path where SKILL.md was created")
    workflow_steps: List[str] = Field(description="Workflow steps encoded")
    required_servers: List[str] = Field(description="Required MCP servers")


# ─── R10: Capability Stack Models ────────────────────────────────────────────

class CapabilityGap(BaseModel):
    layer: CapabilityLayer = Field(description="Which layer has the gap")
    gap: str = Field(description="Description of the gap")
    fix: str = Field(description="How to fix it")
    priority: str = Field("medium", description="Priority")


class CapabilityStackReport(BaseModel):
    tools_layer: Dict[str, Any] = Field(description="MCP server status")
    prompts_layer: Dict[str, Any] = Field(description="MCP prompt status")
    skills_layer: Dict[str, Any] = Field(description="Agent skills status")
    context_layer: Dict[str, Any] = Field(description="Project context status")
    gaps: List[CapabilityGap] = Field(default_factory=list, description="Identified gaps")
    score: int = Field(description="Overall capability score 0-100")


class CapabilityBundleItem(BaseModel):
    item_type: str = Field(description="mcp_server, skill, prompt")
    name: str = Field(description="Item name")
    status: str = Field("pending", description="Installation status")
    message: Optional[str] = None


class CapabilityBundleResult(BaseModel):
    items: List[CapabilityBundleItem] = Field(description="Bundle items")
    overall_status: str = Field(description="Status of bundle install")
    summary: str = Field(description="Summary message")


# ─── AI Fallback Models ───────────────────────────────────────────────────────

class AIInstallationRequest(BaseModel):
    """Request for AI-assisted installation fallback."""
    server_name: str = Field(description="Name of the server that failed to install")
    reason: str = Field(description="Reason why standard installation failed")
    clients: List[str] = Field(default_factory=lambda: ["local_mcp_json"], description="Target MCP clients")
    suggested_command: Optional[str] = Field(None, description="AI-suggested installation command")
    suggested_integration: Optional[Dict[str, Any]] = Field(None, description="AI-suggested integration config")
    env_vars: Optional[Dict[str, str]] = Field(None, description="Required environment variables")
    user_approved: bool = Field(False, description="Whether user approved the suggestion")


class AIInstallationResult(BaseModel):
    """Result of an AI-assisted installation attempt."""
    success: bool = Field(description="Whether the AI-assisted installation succeeded")
    server_name: str = Field(description="Name of the server")
    method: str = Field("ai_fallback", description="Installation method used")
    command_executed: Optional[str] = Field(None, description="Command that was executed")
    integration_created: bool = Field(False, description="Whether integration config was created")
    message: str = Field(description="Result message")
    warnings: List[str] = Field(default_factory=list, description="Any warnings")


# ─── Project Init Models ─────────────────────────────────────────────────────

class ProjectServerDefinition(BaseModel):
    """Definition of a project-scoped MCP server."""
    name: str = Field(description="Server identifier (e.g. 'beacon')")
    description: str = Field(description="What this server does")
    command: str = Field(description="Command to run (e.g. 'py')")
    args: List[str] = Field(default_factory=list, description="Command arguments (may contain {templates})")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Environment variables (may contain {templates})")
    required_env_from_os: List[str] = Field(default_factory=list, description="API keys to resolve from os.environ")
    category: str = Field("knowledge", description="Server category")


class ProjectInitResult(BaseModel):
    """Result of project initialization."""
    servers_configured: List[str] = Field(default_factory=list, description="Servers written to .mcp.json")
    servers_skipped: List[str] = Field(default_factory=list, description="Servers skipped (already present)")
    missing_env_vars: Dict[str, List[str]] = Field(default_factory=dict, description="Server -> list of missing env vars")
    settings_updated: bool = Field(False, description="Whether .claude/settings.local.json was created/updated")
    pre_existing_servers: List[str] = Field(default_factory=list, description="Servers already in .mcp.json")
    warnings: List[str] = Field(default_factory=list, description="Any warnings")


class ProjectValidateResult(BaseModel):
    """Result of project validation."""
    has_mcp_json: bool = Field(False, description="Whether .mcp.json exists")
    has_settings_flag: bool = Field(False, description="Whether enableAllProjectMcpServers is set")
    healthy_servers: List[str] = Field(default_factory=list, description="Servers with valid config")
    unhealthy_servers: Dict[str, str] = Field(default_factory=dict, description="Server -> reason unhealthy")
    overall_healthy: bool = Field(False, description="Whether everything is healthy")


# Forward reference resolution
MCPInstallationResult.model_rebuild()
