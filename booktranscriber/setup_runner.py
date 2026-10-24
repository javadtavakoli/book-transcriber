"""First-run setup: download what this machine needs, with one aggregated progress stream."""
import dataclasses
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from . import llm_sources, paths, setup_sources
from .downloader import ChecksumError, DownloadCancelled, NetworkError, download_file
from .llm_catalog import MODELS, choose_backend, choose_llm
from .settings import Settings
from .syscheck import WHISPER_REPOS, SystemInfo, choose_whisper_model, current_os, is_nvidia

ITEMS = ("check", "gpu", "whisper", "llm", "test")
GB = 1_000_000_000
GPU_ESTIMATE = int(1.6 * GB)
MODEL_ESTIMATE = {"large-v3": int(3.1 * GB), "large-v3-turbo": int(1.7 * GB)}
LLM_RUNTIME_ESTIMATE = 60_000_000   # the runtime archives, ahead of the exact sizes
SELFTEST_TIMEOUT = 600


class SetupError(Exception):
    def __init__(self, kind: str, message: str = "", needed: int = 0, free: int = 0,
                 fits_without_llm: bool = False, item: str | None = None):
        super().__init__(message or kind)
        self.kind, self.needed, self.free = kind, needed, free
        self.fits_without_llm = fits_without_llm    # the space is enough if the optional helper is skipped
        self.item = item    # the setup item (ITEMS) being fetched when it failed, if any


@dataclass
class SetupPlan:
    info: SystemInfo
    include_gpu: bool
    whisper_model: str
    reuse_model_path: Path | None
    needed_bytes: int
    include_llm: bool = False
    llm_model: str | None = None
    llm_backend: str = "vulkan"


@dataclass
class SetupProgress:
    item: str
    item_done: int
    item_total: int
    overall_done: int
    overall_total: int
    bytes_per_sec: float
    eta_seconds: float | None


def make_plan(info: SystemInfo, existing: Path | None, include_llm: bool | None = None) -> SetupPlan:
    include_gpu = info.os != "macos" and is_nvidia(info)
    model = choose_whisper_model(info)
    llm_model, recommended = choose_llm(info)
    include_llm = recommended if include_llm is None else include_llm
    needed = (GPU_ESTIMATE if include_gpu else 0) + (0 if existing else MODEL_ESTIMATE[model])
    if include_llm:
        needed += MODELS[llm_model].size + LLM_RUNTIME_ESTIMATE
    return SetupPlan(info, include_gpu, model, existing, int(needed * 1.1),
                     include_llm, llm_model, choose_backend(info))


def model_dir_for(model: str) -> Path:
    return paths.models_dir() / WHISPER_REPOS[model].split("/")[1]


def run_selftest(model_path: str, device: str, lib_dirs: list[str] | None = None,
                 cancel: threading.Event | None = None) -> None:
    """Transcribe a moment of noise in a worker process, exactly as a real job would run."""
    from .protocol import decode
    from .worker import worker_command, worker_env
    windows = sys.platform == "win32"
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if windows else {}
    log = paths.logs_dir() / "selftest.log"
    with open(log, "w+", encoding="utf-8", errors="replace") as out:
        proc = subprocess.Popen(worker_command(["--selftest", "--model", model_path, "--device", device]),
                                env=worker_env(lib_dirs), stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, **kw)
        deadline = time.monotonic() + SELFTEST_TIMEOUT
        # Poll instead of blocking, so Pause and closing the window stop the test promptly.
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.wait()
                raise SetupError("cancelled")
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                raise SetupError("test", "self-test timed out")
            time.sleep(0.2)
        out.seek(0)
        text = out.read()
    events = [e for e in map(decode, text.splitlines()) if e]
    if proc.returncode == 0 and events and events[-1]["type"] == "done":
        return
    kind = next((e["kind"] for e in events if e["type"] == "error"), None)
    # No error event and an abnormal exit means a native crash; on the graphics card that is
    # almost always the GPU libraries, so offer "continue without graphics card".
    crashed = kind is None and (proc.returncode < 0 or proc.returncode > 128)
    gpu_problem = kind == "model" or crashed
    raise SetupError("gpu" if gpu_problem and device != "cpu" else "test", text[-2000:])


class _Meter:
    """Overall progress plus speed over the last few seconds."""

    def __init__(self, total: int, on_progress):
        self.total, self.on_progress, self.base = total, on_progress, 0
        self.window = deque()

    def report(self, item: str, item_done: int, item_total: int, file_done: int = 0):
        done = min(self.base + file_done, self.total)
        now = time.monotonic()
        self.window.append((now, done))
        while self.window and now - self.window[0][0] > 5:
            self.window.popleft()
        t0, d0 = self.window[0]
        speed = (done - d0) / (now - t0) if now > t0 else 0.0
        eta = (self.total - done) / speed if speed > 0 else None
        self.on_progress(SetupProgress(item, item_done, item_total, done, self.total, speed, eta))


