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
    s = run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(), seen.append, threading.Event(),
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
    run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(), no_test, threading.Event(), downloader=fake_dl, sources=src, selftest=no_test)
    calls = []

    def counting_dl(url, *a, **k):
        calls.append(url)
        fake_dl(url, *a, **k)
    run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(), no_test, threading.Event(), downloader=counting_dl, sources=src, selftest=no_test)
    assert not [c for c in calls if c.startswith("u")]


def test_reuse_skips_model_download(tmp_path):
    calls = []

    def dl(url, *a, **k):
        calls.append(url)
        fake_dl(url, *a, **k)
    s = run_setup(make_plan(GPU_INFO, tmp_path, include_llm=False), Settings(), no_test, threading.Event(),
                  downloader=dl, sources=FakeSources(), selftest=no_test)
    assert calls == ["u0", "u1"] and s.whisper_model_path == str(tmp_path)


def test_disk_full():
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(), no_test, threading.Event(),
                  downloader=lambda *a, **k: pytest.fail("no download"), sources=FakeSources(model_sizes=(10**15,)),
                  selftest=no_test)
    assert e.value.kind == "disk"


@pytest.mark.parametrize("exc,kind", [(NetworkError("x"), "network"), (DownloadCancelled(), "cancelled")])
def test_download_errors_map_kind(exc, kind):
    def dl(*a, **k):
        raise exc
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(), no_test, threading.Event(), downloader=dl,
                  sources=FakeSources(), selftest=no_test)
    assert e.value.kind == kind


def test_selftest_runs_with_device_and_model_path():
    got = []
    run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(device="cpu"), no_test, threading.Event(), downloader=fake_dl,
              sources=FakeSources(), selftest=lambda path, device, cancel=None: got.append((path, device)))
    assert got == [(str(paths.models_dir() / "faster-whisper-large-v3"), "cpu")]


def test_selftest_error_propagates():
    def bad(*a, **k):
        raise SetupError("gpu", "x")
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(), no_test, threading.Event(), downloader=fake_dl,
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
    run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(), no_test, cancel, downloader=fake_dl,
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


class FakeLlm:
    """Stands in for llm_sources: tiny archives, a tiny model, and an extraction that makes llama-server."""

    def __init__(self, archive_sizes=(200, 100), model_size=700):
        self.archive_sizes, self.model_size, self.extracted = archive_sizes, model_size, []

    def runtime_dir(self, backend):
        return paths.data_dir() / "llm" / f"fake-{backend}"

    def server_binary(self, backend):
        d = self.runtime_dir(backend)
        return d / "llama-server" if (d / ".done").exists() else None

    def runtime_files(self, os_name, backend):
        names = [backend, "cpu"] if os_name != "macos" else ["metal"]
        return [(b, RemoteFile(f"r{b}", s, None, paths.data_dir() / "llm" / "archives" / f"{b}.tar.gz"))
                for b, s in zip(names, self.archive_sizes)]

    def model_file(self, key):
        return RemoteFile(f"model-{key}", self.model_size, None, paths.data_dir() / "llm" / "models" / f"{key}.gguf")

    def extract_archive(self, archive, dest, cancel=None):
        if cancel is not None and cancel.is_set():
            raise DownloadCancelled()
        self.extracted.append((Path(archive).name, Path(dest).name))
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "llama-server").write_bytes(b"x")
        (Path(dest) / ".done").write_text("ok")
        Path(archive).unlink()


def test_plan_includes_llm_when_recommended():
    p = make_plan(GPU_INFO, None)                       # 6141 MiB meets the small tier
    assert p.include_llm and p.llm_model == "gemma-4-e4b" and p.llm_backend == "vulkan"
    assert make_plan(GPU_INFO, None, include_llm=False).needed_bytes < p.needed_bytes
    weak = make_plan(SystemInfo("linux", None, 10**12), None)
    assert not weak.include_llm
    assert make_plan(SystemInfo("linux", None, 10**12), None, include_llm=True).include_llm
    mac = make_plan(SystemInfo("macos", None, 10**12, ram_bytes=16 * 10**9), None)
    assert mac.llm_backend == "metal" and mac.include_llm


