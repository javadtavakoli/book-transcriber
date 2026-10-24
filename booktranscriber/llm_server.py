"""Runs llama-server as a child process: loading progress from its log, CPU fallback, no orphans."""
import atexit
import socket
import subprocess
import sys
import threading
import time
import weakref
from collections import deque
from pathlib import Path
from typing import Callable

import httpx

from .downloader import DownloadCancelled
from .llm_sources import server_binary
from .settings import Settings

# Startup log lines (matched by substring) and how far along loading is when each appears.
LOAD_STAGES: list[tuple[str, float]] = [
    ("load_model: loading model", 0.05),
    ("llama_model_loader: loaded meta data", 0.15),
    ("load_tensors: loading model tensors", 0.25),
    ("model buffer size", 0.30),
    ("llama_context:", 0.80),
    ("KV buffer size", 0.85),
    ("warming up the model", 0.90),
    ("all slots are idle", 1.0),
]
MEMORY_ERRORS = ("out of memory", "erroroutofdevicememory", "failed to allocate", "unable to allocate")
# With no previous load to go by, assume about this long; the tensor upload logs nothing for minutes.
FIRST_LOAD_GUESS_SECONDS = 180
HEALTH_INTERVAL = 0.5
TICK = 0.1
TAIL_LINES = 200

ProgressFn = Callable[[float, "float | None"], None]


def parse_stage(line: str, current: float) -> float:
    return max([current] + [f for needle, f in LOAD_STAGES if needle in line])


class LoadEstimator:
    """Blends the log stage with how long the last load took (stages alone jump unevenly)."""

    def __init__(self, previous_seconds: float | None):
        self.previous = previous_seconds if previous_seconds and previous_seconds > 0 else None

    def fraction(self, stage_fraction: float, elapsed: float) -> float:
        expected = self.previous or FIRST_LOAD_GUESS_SECONDS
        return max(stage_fraction, min(0.97, elapsed / expected))

    def eta(self, elapsed: float) -> float | None:
        # Time left only from a real previous load, never from the first-load guess.
        if self.previous is None or elapsed >= self.previous:
            return None
        return self.previous - elapsed


class LlmStartError(Exception):
    """kind: "memory", "crash", "timeout" or "missing"; detail holds the log tail."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail[-500:]}" if detail else kind)
        self.kind, self.detail = kind, detail


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _classify(tail: str) -> str:
    low = tail.lower()
    return "memory" if any(m in low for m in MEMORY_ERRORS) else "crash"


class _Log:
    """What the reader thread has seen; kept apart from LlamaServer so the thread doesn't keep it alive."""

    def __init__(self):
        self.tail: deque[str] = deque(maxlen=TAIL_LINES)
        self.stage = 0.0

    def text(self) -> str:
        return "\n".join(self.tail)


def _read_log(stream, log: _Log) -> None:
    try:
        for line in stream:
            line = line.rstrip()
            log.tail.append(line)
            log.stage = parse_stage(line, log.stage)
    except (OSError, ValueError):
        pass
    finally:
        stream.close()


def _stop_process(proc: subprocess.Popen, reader: threading.Thread | None) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    if reader is not None:
        reader.join(5)


# Every started server, so the app never exits leaving one running.
_servers: "weakref.WeakSet[LlamaServer]" = weakref.WeakSet()


def _stop_all() -> None:
    for server in list(_servers):
        server.stop()


atexit.register(_stop_all)


