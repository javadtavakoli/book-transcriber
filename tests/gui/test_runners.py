import sys
from pathlib import Path

import pytest

from booktranscriber.gui import runners
from booktranscriber.gui.runners import TranscribeJob, TranscribeRunner

FAKE = str(Path(__file__).with_name("fake_worker.py"))


def job(tmp_path):
    return TranscribeJob(audio=str(tmp_path / "a.wav"), out=str(tmp_path / "a - متن خام.txt"), model="m",
                         download_root=None, language="fa", prompt=None, timestamps=False, device="auto")


@pytest.fixture
def fake(monkeypatch):
    def use(mode):
        monkeypatch.setattr(runners, "worker_command", lambda args: [sys.executable, FAKE, mode, *args])
    return use


def test_runner_emits_events(qtbot, fake, tmp_path):
    fake("ok")
    r = TranscribeRunner()
    segs, progress = [], []
    r.segment.connect(lambda start, text: segs.append(text))
    r.progress.connect(lambda d, t, e: progress.append((d, t)))
    j = job(tmp_path)
    with qtbot.waitSignal(r.finished, timeout=10000) as blocker:
        r.start(j)
    assert blocker.args == [j.out, 2] and segs == ["سلام", "دنیا"] and progress == [(2.0, 4.0)]
    assert not r.is_running()


def test_runner_reports_worker_error(qtbot, fake, tmp_path):
    fake("error")
    r = TranscribeRunner()
    with qtbot.waitSignal(r.failed, timeout=10000) as blocker:
        r.start(job(tmp_path))
    assert blocker.args[0] == "bad_audio"


def test_runner_crash_without_error_event(qtbot, fake, tmp_path):
    fake("crash")
    r = TranscribeRunner()
    with qtbot.waitSignal(r.failed, timeout=10000) as blocker:
        r.start(job(tmp_path))
    assert "Segmentation fault" in blocker.args[1]


def test_runner_cancel_kills_and_removes_part(qtbot, fake, tmp_path):
    fake("slow")
    r = TranscribeRunner()
    j = job(tmp_path)
    with qtbot.waitSignal(r.loaded, timeout=10000):
        r.start(j)
    assert Path(j.out + ".part").exists()
    failed = []
    r.failed.connect(lambda *a: failed.append(a))
    r.cancel()
    assert not r.is_running() and not Path(j.out + ".part").exists()
    qtbot.wait(200)
    assert failed == []      # a cancel is not an error


def test_retry_right_after_error_is_not_broken_by_old_process(qtbot, monkeypatch, tmp_path):
    modes = iter(["error_then_linger", "slow"])
    monkeypatch.setattr(runners, "worker_command",
                        lambda args: [sys.executable, FAKE, next(modes), *args])
    r = TranscribeRunner()
    failures, loaded = [], []
    r.failed.connect(lambda kind, msg: failures.append(kind))
    with qtbot.waitSignal(r.failed, timeout=10000):
        r.start(job(tmp_path))
    r.loaded.connect(loaded.append)
    r.start(job(tmp_path))      # retry immediately, while the first worker is still alive
    qtbot.wait(2000)            # the first worker exits meanwhile
    assert failures == ["model"] and loaded == ["cpu/int8"] and r.is_running()
    r.cancel()


def test_worker_that_cannot_start_fails(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(runners, "worker_command", lambda args: ["/nonexistent/python", *args])
    r = TranscribeRunner()
    with qtbot.waitSignal(r.failed, timeout=10000) as blocker:
        r.start(job(tmp_path))
    assert blocker.args[0] == "unknown" and not r.is_running()


def test_native_crash_on_gpu_maps_to_model(qtbot, fake, tmp_path):
    fake("crash")
    r = TranscribeRunner()
    j = job(tmp_path)
    j.device = "auto"
    with qtbot.waitSignal(r.failed, timeout=10000) as blocker:
        r.start(j)
    assert blocker.args[0] == "model"


def test_native_crash_on_cpu_stays_unknown(qtbot, fake, tmp_path):
    fake("crash")
    r = TranscribeRunner()
    j = job(tmp_path)
    j.device = "cpu"
    with qtbot.waitSignal(r.failed, timeout=10000) as blocker:
        r.start(j)
    assert blocker.args[0] == "unknown"


def test_setup_runner_stop_joins_thread(qtbot, monkeypatch):
    import threading
    import time

    from booktranscriber import setup_runner
    from booktranscriber.gui.runners import SetupRunner

    def slow_to_stop(plan, settings, on_progress, cancel, **kw):
        cancel.wait()
        time.sleep(0.5)          # e.g. finishing the current chunk
        raise setup_runner.SetupError("cancelled")
    monkeypatch.setattr(setup_runner, "run_setup", slow_to_stop)
    r = SetupRunner()
    r.start(None, None)
    qtbot.wait(100)
    assert r.is_running()
    r.stop_and_wait()
    assert not r.is_running()
