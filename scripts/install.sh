#!/usr/bin/env sh
# install.sh — piighost one-command installer for macOS / Linux
# Usage: curl -LsSf https://piighost.dev/install.sh | sh
set -eu

PIIGHOST_EXTRAS="mcp,index,gliner2"

# 1. Ensure uv is present
if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Add uv to PATH for the remainder of this script
    export PATH="$HOME/.local/bin:$PATH"
fi

# 2. Install piighost (quiet, so uv's own output is the only noise)
echo "Installing piighost[${PIIGHOST_EXTRAS}]..."
uv tool install "piighost[${PIIGHOST_EXTRAS}]" --python 3.12

# 3. Run the Python installer to warm up models and register Claude Desktop
echo "Running piighost install --full ..."
piighost install --full