class LlamaServer:
    def __init__(self, binary: Path, model: Path, gpu: bool, ctx: int = 8192):
        self.binary, self.model, self.gpu, self.ctx = Path(binary), Path(model), gpu, ctx
        self.port = 0
        self.pid: int | None = None
        self.load_seconds: float | None = None
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._ready = False
        self._finalizer: weakref.finalize | None = None
        self._lock = threading.Lock()

    def command(self) -> list[str]:
        cmd = [str(self.binary), "-m", str(self.model), "-c", str(self.ctx),
               "--host", "127.0.0.1", "--port", str(self.port), "--jinja",
               "-lv", "4"]   # the loading stages are only logged at verbosity 4
        # On the graphics card llama-server fits as many layers as free memory allows by itself.
        return cmd if self.gpu else cmd + ["-ngl", "0"]

    def start(self, on_progress: ProgressFn, cancel: threading.Event, timeout: float = 1800,
              previous_seconds: float | None = None) -> None:
        if not self.binary.is_file():
            raise LlmStartError("missing", str(self.binary))
        self.stop()
        self.port = _free_port()
        windows = sys.platform == "win32"
        kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if windows else {}
        log = _Log()
        try:
            proc = subprocess.Popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace", **kw)
        except OSError as e:   # a build that can't even be executed is as broken as one that crashes
            raise LlmStartError("crash", str(e)) from e
        reader = threading.Thread(target=_read_log, args=(proc.stdout, log), daemon=True)
        reader.start()
        with self._lock:
            self._proc, self._reader, self.pid = proc, reader, proc.pid
            # A server collected without stop() still takes its process down with it.
            self._finalizer = weakref.finalize(self, _stop_process, proc, reader)
        _servers.add(self)
        try:
            self._wait_ready(proc, reader, log, on_progress, cancel, timeout, LoadEstimator(previous_seconds))
        except BaseException:
            self.stop()   # cancelled, failed, or on_progress raised: never leave it running
            raise

    def _wait_ready(self, proc, reader, log, on_progress, cancel, timeout, estimator) -> None:
        url = f"http://127.0.0.1:{self.port}/health"
        t0 = time.monotonic()
        next_health, shown, reported = t0, -1.0, t0
        # Poll instead of blocking, so cancelling or closing the window stops loading promptly.
        with local_client(2) as client:
            while True:
                # stop() from another thread (e.g. the app closing) is a cancel, not a crash to fall back from.
                if cancel.is_set() or self._proc is not proc:
                    raise DownloadCancelled()
                if proc.poll() is not None:
                    reader.join(5)   # let it drain the last lines (the error) first
                    raise LlmStartError(_classify(log.text()), log.text())
                now = time.monotonic()
                elapsed = now - t0
                if elapsed > timeout:
                    raise LlmStartError("timeout", log.text())
                if now >= next_health:
                    next_health = now + HEALTH_INTERVAL
                    if _healthy(client, url):
                        self.load_seconds = elapsed
                        self._ready = True
                        on_progress(1.0, 0.0)
                        return
                fraction = max(shown, estimator.fraction(log.stage, elapsed))
                # Report each step forward, and once a second so the time left keeps counting down.
                if fraction > shown or now - reported >= 1:
                    shown, reported = fraction, now
                    on_progress(fraction, estimator.eta(elapsed))
                time.sleep(TICK)

    def is_ready(self) -> bool:
        proc = self._proc
        return self._ready and proc is not None and proc.poll() is None

    def stop(self) -> None:
        with self._lock:
            proc, reader, self._proc, self._reader = self._proc, self._reader, None, None
            finalizer, self._finalizer = self._finalizer, None
            self._ready = False
        if finalizer is not None:
            finalizer.detach()
        if proc is not None:
            _stop_process(proc, reader)
        _servers.discard(self)


def local_client(timeout: float) -> httpx.Client:
    """An httpx client for the server on 127.0.0.1: ignores proxy settings, which would misroute it."""
    return httpx.Client(timeout=timeout, trust_env=False)


def _healthy(client: httpx.Client, url: str) -> bool:
    try:
        r = client.get(url)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


def start_with_fallback(settings: Settings, on_progress: ProgressFn, cancel: threading.Event,
                        on_fallback: Callable[[], None]) -> LlamaServer:
    """Start on the graphics card; if that build crashes or is missing, use the CPU build once."""
    model = Path(settings.llm_model_path) if settings.llm_model_path else None
    if model is None or not model.is_file():
        raise LlmStartError("missing", str(model))
    backend = settings.llm_backend or "cpu"
    previous = settings.llm_load_seconds
    if backend != "cpu":
        gpu_binary = server_binary(backend)
        if gpu_binary is not None:
            server = LlamaServer(gpu_binary, model, gpu=True)
            try:
                server.start(on_progress, cancel, previous_seconds=previous)
            except LlmStartError as e:
                # Out of memory on the card would be no better on the CPU route, which needs at least as much.
                if e.kind != "crash":
                    raise
            else:
                settings.llm_load_seconds = server.load_seconds
                return server
        on_fallback()
    cpu_binary = server_binary("cpu")   # on macOS this is the Metal build, run with -ngl 0
    if cpu_binary is None:
        raise LlmStartError("missing", "no CPU build of llama-server")
    server = LlamaServer(cpu_binary, model, gpu=False)
    server.start(on_progress, cancel, previous_seconds=previous)
    settings.llm_load_seconds = server.load_seconds
    return server
