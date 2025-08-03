"""
Data models for Meta MCP Server.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, HttpUrl


class MCPServerCategory(str, Enum):
    """Categories for MCP servers."""

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


class MCPInstallationScope(str, Enum):
    """Installation scope levels for MCP servers."""

    GLOBAL = "global"  # System-wide installation (available to all users/projects)
    USER = (
        "user"  # User-specific installation (available to all projects for this user)
    )
    PROJECT = (
        "project"  # Project-specific installation (only available in current directory)
    )


class MCPServerStatus(str, Enum):
    """Status of an MCP server."""

    AVAILABLE = "available"
    INSTALLED = "installed"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    UPDATING = "updating"
    UNKNOWN = "unknown"


class MCPServerInfo(BaseModel):
    """Information about an MCP server."""

    name: str = Field(description="Server name")
    display_name: str = Field(description="Human-readable display name")
    description: str = Field(description="Server description")
    category: MCPServerCategory = Field(description="Server category")
    repository_url: Optional[HttpUrl] = Field(None, description="Source repository URL")
    documentation_url: Optional[HttpUrl] = Field(None, description="Documentation URL")
    version: Optional[str] = Field(None, description="Latest version")
    author: Optional[str] = Field(None, description="Author name")
    license: Optional[str] = Field(None, description="License type")
    keywords: List[str] = Field(default_factory=list, description="Search keywords")
    created_at: Optional[datetime] = Field(None, description="Creation date")
    updated_at: Optional[datetime] = Field(None, description="Last update date")
    stars: Optional[int] = Field(None, description="GitHub stars count")
    status: MCPServerStatus = Field(
        MCPServerStatus.AVAILABLE, description="Current status"
    )


class MCPServerOption(BaseModel):
    """Installation option for an MCP server."""

    name: str = Field(description="Option name")
    display_name: str = Field(description="Human-readable option name")
    description: Optional[str] = Field(None, description="Option description")
    install_command: str = Field(description="Installation command")
    config_name: str = Field(description="Configuration name for Claude")
    env_vars: List[str] = Field(
        default_factory=list, description="Required environment variables"
    )
    repository_url: Optional[HttpUrl] = Field(
        None, description="Specific repository for this option"
    )
    recommended: bool = Field(
        False, description="Whether this is the recommended option"
    )


class MCPClientIntegration(BaseModel):
    """Integration configuration for a specific MCP client."""

    config_path: str = Field(description="Path to client's configuration file")
    config_template: Dict[str, Any] = Field(
        description="Configuration template to merge"
    )
    restart_required: bool = Field(
        default=False, description="Whether client restart is required"
    )
    instructions: Optional[str] = Field(None, description="Setup instructions for user")


class MCPEnvironmentVariable(BaseModel):
    """Environment variable configuration."""

    name: str = Field(description="Environment variable name")
    description: str = Field(description="Variable description")
    required: bool = Field(default=False, description="Whether variable is required")
    example: Optional[str] = Field(None, description="Example value")


class MCPPlatformSupport(BaseModel):
    """Platform support information."""

    windows: bool = Field(default=True, description="Windows support")
    macos: bool = Field(default=True, description="macOS support")
    linux: bool = Field(default=True, description="Linux support")


class MCPServerOptionEnhanced(BaseModel):
    """Enhanced installation option with integration support."""

    # Installation configuration
    install: str = Field(description="Installation command")
    verify_install: Optional[str] = Field(
        None, description="Command to verify installation"
    )
    uninstall: Optional[str] = Field(None, description="Uninstallation command")

    # Integration configurations
    integrations: Dict[str, MCPClientIntegration] = Field(
        default_factory=dict, description="Client integration configurations"
    )

    # Environment and requirements
    env_vars: List[MCPEnvironmentVariable] = Field(
        default_factory=list, description="Environment variable configurations"
    )
    prerequisites: List[str] = Field(
        default_factory=list, description="Required system dependencies"
    )
    platform_support: MCPPlatformSupport = Field(
        default_factory=MCPPlatformSupport, description="Platform support information"
    )


class MCPServerDefinitionEnhanced(BaseModel):
    """Enhanced server definition with complete integration support."""

    name: str = Field(description="Server display name")
    description: str = Field(description="Server description")
    repository_url: Optional[HttpUrl] = Field(None, description="Repository URL")
    documentation_url: Optional[HttpUrl] = Field(None, description="Documentation URL")
    author: Optional[str] = Field(None, description="Server author")
    category: str = Field(description="Server category")
    options: Dict[str, MCPServerOptionEnhanced] = Field(
        description="Installation options with integration support"
    )


class IntegrationResult(BaseModel):
    """Result of MCP client integration."""

    success: bool = Field(description="Whether integration succeeded")
    client_name: str = Field(description="Name of the MCP client")
    config_path: str = Field(description="Path to configuration file")
    message: str = Field(description="Result message")
    restart_required: bool = Field(description="Whether client restart is required")


# CompleteInstallationResult moved below MCPInstallationResult


class MCPServerWithOptions(MCPServerInfo):
    """MCP server with installation options."""

    options: List[MCPServerOption] = Field(
        default_factory=list, description="Installation options"
    )


class MCPSearchQuery(BaseModel):
    """Search query for MCP servers."""

    query: Optional[str] = Field(None, description="Search query text")
    category: Optional[MCPServerCategory] = Field(
        None, description="Filter by category"
    )
    keywords: Optional[List[str]] = Field(None, description="Filter by keywords")
    sort_by: Optional[str] = Field("relevance", description="Sort order")
    limit: Optional[int] = Field(20, description="Maximum results to return")


class MCPSearchResult(BaseModel):
    """Search results for MCP servers."""

    query: MCPSearchQuery = Field(description="Original search query")
    total_count: int = Field(description="Total number of results")
    servers: List[MCPServerWithOptions] = Field(description="Found servers")
    search_time_ms: int = Field(description="Search execution time in milliseconds")


class MCPInstallationRequest(BaseModel):
    """Request to install an MCP server."""

    server_name: str = Field(description="Server name to install")
    option_name: str = Field(description="Installation option to use")
    env_vars: Optional[Dict[str, str]] = Field(
        None, description="Environment variables"
    )
    auto_configure: bool = Field(
        True, description="Automatically update Claude configuration"
    )


class MCPInstallationResult(BaseModel):
    """Result of an MCP server installation."""

    success: bool = Field(description="Whether installation succeeded")
    server_name: str = Field(description="Server name that was installed")
    option_name: str = Field(description="Installation option used")
    config_name: str = Field(description="Configuration name in Claude")
    message: str = Field(description="Installation message or error")
    installed_at: datetime = Field(
        default_factory=datetime.now, description="Installation timestamp"
    )


class CompleteInstallationResult(BaseModel):
    """Result of complete installation (install + integrate)."""

    server_name: str = Field(description="Name of the server")
    installation: Optional[MCPInstallationResult] = Field(
        None, description="Installation result"
    )
    integrations: List[IntegrationResult] = Field(
        default_factory=list, description="Integration results"
    )
    overall_success: bool = Field(description="Overall operation success")
    summary: str = Field(description="Summary message for user")

class AIInstallationRequest(BaseModel):
    """Request for AI-assisted installation as fallback."""
    
    server_name: str = Field(description="Name of the server to install")
    reason: str = Field(description="Reason for installation failure")
    suggested_command: Optional[str] = Field(None, description="AI-suggested installation command")
    suggested_integration: Optional[Dict[str, Any]] = Field(None, description="AI-suggested integration config")
    env_vars: Optional[Dict[str, str]] = Field(None, description="Environment variables needed")
    clients: Optional[List[str]] = Field(None, description="Target MCP clients")
    user_approved: bool = Field(default=False, description="Whether user approved the AI suggestion")


class AIInstallationResult(BaseModel):
    """Result of AI-assisted installation."""
    
    success: bool = Field(description="Whether AI installation succeeded")
    server_name: str = Field(description="Server name that was installed")
    method: str = Field(description="Installation method used by AI")
    command_executed: str = Field(description="Actual command executed")
    integration_created: bool = Field(default=False, description="Whether integration config was created")
    message: str = Field(description="Installation result message")
    warnings: List[str] = Field(default_factory=list, description="Any warnings during installation")


class MCPConfigEntry(BaseModel):
    """Entry in MCP configuration for a server."""

    command: str = Field(description="Command to execute")
    args: List[str] = Field(default_factory=list, description="Command arguments")
    cwd: Optional[str] = Field(None, description="Working directory")
    env: Optional[Dict[str, str]] = Field(None, description="Environment variables")


class MCPConfiguration(BaseModel):
    """MCP configuration structure."""

    mcpServers: Dict[str, MCPConfigEntry] = Field(
        default_factory=dict, description="Configured MCP servers"
    )


class MCPServerHealth(BaseModel):
    """Health status of an MCP server."""

    is_running: bool = Field(description="Whether the server is running")
    response_time_ms: Optional[int] = Field(
        None, description="Response time in milliseconds"
    )
    error_message: Optional[str] = Field(None, description="Error message if unhealthy")
    last_checked: datetime = Field(
        default_factory=datetime.now, description="Last health check time"
    )


class ErrorCategory(str, Enum):
    """Categories of installation errors."""

    PERMISSION_ERROR = "permission_error"
    NETWORK_ERROR = "network_error"
    DEPENDENCY_MISSING = "dependency_missing"
    PACKAGE_NOT_FOUND = "package_not_found"
    ENVIRONMENT_ISSUE = "environment_issue"
    SYSTEM_ERROR = "system_error"
    COMMAND_ERROR = "command_error"
    UNKNOWN = "unknown"


class InstallationError(BaseModel):
    """Detailed information about an installation error."""

    category: ErrorCategory = Field(description="Error category")
    message: str = Field(description="Error message")
    details: Dict[str, str] = Field(
        default_factory=dict, description="Additional error details"
    )
    suggestion: Optional[str] = Field(None, description="Suggested fix for the error")


class InstallationLogEntry(BaseModel):
    """Log entry for a single installation attempt."""

    attempt_id: int = Field(description="Attempt number within session")
    command: str = Field(description="Command that was executed")
    attempt_type: str = Field(description="Type of attempt (primary, fallback, readme)")
    started_at: datetime = Field(description="When the attempt started")
    ended_at: Optional[datetime] = Field(None, description="When the attempt ended")
    duration_seconds: Optional[float] = Field(
        None, description="How long the attempt took"
    )
    cwd: str = Field(description="Working directory for the command")
    return_code: Optional[int] = Field(None, description="Command return code")
    stdout: str = Field(default="", description="Standard output from command")
    stderr: str = Field(default="", description="Standard error from command")
    success: bool = Field(default=False, description="Whether the attempt succeeded")
    error: Optional[InstallationError] = Field(
        None, description="Error details if failed"
    )


class InstallationSession(BaseModel):
    """Complete session log for an installation attempt."""

    session_id: str = Field(description="Unique session identifier")
    server_name: str = Field(description="Name of server being installed")
    option_name: str = Field(description="Installation option being used")
    install_command: str = Field(description="Primary installation command")
    started_at: datetime = Field(description="When the session started")
    ended_at: Optional[datetime] = Field(None, description="When the session ended")
    duration_seconds: Optional[float] = Field(
        None, description="Total session duration"
    )
    success: Optional[bool] = Field(None, description="Overall success of installation")
    final_message: Optional[str] = Field(None, description="Final result message")
    system_info: Dict[str, str] = Field(
        default_factory=dict, description="System information"
    )
    attempts: List[InstallationLogEntry] = Field(
        default_factory=list, description="All installation attempts"
    )


class InstallationStats(BaseModel):
    """Statistics about installation attempts."""

    total_attempts: int = Field(description="Total number of installation attempts")
    successful_installs: int = Field(description="Number of successful installations")
    failed_installs: int = Field(description="Number of failed installations")
    success_rate: float = Field(description="Success rate as percentage")
    error_categories: Dict[str, int] = Field(
        default_factory=dict, description="Count by error category"
    )
    most_problematic_servers: List[str] = Field(
        default_factory=list, description="Servers with most failures"
    )
    average_install_time: Optional[float] = Field(
        None, description="Average installation time in seconds"
    )
    last_updated: datetime = Field(
        default_factory=datetime.now, description="When stats were last updated"
    )
