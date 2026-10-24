"""Transcription worker: runs in a child process and streams JSON-line events on stdout.

    python -m booktranscriber.worker --audio IN --out OUT --model NAME_OR_PATH [...]
    python -m booktranscriber.worker --selftest --model NAME_OR_PATH [--device ...]

Running Whisper here instead of in the GUI process means Cancel is a kill, and a native
CUDA crash becomes an error message instead of taking the window down.
"""
import argparse
import os
import sys
import time
from typing import Callable

from . import engine

CUDA_WORDS = ("cublas", "cudnn", "cuda")


class BadAudio(Exception):
    pass


def worker_command(args: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker", *args]
    return [sys.executable, "-m", "booktranscriber.worker", *args]


def worker_env(lib_dirs: list[str] | None = None, base=None) -> dict[str, str]:
    """Environment for a worker child: GPU libraries on the loader path, and (from source) this package importable."""
    from .gpu import default_lib_dirs, gpu_env
    base = os.environ if base is None else base
    env = gpu_env(default_lib_dirs() if lib_dirs is None else lib_dirs, base, sys.platform == "win32")
    if not getattr(sys, "frozen", False):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env["PYTHONPATH"] = os.pathsep.join([root] + ([base["PYTHONPATH"]] if base.get("PYTHONPATH") else []))
    return env


def probe_audio(path: str) -> float:
    """Fail fast, before the multi-GB model loads, if this isn't decodable audio."""
    import av
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    try:
        with av.open(path) as c:
            if not c.streams.audio:
                raise BadAudio("no audio stream")
            return (c.duration or 0) / 1_000_000
    except av.error.FFmpegError as e:
        raise BadAudio(str(e)) from e


def classify(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        return "not_found"
    if isinstance(exc, BadAudio):
        return "bad_audio"
    if isinstance(exc, engine.ModelLoadError):
        return "model"
    if isinstance(exc, (RuntimeError, OSError)) and any(w in str(exc).lower() for w in CUDA_WORDS):
        return "model"
    try:
        import av
        if isinstance(exc, av.error.FFmpegError):
            return "bad_audio"
    except ImportError:
        pass
    if isinstance(exc, PermissionError):
        return "write"
    return "unknown"


def parse_args(argv):
    p = argparse.ArgumentParser(prog="booktranscriber.worker")
    p.add_argument("--audio")
    p.add_argument("--out")
    p.add_argument("--model", required=True)
    p.add_argument("--download-root")
    p.add_argument("--language", default="fa")
    p.add_argument("--prompt")
    p.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    p.add_argument("--timestamps", action="store_true")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args(argv)
    if not a.selftest and not (a.audio and a.out):
        p.error("--audio and --out are required")
    # Absolute now, because loading a local model changes the working directory (see load_in_child).
    for name in ("audio", "out", "download_root"):
        if getattr(a, name):
            setattr(a, name, os.path.abspath(getattr(a, name)))
    return a


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _selftest(a, emit, loader) -> int:
    import numpy as np
    model, backend = loader(a.model, a.device, a.download_root, _log)
    emit({"type": "loaded", "backend": backend})
    noise = np.random.default_rng(0).normal(0, 0.01, 32000).astype(np.float32)
    # No VAD, and consume every segment, so the encoder and GPU kernels really run.
    segments, _ = engine.transcribe(model, noise, engine.TranscribeOptions(language="fa"), vad_filter=False)
    n = sum(1 for _ in segments)
    emit({"type": "done", "out": "", "segments": n})
    return 0


def _transcribe(a, emit, loader) -> int:
    probe_audio(a.audio)
    model, backend = loader(a.model, a.device, a.download_root, _log)
    emit({"type": "loaded", "backend": backend})
    opts = engine.TranscribeOptions(language=a.language, prompt=a.prompt, timestamps=a.timestamps)
    segments, total = engine.transcribe(model, a.audio, opts)
    emit({"type": "duration", "seconds": total})

    part = a.out + ".part"
    start = last = time.time()
    n = 0
    try:
        with open(part, "w", encoding="utf-8") as f:
            for seg in segments:
                n += 1
                f.write(engine.format_line(seg, a.timestamps) + "\n")
                f.flush()
                emit({"type": "segment", "start": seg.start, "end": seg.end, "text": seg.text.strip()})
                now = time.time()
                if now - last >= 1.0:
                    last = now
                    rate = seg.end / (now - start) if now > start else 0
                    eta = (total - seg.end) / rate if rate else 0
                    emit({"type": "progress", "done": seg.end, "total": total, "eta": eta})
        if n:
            os.replace(part, a.out)
        else:
            os.remove(part)     # nothing heard: don't replace an earlier transcript with an empty file
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise
    emit({"type": "done", "out": a.out, "segments": n})
    return 0


def load_in_child(name_or_path: str, device: str, download_root: str | None, log):
    """The worker's loader: native code gets a bare model name, run from the model's parent folder."""
    return engine.load_model(engine.local_model_ref(name_or_path), device, download_root, log)


def run(argv: list[str], emit: Callable[[dict], None], loader=engine.load_model) -> int:
    a = parse_args(argv)
    try:
        return (_selftest if a.selftest else _transcribe)(a, emit, loader)
    except Exception as e:
        import traceback
        traceback.print_exc()
        emit({"type": "error", "kind": classify(e), "message": str(e)})
        return 1


def ensure_stdio() -> None:
    """A windowed frozen app starts with sys.stdout/stderr None; the parent's pipes are still fds 1 and 2."""
    for name, fd in (("stdout", 1), ("stderr", 2)):
        if getattr(sys, name) is not None:
            continue
        try:
            if sys.platform == "win32":
                import msvcrt
                if msvcrt.get_osfhandle(fd) < 0:     # -2: the fd exists but the parent gave it no handle
                    raise OSError(fd, "no inherited handle")
            # fdopen fstat()s the fd, so a closed one raises here
            stream = os.fdopen(fd, "w", encoding="utf-8", buffering=1, closefd=False)
        except OSError:
            stream = open(os.devnull, "w", encoding="utf-8")
        setattr(sys, name, stream)


def main(argv: list[str] | None = None) -> int:
    from .gpu import register_dll_dirs_from_env
    from .protocol import encode
    ensure_stdio()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    register_dll_dirs_from_env()
    return run(sys.argv[1:] if argv is None else argv, lambda e: print(encode(e), flush=True),
               loader=load_in_child)


if __name__ == "__main__":
    sys.exit(main())
