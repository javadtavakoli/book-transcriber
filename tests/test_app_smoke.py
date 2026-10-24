import os
import subprocess
import sys


def test_smoke_flag_writes_ok(tmp_path):
    out = tmp_path / "smoke.txt"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", BT_DATA_DIR=str(tmp_path / "data"))
    r = subprocess.run([sys.executable, "-m", "booktranscriber", "--smoke", "--smoke-out", str(out)],
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert out.read_text(encoding="utf-8").startswith("SMOKE OK")