def run_setup(plan: SetupPlan, settings: Settings, on_progress: Callable[[SetupProgress], None],
              cancel: threading.Event, *, downloader=download_file, sources=setup_sources,
              selftest=run_selftest, llm=llm_sources) -> Settings:
    gpu_dir = paths.gpu_dir()
    try:
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            gpu_files = sources.gpu_wheel_files(plan.info.os, gpu_dir, client) if plan.include_gpu else []
        model_path = plan.reuse_model_path or model_dir_for(plan.whisper_model)
        model_files = [] if plan.reuse_model_path else sources.model_files(WHISPER_REPOS[plan.whisper_model], model_path)
    except (httpx.HTTPError, OSError) as e:
        raise SetupError("network", str(e)) from e
    except LookupError as e:
        raise SetupError("gpu", str(e)) from e

    def extract_wheel(f):
        try:
            sources.extract_nvidia_libs(f.dest, gpu_dir, plan.info.os == "windows", cancel)
        except DownloadCancelled as e:
            raise SetupError("cancelled") from e
        _marker(f).write_text("ok")

    steps = [_Step("gpu", f, _marker(f).exists(), extract_wheel, unpack=True) for f in gpu_files]
    steps += [_Step("whisper", f) for f in model_files]
    if plan.include_llm:
        steps += _llm_steps(plan.info.os, plan.llm_model, plan.llm_backend, llm, cancel)
    meter = _fetch(steps, on_progress, cancel, downloader, check=True, llm_optional=True)
    meter.report("test", 0, 1)
    selftest(str(model_path), settings.device, cancel=cancel)
    meter.report("test", 1, 1)
    done = dataclasses.replace(settings, setup_done=True, whisper_model=plan.whisper_model,
                               whisper_model_path=str(model_path))
    return _with_llm(done, plan.llm_model, plan.llm_backend, llm) if plan.include_llm else done


def run_llm_setup(model_key: str, backend: str, settings: Settings, on_progress: Callable[[SetupProgress], None],
                  cancel: threading.Event, *, downloader=download_file, llm=llm_sources) -> Settings:
    """Just the local AI helper's downloads, for people who skipped it during setup."""
    _fetch(_llm_steps(current_os(), model_key, backend, llm, cancel), on_progress, cancel, downloader)
    return _with_llm(settings, model_key, backend, llm)


def _with_llm(settings: Settings, model_key: str, backend: str, llm) -> Settings:
    return dataclasses.replace(settings, llm_model=model_key, llm_backend=backend,
                               llm_model_path=str(llm.model_file(model_key).dest))


@dataclass
class _Step:
    item: str
    file: object
    skip: bool = False          # already in place from an earlier run
    after: Callable | None = None   # runs once the file has arrived (unpack the archive)
    unpack: bool = False        # needs room to unpack next to itself


def _llm_steps(os_name: str, model_key: str, backend: str, llm, cancel) -> list[_Step]:
    def unpacker(archive_backend):
        def extract(f):
            try:
                llm.extract_archive(Path(f.dest), llm.runtime_dir(archive_backend), cancel)
            except DownloadCancelled as e:
                raise SetupError("cancelled") from e
            except (OSError, RuntimeError, tarfile.TarError, zipfile.BadZipFile) as e:
                raise SetupError("disk" if getattr(e, "errno", None) == 28 else "network", str(e)) from e
        return extract
    steps = [_Step("llm", f, llm.server_binary(b) is not None, unpacker(b), unpack=True)
             for b, f in llm.runtime_files(os_name, backend)]
    return steps + [_Step("llm", llm.model_file(model_key))]


def _fetch(steps: list[_Step], on_progress, cancel, downloader, check: bool = False,
           llm_optional: bool = False) -> "_Meter":
    """Download every step in order under one overall meter, checking disk space first."""
    total = sum(st.file.size for st in steps)
    # Only what is still to arrive counts (a resumed download already has part of it on disk),
    # plus room to unpack each pending archive next to itself.
    def room(chosen):
        pending = [st for st in chosen if not st.skip]
        return sum(_left(st.file) for st in pending) + sum(st.file.size for st in pending if st.unpack)
    needed = room(steps)
    free = shutil.disk_usage(paths.data_dir()).free
    if free < needed:
        fits = llm_optional and room([st for st in steps if st.item != "llm"]) <= free
        raise SetupError("disk", needed=needed, free=free, fits_without_llm=fits)

    meter = _Meter(total, on_progress)
    if check:
        meter.report("check", 1, 1)
    for item in dict.fromkeys(st.item for st in steps):
        group = [st for st in steps if st.item == item]
        item_total = sum(st.file.size for st in group)
        item_base = meter.base
        for st in group:
            f = st.file
            if not st.skip:
                def prog(n, f=f):
                    meter.report(item, meter.base - item_base + n, item_total, n)
                try:
                    _download(downloader, f, prog, cancel)
                    if st.after:
                        st.after(f)
                except SetupError as e:
                    e.item = e.item or item     # so a failed optional helper can be skipped
                    raise
            meter.base += f.size
        meter.report(item, item_total, item_total)
    return meter


def _left(f) -> int:
    dest = Path(f.dest)
    if dest.exists():
        return 0
    part = dest.with_name(dest.name + ".part")
    return max(f.size - (part.stat().st_size if part.exists() else 0), 0)


def _marker(f) -> Path:
    return Path(f.dest).with_name(Path(f.dest).name + ".done")


def _download(downloader, f, prog, cancel) -> None:
    try:
        downloader(f.url, f.dest, f.size, f.sha256, prog, cancel)
    except NetworkError as e:
        raise SetupError("network", str(e)) from e
    except ChecksumError as e:
        raise SetupError("checksum", str(e)) from e
    except DownloadCancelled as e:
        raise SetupError("cancelled") from e
    except OSError as e:
        raise SetupError("disk" if e.errno == 28 else "network", str(e)) from e
