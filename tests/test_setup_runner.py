import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from booktranscriber import paths
from booktranscriber.downloader import DownloadCancelled, NetworkError
from booktranscriber.settings import Settings
from booktranscriber.setup_runner import SetupError, make_plan, run_setup
from booktranscriber.setup_sources import RemoteFile
from booktranscriber.syscheck import GpuInfo, SystemInfo

GPU_INFO = SystemInfo("linux", GpuInfo("RTX", 6141), 10**12)


def test_make_plan_no_gpu():
    p = make_plan(SystemInfo("linux", None, 10**12), existing=None)
    assert not p.include_gpu and p.whisper_model == "large-v3-turbo" and p.reuse_model_path is None


def test_make_plan_reuse():
    p = make_plan(GPU_INFO, existing=Path("/m"))
    assert p.include_gpu and p.whisper_model == "large-v3" and p.reuse_model_path == Path("/m")
    assert p.needed_bytes < make_plan(GPU_INFO, existing=None).needed_bytes


def test_make_plan_macos_never_gpu():
    assert not make_plan(SystemInfo("macos", GpuInfo("x", 8000), 10**12), None).include_gpu


class FakeSources:
    def __init__(self, gpu_sizes=(100, 300), model_sizes=(600,)):
        self.gpu_sizes, self.model_sizes, self.extracted = gpu_sizes, model_sizes, []

    def gpu_wheel_files(self, os_name, gpu_dir, client):
        return [RemoteFile(f"u{i}", s, None, gpu_dir / "wheels" / f"w{i}.whl") for i, s in enumerate(self.gpu_sizes)]

    def model_files(self, repo_id, dest_dir):
        return [RemoteFile(f"m{i}", s, None, dest_dir / f"f{i}") for i, s in enumerate(self.model_sizes)]

    def extract_nvidia_libs(self, wheel, gpu_dir, windows, cancel=None):
        self.extracted.append(wheel.name)
        Path(wheel).unlink()
        return []


def fake_dl(url, dest, size, sha256, on_progress, cancel, client=None):
    on_progress(size // 2)
    on_progress(size)
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_bytes(b"x")


def no_test(*a, **k):
    pass


def test_progress_aggregates_and_finishes():
    seen = []
    src = FakeSources()
    s = run_setup(make_plan(GPU_INFO, None), Settings(), seen.append, threading.Event(),
                  downloader=fake_dl, sources=src, selftest=no_test)
    assert seen[-1].overall_done == seen[-1].overall_total == 1000
    overall = [p.overall_done for p in seen]
    assert overall == sorted(overall)
    assert {p.item for p in seen} >= {"check", "gpu", "whisper", "test"}
    assert s.setup_done and s.whisper_model == "large-v3"
    assert Path(s.whisper_model_path) == paths.models_dir() / "faster-whisper-large-v3"
    assert src.extracted == ["w0.whl", "w1.whl"]


def test_rerun_skips_extracted_wheels():
    src = FakeSources()
    run_setup(make_plan(GPU_INFO, None), Settings(), no_test, threading.Event(), downloader=fake_dl, sources=src, selftest=no_test)
    calls = []

    def counting_dl(url, *a, **k):
        calls.append(url)
        fake_dl(url, *a, **k)
    run_setup(make_plan(GPU_INFO, None), Settings(), no_test, threading.Event(), downloader=counting_dl, sources=src, selftest=no_test)
    assert not [c for c in calls if c.startswith("u")]


def test_reuse_skips_model_download(tmp_path):
    calls = []

    def dl(url, *a, **k):
        calls.append(url)
        fake_dl(url, *a, **k)
    s = run_setup(make_plan(GPU_INFO, tmp_path), Settings(), no_test, threading.Event(),
                  downloader=dl, sources=FakeSources(), selftest=no_test)
    assert calls == ["u0", "u1"] and s.whisper_model_path == str(tmp_path)


def test_disk_full():
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None), Settings(), no_test, threading.Event(),
                  downloader=lambda *a, **k: pytest.fail("no download"), sources=FakeSources(model_sizes=(10**15,)),
                  selftest=no_test)
    assert e.value.kind == "disk"


