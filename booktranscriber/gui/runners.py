"""Bridges from Qt to the long-running work: the worker process, first-run setup and the local AI helper."""
import os
import threading
from dataclasses import dataclass

import shiboken6
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QThread, Signal

from .. import paths
from ..downloader import DownloadCancelled
from ..llm_server import LlmStartError, start_with_fallback
from ..local_fix import chunk_lines, fix_transcript
from ..protocol import decode
from ..settings import save_settings
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
        self._stop_process()        # a previous worker may still be shutting down
        self._job, self._buf, self._stderr, self._ended = job, b"", [], False
        cmd = worker_command(job.args())
        p = QProcess(self)
        env = QProcessEnvironment()
        for k, v in worker_env().items():
            env.insert(k, v)
        p.setProcessEnvironment(env)
        # Every handler checks sender() is still the current process, so a late signal from
        # an old worker can never affect the job that replaced it.
        p.readyReadStandardOutput.connect(self._on_stdout)
        p.readyReadStandardError.connect(self._on_stderr)
        p.finished.connect(self._on_finished)
        p.errorOccurred.connect(self._on_error)
        self._proc = p
        p.start(cmd[0], cmd[1:])

    def _current(self) -> bool:
        # Also false while Qt is destroying the process (e.g. the window closing).
        p = self.sender()
        return p is not None and p is self._proc and shiboken6.isValid(p)

    def _stop_process(self) -> None:
        p, self._proc = self._proc, None
        if p is not None:
            if p.state() != QProcess.NotRunning:
                p.kill()
                p.waitForFinished(5000)
            p.disconnect(self)
            p.deleteLater()

    def cancel(self) -> None:
        self._ended = True
        self._stop_process()
        if self._job:
            part = self._job.out + ".part"
            if os.path.exists(part):
                os.remove(part)

    def _on_stdout(self) -> None:
        if self._current():
            self._read_stdout()

    def _read_stdout(self) -> None:
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
        if self._current():
            self._read_stderr()

    def _read_stderr(self) -> None:
        text = bytes(self._proc.readAllStandardError()).decode("utf-8", errors="replace")
        with open(paths.logs_dir() / "worker.log", "a", encoding="utf-8") as f:
            f.write(text)
        self._stderr = (self._stderr + text.splitlines())[-STDERR_TAIL:]

    def _on_finished(self, code, status) -> None:
        if not self._current():
            return
        p = self._proc
        self._read_stdout()
        self._read_stderr()
        if not self._ended:
            # Died without telling us why. A crash while using the graphics card is most
            # likely the GPU libraries, so offer the CPU route; otherwise a generic error.
            crashed = status == QProcess.CrashExit or code < 0 or code > 128
            on_gpu = self._job is not None and self._job.device != "cpu"
            self._ended = True
            self.failed.emit("model" if crashed and on_gpu else "unknown", "\n".join(self._stderr))
        self._proc = None
        p.deleteLater()

    def _on_error(self, err) -> None:
        # FailedToStart never reaches finished(); other errors are followed by it.
        if self._current() and err == QProcess.FailedToStart and not self._ended:
            p = self._proc
            self._ended = True
            self._proc = None
            p.deleteLater()
            self.failed.emit("unknown", p.errorString())


class _SetupThread(QThread):
    progress = Signal(object)
    done = Signal(object)
    error = Signal(object)      # SetupError

    def __init__(self, plan, settings, cancel, llm=None):
        super().__init__()
        self.plan, self.settings, self.cancel = plan, settings, cancel
        self.llm = llm      # (model key, backend): only the AI helper's downloads

    def run(self):
        from ..setup_runner import SetupError, run_llm_setup, run_setup
        try:
            if self.llm is not None:
                self.done.emit(run_llm_setup(*self.llm, self.settings, self.progress.emit, self.cancel))
            else:
                self.done.emit(run_setup(self.plan, self.settings, self.progress.emit, self.cancel))
        except SetupError as e:
            self.error.emit(e)
        except Exception:
            import traceback
            (paths.logs_dir() / "setup.log").write_text(traceback.format_exc(), "utf-8")
            self.error.emit(SetupError("test"))


