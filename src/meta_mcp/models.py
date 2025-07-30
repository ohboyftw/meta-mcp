"""
Data models for Meta MCP Server.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
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
    status: MCPServerStatus = Field(MCPServerStatus.AVAILABLE, description="Current status")


class MCPServerOption(BaseModel):
    """Installation option for an MCP server."""
    name: str = Field(description="Option name")
    display_name: str = Field(description="Human-readable option name")
    description: Optional[str] = Field(None, description="Option description")
    install_command: str = Field(description="Installation command")
    config_name: str = Field(description="Configuration name for Claude")
    env_vars: List[str] = Field(default_factory=list, description="Required environment variables")
    repository_url: Optional[HttpUrl] = Field(None, description="Specific repository for this option")
    recommended: bool = Field(False, description="Whether this is the recommended option")


class MCPServerWithOptions(MCPServerInfo):
    """MCP server with installation options."""
    options: List[MCPServerOption] = Field(default_factory=list, description="Installation options")


class MCPSearchQuery(BaseModel):
    """Search query for MCP servers."""
    query: Optional[str] = Field(None, description="Search query text")
    category: Optional[MCPServerCategory] = Field(None, description="Filter by category")
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
    env_vars: Optional[Dict[str, str]] = Field(None, description="Environment variables")
    auto_configure: bool = Field(True, description="Automatically update Claude configuration")


class MCPInstallationResult(BaseModel):
    """Result of an MCP server installation."""
    success: bool = Field(description="Whether installation succeeded")
    server_name: str = Field(description="Server name that was installed")
    option_name: str = Field(description="Installation option used")
    config_name: str = Field(description="Configuration name in Claude")
    message: str = Field(description="Installation message or error")
    installed_at: datetime = Field(default_factory=datetime.now, description="Installation timestamp")


class MCPConfigEntry(BaseModel):
    """Entry in MCP configuration for a server."""
    command: str = Field(description="Command to execute")
    args: List[str] = Field(default_factory=list, description="Command arguments")
    cwd: Optional[str] = Field(None, description="Working directory")
    env: Optional[Dict[str, str]] = Field(None, description="Environment variables")


class MCPConfiguration(BaseModel):
    """MCP configuration structure."""
    mcpServers: Dict[str, MCPConfigEntry] = Field(default_factory=dict, description="Configured MCP servers")


class MCPServerHealth(BaseModel):
    """Health status of an MCP server."""
    is_running: bool = Field(description="Whether the server is running")
    response_time_ms: Optional[int] = Field(None, description="Response time in milliseconds")
    error_message: Optional[str] = Field(None, description="Error message if unhealthy")
    last_checked: datetime = Field(default_factory=datetime.now, description="Last health check time")