def test_run_setup_downloads_llm_and_sets_settings():
    seen, llm = [], FakeLlm()
    s = run_setup(make_plan(GPU_INFO, None), Settings(), seen.append, threading.Event(), downloader=fake_dl,
                  sources=FakeSources(), selftest=no_test, llm=llm)
    assert Path(s.llm_model_path).exists() and s.llm_model == "gemma-4-e4b" and s.llm_backend == "vulkan"
    assert [e[1] for e in llm.extracted] == ["fake-vulkan", "fake-cpu"]
    assert llm.server_binary("vulkan") and llm.server_binary("cpu")
    items = [p.item for p in seen]
    assert items.index("llm") > items.index("whisper") and items[-1] == "test"
    overall = [p.overall_done for p in seen]
    assert overall == sorted(overall) and seen[-1].overall_done == seen[-1].overall_total == 1000 + 1000
    assert s.setup_done


def test_run_setup_without_llm_skips_it():
    s = run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(), no_test, threading.Event(),
                  downloader=fake_dl, sources=FakeSources(), selftest=no_test,
                  llm=type("Boom", (), {"__getattr__": lambda self, n: pytest.fail("llm touched")})())
    assert s.llm_model is None and s.llm_model_path is None and s.llm_backend is None


def test_disk_check_includes_llm(monkeypatch):
    import shutil
    from collections import namedtuple
    Usage = namedtuple("Usage", "total used free")
    plan = make_plan(GPU_INFO, None)
    # whisper-only needs 1000 (gpu 400 + 400 unpack + 600 model - fits); the helper adds 700 + 2*(200+100)
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10**6, 0, 1400 + 700 + 599))
    with pytest.raises(SetupError) as e:
        run_setup(plan, Settings(), no_test, threading.Event(), downloader=fake_dl, sources=FakeSources(),
                  selftest=no_test, llm=FakeLlm())
    assert (e.value.kind, e.value.needed) == ("disk", 1400 + 700 + 600)


def test_llm_cancel_during_extract_maps_to_cancelled():
    cancel = threading.Event()

    def dl(url, dest, size, sha, prog, c, client=None):
        fake_dl(url, dest, size, sha, prog, c)
        if url.startswith("rvulkan"):
            cancel.set()
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None), Settings(), no_test, cancel, downloader=dl,
                  sources=FakeSources(), selftest=no_test, llm=FakeLlm())
    assert e.value.kind == "cancelled"


def test_run_llm_setup_alone():
    from booktranscriber.setup_runner import run_llm_setup
    seen, llm = [], FakeLlm()
    base = Settings(setup_done=True, whisper_model="large-v3", whisper_model_path="/w")
    s = run_llm_setup("gemma-4-e4b", "vulkan", base, seen.append, threading.Event(),
                      downloader=fake_dl, llm=llm)
    assert Path(s.llm_model_path).name == "gemma-4-e4b.gguf" and Path(s.llm_model_path).exists()
    assert (s.llm_model, s.llm_backend) == ("gemma-4-e4b", "vulkan")
    assert (s.whisper_model, s.whisper_model_path, s.setup_done) == ("large-v3", "/w", True)
    assert {p.item for p in seen} == {"llm"} and seen[-1].overall_done == seen[-1].overall_total


def _tight_disk(monkeypatch, free):
    import shutil
    from collections import namedtuple
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10**6, 0, free))


@pytest.mark.parametrize("free,fits", [(1400, True), (1399, False)])
def test_disk_error_says_whether_it_fits_without_llm(monkeypatch, free, fits):
    _tight_disk(monkeypatch, free)                      # whisper side alone needs 1400; the helper adds 1300
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None), Settings(), no_test, threading.Event(), downloader=fake_dl,
                  sources=FakeSources(), selftest=no_test, llm=FakeLlm())
    assert e.value.kind == "disk" and e.value.fits_without_llm is fits


def test_run_llm_setup_disk_error_never_offers_skip(monkeypatch):
    from booktranscriber.setup_runner import run_llm_setup
    _tight_disk(monkeypatch, 1)
    with pytest.raises(SetupError) as e:
        run_llm_setup("gemma-4-e4b", "vulkan", Settings(), no_test, threading.Event(), downloader=fake_dl, llm=FakeLlm())
    assert e.value.kind == "disk" and e.value.fits_without_llm is False


@pytest.mark.parametrize("failing,item", [("model-", "llm"), ("m0", "whisper")])
def test_download_error_says_which_item_failed(failing, item):
    def dl(url, *a, **k):
        if url.startswith(failing):
            raise NetworkError("x")
        fake_dl(url, *a, **k)
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None), Settings(), no_test, threading.Event(), downloader=dl,
                  sources=FakeSources(), selftest=no_test, llm=FakeLlm())
    assert (e.value.kind, e.value.item) == ("network", item)