class SetupRunner(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: _SetupThread | None = None
        self._cancel = threading.Event()
        self.last_error = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, plan, settings) -> None:
        self._start(_SetupThread(plan, settings, self._new_cancel()))

    def start_llm(self, model_key: str, backend: str, settings) -> None:
        """Download just the local AI helper (for people who skipped it during setup)."""
        self._start(_SetupThread(None, settings, self._new_cancel(), llm=(model_key, backend)))

    def _new_cancel(self) -> threading.Event:
        self.stop_and_wait()    # never drop a thread that is still running
        self._cancel = threading.Event()
        return self._cancel

    def _start(self, t: _SetupThread) -> None:
        self.last_error = None
        t.progress.connect(self.progress)
        t.done.connect(self.finished)
        t.error.connect(self._on_error)
        self._thread = t
        t.start()

    def _on_error(self, err) -> None:
        self.last_error = err
        self.failed.emit(err.kind)

    def pause(self) -> None:
        self._cancel.set()

    def stop_and_wait(self) -> None:
        """Every setup step checks the cancel flag (downloads within the read timeout), so this
        returns promptly. Waiting without a deadline means Qt never destroys a running thread."""
        self._cancel.set()
        if self._thread is not None:
            self._thread.wait()


class _LocalFixThread(QThread):
    load_progress = Signal(float, object)
    fallback = Signal()
    loaded = Signal()
    fix_progress = Signal(int, int)
    done = Signal(object)
    error = Signal(str)

    def __init__(self, runner, lines, names, settings, cancel):
        super().__init__()
        self.runner, self.lines, self.names, self.settings, self.cancel = runner, lines, names, settings, cancel

    def run(self):
        r = self.runner
        try:
            server = r._server
            if server is None or not server.is_ready():
                if server is not None:
                    server.stop()       # it died since the last job
                server = self._load()
            fixes = fix_transcript(self.lines, self.names, server.port, self.fix_progress.emit, self.cancel)
            if self.cancel.is_set():    # stopped during the last part: the answers may be cut short
                raise DownloadCancelled()
            unanswered = {f.n for f in fixes if f.reason == "missing"}
            if unanswered and server.gpu and server.exited(wait=1):
                # The graphics card's build crashed while answering (spec §5.2): the processor for the
                # rest of this session, and the lines it never answered once more there.
                r.gpu_failed = True
                server.stop()
                server = self._load()
                fixes = self._fix_again(fixes, unanswered, server)
                if self.cancel.is_set():
                    raise DownloadCancelled()
            spoken = [f for f in fixes if f.original]
            if spoken and all(f.reason == "missing" for f in spoken):
                # Not a single answer (every request failed): an error to retry, not an empty review.
                self.error.emit("unknown" if server.is_ready() else "crash")
                return
            self.done.emit(fixes)
        except DownloadCancelled:
            self.error.emit("cancelled")
        except LlmStartError as e:
            _write_log("llm.log", f"{e.kind}\n{e.detail}")
            self.error.emit(e.kind)
        except Exception:
            import traceback
            _write_log("llm.log", traceback.format_exc())
            self.error.emit("unknown")

    def _load(self):
        r = self.runner
        server = start_with_fallback(self.settings, self.load_progress.emit, self.cancel, self.fallback.emit,
                                     use_gpu=not r.gpu_failed)
        # Set before fixing, so stop_server() can reach it. A cancelled job still winding
        # down may have loaded one just now too: keep a single helper.
        with r._server_lock:
            if r._server is not None and r._server is not server and r._server.is_ready():
                server.stop()
                server = r._server
            else:
                r._server = server
        self.loaded.emit()
        return server

    def _fix_again(self, fixes, numbers: set[int], server):
        """Fix just the given lines (the others blanked out), and merge them into fixes."""
        lines = [line if n in numbers else "" for n, line in enumerate(self.lines, 1)]
        total = len(chunk_lines(self.lines))
        # Parts count on from those already answered, so the counter never goes back.
        again = fix_transcript(lines, self.names, server.port,
                               lambda done, n: self.fix_progress.emit(total - n + done, total), self.cancel)
        return [new if f.n in numbers else f for f, new in zip(fixes, again)]


