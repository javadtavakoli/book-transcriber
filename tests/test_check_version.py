import subprocess
import sys
from pathlib import Path

import pytest

from booktranscriber import __version__

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "check_version.py"
MAJOR, MINOR, PATCH = (int(x) for x in __version__.split("."))


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60)


def test_matching_tag_passes():
    r = run(f"v{__version__}")
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("tag", [f"v{MAJOR}.{MINOR}.{PATCH + 1}", __version__, ""])
def test_other_tags_fail(tag):
    r = run(tag)
    assert r.returncode == 1
    assert __version__ in r.stderr


def test_missing_argument_fails():
    assert run().returncode == 2
