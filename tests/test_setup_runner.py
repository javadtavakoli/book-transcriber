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

    def extract_nvidia_libs(self, wheel, gpu_dir, windows):
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
              sources=FakeSources(), selftest=lambda path, device: got.append((path, device)))
    assert got == [(str(paths.models_dir() / "faster-whisper-large-v3"), "cpu")]


def test_selftest_error_propagates():
    def bad(*a):
        raise SetupError("gpu", "x")
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None), Settings(), no_test, threading.Event(), downloader=fake_dl,
                  sources=FakeSources(), selftest=bad)
    assert e.value.kind == "gpu"