def _write_log(name: str, text: str) -> None:
    try:
        (paths.logs_dir() / name).write_text(text, "utf-8")
    except OSError:
        pass


class LocalFixRunner(QObject):
    """Loads the local AI helper (once per session) and fixes a transcript with it, off the GUI thread."""
    load_progress = Signal(float, object)   # fraction, seconds left or None
    fallback = Signal()
    fix_progress = Signal(int, int)
    finished = Signal(object)               # list[LineFix]
    failed = Signal(str)                    # memory, crash, timeout, missing, cancelled, unknown

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: _LocalFixThread | None = None
        self._winding_down: list[_LocalFixThread] = []   # cancelled jobs finishing their current part
        self._cancel = threading.Event()
        self._server = None     # the LlamaServer, kept loaded between jobs
        self._server_lock = threading.Lock()
        self._settings = None
        self._live = False      # the current job's results are still wanted
        self.gpu_failed = False     # the graphics card's build crashed while fixing: the processor from now on

    def is_running(self) -> bool:
        return self._live and self._thread is not None and self._thread.isRunning()

    def server_loaded(self) -> bool:
        s = self._server
        return s is not None and s.is_ready()

    def start(self, raw_lines: list[str], names: list[str], settings) -> None:
        if self._thread is not None:
            self._cancel.set()
            # A cancelled job finishes its current part first (a minute on the processor); let it,
            # rather than freeze the window. Its late results are dropped.
            self._winding_down = [t for t in self._winding_down if t.isRunning()]
            if self._thread.isRunning():
                self._winding_down.append(self._thread)
        self._cancel = threading.Event()
        self._settings, self._live = settings, True
        t = _LocalFixThread(self, list(raw_lines), list(names), settings, self._cancel)
        # Each handler checks the signal comes from the current job, so a stopped job's late
        # results never reach the screen.
        t.load_progress.connect(self._on_load_progress)
        t.fallback.connect(self._on_fallback)
        t.loaded.connect(self._on_loaded)
        t.fix_progress.connect(self._on_fix_progress)
        t.done.connect(self._on_done)
        t.error.connect(self._on_error)
        self._thread = t
        t.start()

    def cancel(self) -> None:
        """Stop the current job; the helper stays loaded for the next one."""
        self._live = False
        self._cancel.set()

    def stop_server(self) -> None:
        """Stop the job and the helper, freeing the graphics memory. Safe whether idle, loading or fixing."""
        self.cancel()
        if self._server is not None:
            self._server.stop()     # an answer being waited for fails at once
        for t in [*self._winding_down, self._thread]:
            if t is not None:
                t.wait()            # loading and fixing both check the cancel flag
        self._winding_down = []
        # Loading may have finished just before the cancel arrived.
        if self._server is not None:
            self._server.stop()
        self._server = None

    def _current(self) -> bool:
        return self._live and self.sender() is self._thread

    def _on_load_progress(self, fraction: float, eta) -> None:
        if self._current():
            self.load_progress.emit(fraction, eta)

    def _on_fallback(self) -> None:
        if self._current():
            self.fallback.emit()

    def _on_loaded(self) -> None:
        # How long loading took is remembered, so next time the bar can show the time left.
        if self.sender() is self._thread and self._settings is not None:
            save_settings(self._settings, paths.settings_file())

    def _on_fix_progress(self, done: int, total: int) -> None:
        if self._current():
            self.fix_progress.emit(done, total)

    def _on_done(self, fixes) -> None:
        if self._current():
            self._live = False
            self.finished.emit(fixes)

    def _on_error(self, kind: str) -> None:
        if self._current():
            self._live = False
            self.failed.emit(kind)
