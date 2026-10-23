#!/usr/bin/env bash
# One-time setup: create ./venv and install dependencies.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 -m venv "$HERE/venv"
"$HERE/venv/bin/python" -m pip install --upgrade pip
"$HERE/venv/bin/python" -m pip install -r "$HERE/requirements.txt"
echo "Setup complete. Try: ./run.sh -h"