@pytest.mark.parametrize("exc,kind", [(NetworkError("x"), "network"), (DownloadCancelled(), "cancelled")])
def test_download_errors_map_kind(exc, kind):
    def dl(*a, **k):
        raise exc
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None), Settings(), no_test, threading.Event(), downloader=dl,
                  sources=FakeSources(), selftest=no_test)
    assert e.value.kind == kind


def test_selftest_runs_with_device_and_model_path():
    got = []
    run_setup(make_plan(GPU_INFO, None), Settings(device="cpu"), no_test, threading.Event(), downloader=fake_dl,
              sources=FakeSources(), selftest=lambda path, device, cancel=None: got.append((path, device)))
    assert got == [(str(paths.models_dir() / "faster-whisper-large-v3"), "cpu")]


def test_selftest_error_propagates():
    def bad(*a, **k):
        raise SetupError("gpu", "x")
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None), Settings(), no_test, threading.Event(), downloader=fake_dl,
                  sources=FakeSources(), selftest=bad)
    assert e.value.kind == "gpu"


def _fake_worker(monkeypatch, code):
    import sys

    from booktranscriber import worker
    monkeypatch.setattr(worker, "worker_command", lambda args: [sys.executable, "-c", code])


def test_selftest_cancel_kills_child_quickly(monkeypatch):
    import time

    from booktranscriber.setup_runner import run_selftest
    _fake_worker(monkeypatch, "import time; time.sleep(60)")
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    t0 = time.monotonic()
    with pytest.raises(SetupError) as e:
        run_selftest("/m", "cuda", lib_dirs=[], cancel=cancel)
    assert e.value.kind == "cancelled" and time.monotonic() - t0 < 5


@pytest.mark.parametrize("device,kind", [("cuda", "gpu"), ("auto", "gpu"), ("cpu", "test")])
def test_selftest_native_crash(monkeypatch, device, kind):
    from booktranscriber.setup_runner import run_selftest
    _fake_worker(monkeypatch, "import os; os.abort()")
    with pytest.raises(SetupError) as e:
        run_selftest("/m", device, lib_dirs=[])
    assert e.value.kind == kind


def test_run_setup_passes_cancel_to_selftest():
    got = []
    cancel = threading.Event()
    run_setup(make_plan(GPU_INFO, None), Settings(), no_test, cancel, downloader=fake_dl,
              sources=FakeSources(), selftest=lambda path, device, cancel=None: got.append(cancel))
    assert got == [cancel]


def test_disk_check_counts_only_what_is_left(monkeypatch):
    import shutil
    from collections import namedtuple

    from booktranscriber import setup_runner
    plan = make_plan(SystemInfo("linux", None, 10**12), None)      # no GPU libs, turbo model
    dest = setup_runner.model_dir_for(plan.whisper_model) / "f0"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.with_name("f0.part").write_bytes(b"x" * 500)               # 500 of 600 bytes already here
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10**6, 0, 150))
    s = run_setup(plan, Settings(), no_test, threading.Event(), downloader=fake_dl,
                  sources=FakeSources(gpu_sizes=(), model_sizes=(600,)), selftest=no_test)
    assert s.setup_done


def test_disk_error_reports_real_numbers(monkeypatch):
    import shutil
    from collections import namedtuple
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10**6, 0, 50))
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(SystemInfo("linux", None, 10**12), None), Settings(), no_test, threading.Event(),
                  downloader=fake_dl, sources=FakeSources(gpu_sizes=(), model_sizes=(600,)), selftest=no_test)
    assert (e.value.kind, e.value.needed, e.value.free) == ("disk", 600, 50)
