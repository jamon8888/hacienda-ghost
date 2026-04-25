#!/usr/bin/env bash
# install.sh — piighost one-command installer for macOS / Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/jamon8888/hacienda-ghost/master/scripts/install.sh | bash
#
# Options (set before running):
#   PIIGHOST_MODE   = strict (default) | local
#   PIIGHOST_EXTRAS = proxy,gliner2,mcp,index,cache (default)
#   PIIGHOST_SOURCE = PyPI package name or git URL (default: GitHub)

set -euo pipefail

MODE="${PIIGHOST_MODE:-strict}"
EXTRAS="${PIIGHOST_EXTRAS:-proxy,gliner2,mcp,index,cache}"
SOURCE="${PIIGHOST_SOURCE:-git+https://github.com/jamon8888/hacienda-ghost.git}"

echo ""
echo "piighost installer"
echo "  mode   : $MODE"
echo "  extras : $EXTRAS"
echo "  source : $SOURCE"
echo ""

# ---------------------------------------------------------------------------
# 1. Ensure uv is present
# ---------------------------------------------------------------------------
if command -v uv &>/dev/null; then
    echo "[1/4] uv already installed"
else
    echo "[1/4] Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    source "$HOME/.local/bin/env" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# 2. Stop any running piighost service before (re)install
# ---------------------------------------------------------------------------
echo "[2/4] Stopping existing piighost service (if any)..."

if [[ "$(uname)" == "Darwin" ]]; then
    sudo launchctl unload /Library/LaunchDaemons/com.piighost.proxy.plist 2>/dev/null || true
else
    sudo systemctl stop piighost-proxy 2>/dev/null || true
fi

pkill -f "uvicorn.*piighost" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 3. Install piighost with all requested extras
# ---------------------------------------------------------------------------
echo "[3/4] Installing piighost[$EXTRAS]..."
uv tool install --reinstall "piighost[$EXTRAS] @ $SOURCE" --python 3.12

# Make the installed binary available in this shell session
export PATH="$(uv tool dir)/piighost/bin:$PATH"

# ---------------------------------------------------------------------------
# 4. Run the system installer (requires sudo for port 443 + hosts file)
# ---------------------------------------------------------------------------
echo "[4/4] Running: piighost install --mode=$MODE ..."
piighost install --mode="$MODE"

echo ""
echo "Done! piighost is installed in $MODE mode."
echo "Run 'piighost doctor' to verify everything is working."
