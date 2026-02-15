#Requires -Version 5.1
<#
.SYNOPSIS
    Install meta-mcp and register it as a user-level MCP server for Claude Code.

.DESCRIPTION
    1. pip install -e .  (editable mode)
    2. Register meta-mcp in ~/.claude.json  (Claude Code user scope)

.EXAMPLE
    .\scripts\install.ps1          # from the repo root
    powershell -File scripts\install.ps1

.NOTES
    Prerequisites: Python 3.10+, pip, Claude Code installed.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir

function Write-Info  { param([string]$Message) Write-Host "[+] $Message" -ForegroundColor Green }
function Write-Warn  { param([string]$Message) Write-Host "[!] $Message" -ForegroundColor Yellow }
function Write-Fail  { param([string]$Message) Write-Host "[x] $Message" -ForegroundColor Red; exit 1 }

# ── Detect Python ─────────────────────────────────────────────────────────
$Python = $null
foreach ($cmd in @('py', 'python3', 'python')) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $Python = $cmd
        break
    }
}
if (-not $Python) { Write-Fail "Python not found. Install Python 3.10+ first." }

$PyVersion = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Info "Using $Python ($PyVersion)"

# ── Step 1: Editable install ─────────────────────────────────────────────
Write-Info "Installing meta-mcp in editable mode..."
& $Python -m pip install -e $RepoRoot --quiet
if ($LASTEXITCODE -ne 0) { Write-Fail "pip install -e failed" }

# Verify the module is importable
& $Python -c "import meta_mcp" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Fail "meta_mcp not importable after install" }
Write-Info "Editable install OK"

# ── Step 2: Register in ~/.claude.json ────────────────────────────────────
Write-Info "Registering meta-mcp in ~/.claude.json (user-level MCP server)..."

$RegisterScript = @'
import json, sys
from pathlib import Path

config_path = Path.home() / ".claude.json"

data = {}
if config_path.is_file():
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("[!] ~/.claude.json has invalid JSON - creating backup", file=sys.stderr)
        backup = config_path.with_suffix(".json.bak")
        config_path.rename(backup)
        print(f"    Backup saved to {backup}", file=sys.stderr)

data.setdefault("mcpServers", {})

data["mcpServers"]["meta-mcp"] = {
    "type": "stdio",
    "command": "$Python",
    "args": ["-m", "meta_mcp", "--stdio"],
}

config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Wrote meta-mcp entry to {config_path}")
'@

& $Python -c $RegisterScript
if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to update ~/.claude.json" }
Write-Info "Registration OK"

# ── Step 3: Verify ────────────────────────────────────────────────────────
Write-Info "Verifying meta-mcp is accessible..."
& $Python -m meta_mcp --help *>$null
if ($LASTEXITCODE -ne 0) { Write-Fail "meta-mcp --help failed" }
Write-Info "Verification OK"

Write-Host ""
Write-Info "meta-mcp installed and registered successfully!"
Write-Host "  Restart Claude Code to pick up the new MCP server."
Write-Host ""
Write-Host "  To uninstall:"
Write-Host "    $Python -m pip uninstall meta-mcp"
Write-Host "    # Then remove the 'meta-mcp' entry from ~/.claude.json"
