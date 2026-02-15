#!/usr/bin/env bash
# install.sh — Install meta-mcp and register it as a user-level MCP server.
#
# Usage:
#   ./scripts/install.sh          # from the repo root
#   bash scripts/install.sh       # explicit
#
# What it does:
#   1. pip install -e .  (editable mode)
#   2. Register meta-mcp in ~/.claude.json  (Claude Code user scope)
#
# Prerequisites: Python 3.10+, pip, Claude Code installed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Colours (disabled when not a terminal) ────────────────────────────────
if [ -t 1 ]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; NC=''
fi

info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
fail()  { echo -e "${RED}[x]${NC} $*" >&2; exit 1; }

# ── Detect Python ─────────────────────────────────────────────────────────
PYTHON=""
for cmd in py python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done
[ -n "$PYTHON" ] || fail "Python not found. Install Python 3.10+ first."

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Using $PYTHON ($PY_VERSION)"

# ── Step 1: Editable install ─────────────────────────────────────────────
info "Installing meta-mcp in editable mode..."
"$PYTHON" -m pip install -e "$REPO_ROOT" --quiet || fail "pip install -e failed"

# Verify the module is importable
"$PYTHON" -c "import meta_mcp" 2>/dev/null || fail "meta_mcp not importable after install"
info "Editable install OK"

# ── Step 2: Register in ~/.claude.json ────────────────────────────────────
info "Registering meta-mcp in ~/.claude.json (user-level MCP server)..."

"$PYTHON" -c "
import json, sys
from pathlib import Path

config_path = Path.home() / '.claude.json'

# Read existing config (or start fresh)
data = {}
if config_path.is_file():
    try:
        data = json.loads(config_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        print('[!] ~/.claude.json has invalid JSON — creating backup', file=sys.stderr)
        backup = config_path.with_suffix('.json.bak')
        config_path.rename(backup)
        print(f'    Backup saved to {backup}', file=sys.stderr)

data.setdefault('mcpServers', {})

data['mcpServers']['meta-mcp'] = {
    'type': 'stdio',
    'command': '$PYTHON',
    'args': ['-m', 'meta_mcp', '--stdio'],
}

config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(f'Wrote meta-mcp entry to {config_path}')
" || fail "Failed to update ~/.claude.json"

info "Registration OK"

# ── Step 3: Verify ────────────────────────────────────────────────────────
info "Verifying meta-mcp is accessible..."
"$PYTHON" -m meta_mcp --help >/dev/null 2>&1 || fail "meta-mcp --help failed"
info "Verification OK"

echo ""
info "meta-mcp installed and registered successfully!"
echo "  Restart Claude Code to pick up the new MCP server."
echo ""
echo "  To uninstall:"
echo "    $PYTHON -m pip uninstall meta-mcp"
echo "    # Then remove the 'meta-mcp' entry from ~/.claude.json"
