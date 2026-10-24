"""Bridges from Qt to the long-running work: the worker process and first-run setup."""
import os
import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QThread, Signal

from .. import paths
from ..protocol import decode
from ..worker import worker_command, worker_env

STDERR_TAIL = 40


@dataclass
class TranscribeJob:
    audio: str
    out: str
    model: str
    download_root: str | None
    language: str
    prompt: str | None
    timestamps: bool
    device: str

    def args(self) -> list[str]:
        a = ["--audio", self.audio, "--out", self.out, "--model", self.model,
             "--language", self.language, "--device", self.device]
        if self.download_root:
            a += ["--download-root", self.download_root]
        if self.prompt:
            a += ["--prompt", self.prompt]
        if self.timestamps:
            a.append("--timestamps")
        return a


class TranscribeRunner(QObject):
    loaded = Signal(str)
    duration = Signal(float)
    segment = Signal(float, str)
    progress = Signal(float, float, float)
    finished = Signal(str, int)
    failed = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._job: TranscribeJob | None = None
        self._buf = b""
        self._stderr: list[str] = []
        self._ended = False

    def is_running(self) -> bool:
        # The job is over once its final event arrives, even if the process takes a moment to exit.
        return not self._ended and self._proc is not None and self._proc.state() != QProcess.NotRunning

    def start(self, job: TranscribeJob) -> None:
        self._job, self._buf, self._stderr, self._ended = job, b"", [], False
        cmd = worker_command(job.args())
        p = QProcess(self)
        env = QProcessEnvironment()
        for k, v in worker_env().items():
            env.insert(k, v)
        p.setProcessEnvironment(env)
        p.readyReadStandardOutput.connect(self._on_stdout)
        p.readyReadStandardError.connect(self._on_stderr)
        p.finished.connect(self._on_finished)
        self._proc = p
        p.start(cmd[0], cmd[1:])

    def cancel(self) -> None:
        p, self._proc = self._proc, None
        self._ended = True
        if p is not None and p.state() != QProcess.NotRunning:
            p.kill()
            p.waitForFinished(5000)
        if self._job:
            part = self._job.out + ".part"
            if os.path.exists(part):
                os.remove(part)

    def _on_stdout(self) -> None:
        if self._proc is None:
            return
        self._buf += bytes(self._proc.readAllStandardOutput())
        *lines, self._buf = self._buf.split(b"\n")
        for raw in lines:
            ev = decode(raw.decode("utf-8", errors="replace"))
            if ev:
                self._dispatch(ev)

    def _dispatch(self, ev: dict) -> None:
        t = ev["type"]
        if t == "loaded":
            self.loaded.emit(ev.get("backend", ""))
        elif t == "duration":
            self.duration.emit(float(ev["seconds"]))
        elif t == "segment":
            self.segment.emit(float(ev["start"]), ev["text"])
        elif t == "progress":
            self.progress.emit(float(ev["done"]), float(ev["total"]), float(ev["eta"]))
        elif t == "done":
            self._ended = True
            self.finished.emit(ev["out"], int(ev["segments"]))
        elif t == "error":
            self._ended = True
            self.failed.emit(ev.get("kind", "unknown"), ev.get("message", ""))

    def _on_stderr(self) -> None:
        if self._proc is None:
            return
        text = bytes(self._proc.readAllStandardError()).decode("utf-8", errors="replace")
        with open(paths.logs_dir() / "worker.log", "a", encoding="utf-8") as f:
            f.write(text)
        self._stderr = (self._stderr + text.splitlines())[-STDERR_TAIL:]

    def _on_finished(self, code, status) -> None:
        if self._proc is not None:
            self._on_stdout()
            self._on_stderr()
        if not self._ended:
            self._ended = True
            self.failed.emit("unknown", "\n".join(self._stderr))
        self._proc = None


class _SetupThread(QThread):
    progress = Signal(object)
    done = Signal(object)
    error = Signal(str)

    def __init__(self, plan, settings, cancel):
        super().__init__()
        self.plan, self.settings, self.cancel = plan, settings, cancel

    def run(self):
        from ..setup_runner import SetupError, run_setup
        try:
            self.done.emit(run_setup(self.plan, self.settings, self.progress.emit, self.cancel))
        except SetupError as e:
            self.error.emit(e.kind)
        except Exception:
            import traceback
            (paths.logs_dir() / "setup.log").write_text(traceback.format_exc(), "utf-8")
            self.error.emit("test")


class SetupRunner(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: _SetupThread | None = None
        self._cancel = threading.Event()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, plan, settings) -> None:
        self._cancel = threading.Event()
        t = _SetupThread(plan, settings, self._cancel)
        t.progress.connect(self.progress)
        t.done.connect(self.finished)
        t.error.connect(self.failed)
        self._thread = t
        t.start()

    def pause(self) -> None:
        self._cancel.set()

    def stop_and_wait(self, ms: int = 10000) -> None:
        self._cancel.set()
        if self._thread is not None:
            self._thread.wait(ms)
