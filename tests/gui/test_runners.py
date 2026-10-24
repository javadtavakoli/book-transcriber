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
    assert blocker.args[0] == "unknown" and "Segmentation fault" in blocker.args[1]


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
