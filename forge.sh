#!/bin/sh
# Decomp Forge - Wind Waker (Linux launcher)
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:$PATH"
echo "Starting Decomp Forge... http://localhost:7878"
exec python3 forge/forge.py serve
