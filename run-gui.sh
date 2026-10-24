#!/usr/bin/env bash
# Open the desktop app (from a source checkout).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
exec "$HERE/venv/bin/python" -m booktranscriber "$@"
