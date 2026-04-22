#!/usr/bin/env bash
# ─────────────────────────────────────────────────
#  Turtle Logo IDE – launch script
# ─────────────────────────────────────────────────
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Ensure python3-tk is installed
if ! python3 -c "import tkinter" 2>/dev/null; then
  echo "tkinter not found. Installing python3-tk..."
  sudo apt-get install -y python3-tk
fi

cd "$SCRIPT_DIR"
exec python3 logo_ide.py "$@"