def test_llm_extract_error_says_llm():
    class BadArchive(FakeLlm):
        def extract_archive(self, archive, dest, cancel=None):
            raise RuntimeError("broken archive")
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None), Settings(), no_test, threading.Event(), downloader=fake_dl,
                  sources=FakeSources(), selftest=no_test, llm=BadArchive())
    assert (e.value.kind, e.value.item) == ("network", "llm")


def test_make_plan_amd_no_cuda():
    p = make_plan(SystemInfo("windows", GpuInfo("AMD Radeon RX 7600", 8192, "amd"), 10**12), None)
    assert p.include_gpu is False and p.whisper_model == "large-v3-turbo"


# --- a dropped connection is retried on its own (30 times, 5 s apart) ---------------------
def test_dropped_connection_is_retried_until_it_works():
    from booktranscriber import setup_runner
    attempts, seen = [], []

    def flaky(url, *a, **k):
        attempts.append(url)
        if url == "m0" and attempts.count("m0") <= 3:
            raise NetworkError("connection reset")
        fake_dl(url, *a, **k)
    s = run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(), seen.append, threading.Event(),
                  downloader=flaky, sources=FakeSources(), selftest=no_test)
    assert s.setup_done and attempts.count("m0") == 4
    assert [p.retry for p in seen if p.retry] == [1, 2, 3]
    assert all(p.item == "whisper" for p in seen if p.retry)
    assert setup_runner.NETWORK_RETRIES == 30 and setup_runner.RETRY_DELAY == 0   # 5.0 in the app; tests patch it


def test_retry_constants_are_the_owners(monkeypatch):
    from booktranscriber import setup_runner
    monkeypatch.undo()      # see the app's own values, not the conftest's no-wait patch
    assert (setup_runner.NETWORK_RETRIES, setup_runner.RETRY_DELAY) == (30, 5.0)


def test_gives_up_after_30_retries():
    attempts, retries = [], []

    def down(url, *a, **k):
        attempts.append(url)
        raise NetworkError("no internet")
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(),
                  lambda p: p.retry and retries.append(p.retry), threading.Event(),
                  downloader=down, sources=FakeSources(), selftest=no_test)
    assert e.value.kind == "network" and len(attempts) == 31     # the first try plus 30 retries
    assert retries == list(range(1, 31))


def test_other_errors_are_not_retried():
    from booktranscriber.downloader import ChecksumError
    attempts = []

    def damaged(url, *a, **k):
        attempts.append(url)
        raise ChecksumError("damaged")
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(), no_test, threading.Event(),
                  downloader=damaged, sources=FakeSources(), selftest=no_test)
    assert e.value.kind == "checksum" and len(attempts) == 1


def test_pause_during_the_wait_stops_at_once(monkeypatch):
    from booktranscriber import setup_runner
    monkeypatch.setattr(setup_runner, "RETRY_DELAY", 30)
    cancel = threading.Event()

    def down(url, *a, **k):
        raise NetworkError("no internet")
    with pytest.raises(SetupError) as e:
        run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(),
                  lambda p: p.retry and cancel.set(), cancel,
                  downloader=down, sources=FakeSources(), selftest=no_test)
    assert e.value.kind == "cancelled"


def test_listing_the_files_is_retried_too():
    class FlakySources(FakeSources):
        calls = 0

        def model_files(self, repo_id, dest_dir):
            FlakySources.calls += 1
            if FlakySources.calls <= 2:
                raise OSError("network unreachable")
            return super().model_files(repo_id, dest_dir)
    seen = []
    s = run_setup(make_plan(GPU_INFO, None, include_llm=False), Settings(), seen.append, threading.Event(),
                  downloader=fake_dl, sources=FlakySources(), selftest=no_test)
    assert s.setup_done and [p.retry for p in seen if p.retry] == [1, 2]


def test_helper_download_later_retries_too():
    from booktranscriber.setup_runner import run_llm_setup
    attempts = []

    def flaky(url, *a, **k):
        attempts.append(url)
        if len(attempts) == 1:
            raise NetworkError("reset")
        fake_dl(url, *a, **k)
    run_llm_setup("gemma-4-e4b", "vulkan", Settings(), no_test, threading.Event(), downloader=flaky, llm=FakeLlm())
    assert attempts[0] == attempts[1]
