#!/usr/bin/env bash
# Transcribe a book-club recording locally on the GPU.
# Usage: ./run.sh "/path/to/session.m4a" ["/path/to/out.txt"]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$HERE/venv/bin/python" "$HERE/transcribe.py" "$@"
