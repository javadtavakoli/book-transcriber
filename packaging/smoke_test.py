"""Smoke-test a frozen build:  python packaging/smoke_test.py dist/WritingParrot

Copies the build to a folder with a Persian name and a space, then checks that the GUI self-check
passes and that the worker answers a missing file with a not_found error line. Exits non-zero on failure.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EXE = "WritingParrot.exe" if sys.platform == "win32" else "WritingParrot"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
WORKER_TIMEOUT = 60


def fail(msg: str) -> int:
    print(f"FAIL: {msg}", flush=True)
    return 1


def check_gui(exe: Path, work: Path, env: dict) -> int:
    out = work / "smoke.txt"
    try:
        r = subprocess.run([str(exe), "--smoke", "--smoke-out", str(out)], env=env,
                           capture_output=True, encoding="utf-8", errors="replace", timeout=180, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return fail("--smoke did not exit within 180 s")
    text = out.read_text(encoding="utf-8") if out.is_file() else ""
    if r.returncode != 0 or not text.startswith("SMOKE OK"):
        return fail(f"--smoke exit {r.returncode}\n{text}\n{r.stdout}\n{r.stderr}")
    print(text.strip(), flush=True)
    return 0


def check_worker(exe: Path, work: Path, env: dict) -> int:
    cmd = [str(exe), "--worker", "--audio", str(work / "missing.wav"), "--out", str(work / "x.txt"),
           "--model", "large-v3"]
    p = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    try:
        out, err = p.communicate(timeout=WORKER_TIMEOUT)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        return fail(f"worker sent no answer within {WORKER_TIMEOUT} s")
    for line in out.decode("utf-8", "replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "error" and event.get("kind") == "not_found":
            print(f"worker: {line}", flush=True)
            return 0
    return fail(f"no not_found error line (exit {p.returncode})\nstdout: {out.decode('utf-8', 'replace')}\nstderr: {err.decode('utf-8', 'replace')}")


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")    # a cp1252 CI console can't print Persian paths
    except Exception:
        pass
    if len(argv) != 1:
        print(__doc__)
        return 2
    dist = Path(argv[0]).resolve()
    if not (dist / EXE).is_file():
        return fail(f"{dist / EXE} not found")
    tmp = Path(tempfile.mkdtemp())
    try:
        app = tmp / "طوطی تست"
        shutil.copytree(dist, app, symlinks=True)
        work = tmp / "پوشه کار"      # non-ASCII --audio and --out paths too
        (work / "data").mkdir(parents=True)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", BT_DATA_DIR=str(work / "data"))
        start = time.time()
        code = check_gui(app / EXE, work, env) or check_worker(app / EXE, work, env)
        print(f"{'PASS' if code == 0 else 'FAILED'} in {time.time() - start:.0f} s", flush=True)
        return code
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
