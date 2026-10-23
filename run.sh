#!/usr/bin/env bash
# Transcribe recordings locally on the GPU.  Run ./run.sh -h for options.
# Usage: ./run.sh "/path/to/session.m4a" [-o out.txt] [-f prompts/book.txt] [-t]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$HERE/venv/bin/python" "$HERE/transcribe.py" "$@"
