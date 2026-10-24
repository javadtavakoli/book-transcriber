"""Check that a release tag matches the package version:  python tools/check_version.py v0.1.0

Exits 1 (with a message) when the tag is not "v" + booktranscriber.__version__, 2 on bad usage.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from booktranscriber import __version__  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: check_version.py <tag>", file=sys.stderr)
        return 2
    tag, expected = argv[0], f"v{__version__}"
    if tag != expected:
        print(f"Tag {tag!r} does not match the package version {__version__} (expected {expected!r}).", file=sys.stderr)
        return 1
    print(f"Tag {tag} matches the package version.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
