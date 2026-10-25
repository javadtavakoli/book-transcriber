"""Smoke-test a frozen build:  python packaging/smoke_test.py dist/WritingParrot [--model-test]

Copies the build to a folder with a Persian name and a space, then checks that the GUI self-check
passes and that the worker answers a missing file with a not_found error line. Exits non-zero on failure.
--model-test also downloads the tiny Whisper model (about 80 MB) into a Persian-named folder and
checks that the worker's self-test really loads it and runs it on the processor, then that the
worker transcribes a real recording from a Persian-named folder from start to finish.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

EXE = "WritingParrot.exe" if sys.platform == "win32" else "WritingParrot"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
WORKER_TIMEOUT = 60
MODEL_TIMEOUT = 300
TINY_REPO = "Systran/faster-whisper-tiny"
TINY_REVISION = "d90ca5fe260221311c53c58e660288d3deb8d356"
TINY_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]


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


def run_worker(cmd: list[str], env: dict, timeout: int):
    """Runs the worker; returns (events, stdout, stderr), or None when it didn't finish in time."""
    p = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        return None
    out, err = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    events = []
    for line in out.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events, out, err


def check_transcribe(exe: Path, model: Path, work: Path, env: dict) -> int:
    """A real recording, read by the frozen app's own audio reader: the self-test alone doesn't open a file."""
    audio = work / "ضبط تست.wav"
    with wave.open(str(audio), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(bytes(range(256)) * 250)       # 2 s of a quiet buzz
    out_file = work / "متن.txt"
    cmd = [str(exe), "--worker", "--audio", str(audio), "--out", str(out_file), "--model", str(model), "--device", "cpu"]
    r = run_worker(cmd, env, MODEL_TIMEOUT)
    if r is None:
        return fail(f"transcription did not finish within {MODEL_TIMEOUT} s")
    events, out, err = r
    done = [e for e in events if e.get("type") == "done"]
    if not done:
        return fail(f"no done line from a real transcription\nstdout: {out}\nstderr: {err}")
    print(f"transcribe: {json.dumps(done[0], ensure_ascii=False)}", flush=True)
    return 0


def check_model(exe: Path, tmp: Path, env: dict) -> int:
    """A model in a Persian folder (a Persian Windows user name) must load: native code only gets an ASCII name."""
    from huggingface_hub import snapshot_download
    model = tmp / "کاربر علی" / "دانلودها" / "faster-whisper-tiny"
    try:
        snapshot_download(TINY_REPO, revision=TINY_REVISION, local_dir=model, allow_patterns=TINY_FILES)
    except Exception as e:
        return fail(f"could not download {TINY_REPO}: {e}")
    cmd = [str(exe), "--worker", "--selftest", "--model", str(model), "--device", "cpu"]
    r = run_worker(cmd, env, MODEL_TIMEOUT)
    if r is None:
        return fail(f"model self-test did not finish within {MODEL_TIMEOUT} s")
    events, out, err = r
    done = [e for e in events if e.get("type") == "done"]
    if not done:
        return fail(f"no done line from the model self-test\nstdout: {out}\nstderr: {err}")
    if f"loading {model.name} " not in err:
        return fail(f"the model was not loaded by its bare name\nstderr: {err}")
    print(f"model: {json.dumps(done[0])}", flush=True)
    return check_transcribe(exe, model, tmp / "پوشه کار", env)


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")    # a cp1252 CI console can't print Persian paths
    except Exception:
        pass
    model_test = "--model-test" in argv
    argv = [a for a in argv if a != "--model-test"]
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
        if code == 0 and model_test:
            code = check_model(app / EXE, tmp, env)
        print(f"{'PASS' if code == 0 else 'FAILED'} in {time.time() - start:.0f} s", flush=True)
        return code
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
