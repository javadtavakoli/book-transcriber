import re
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QLabel

from booktranscriber.gui import setup_view
from booktranscriber.gui.setup_view import SetupView
from booktranscriber.i18n import I18n
from booktranscriber.settings import Settings
from booktranscriber.setup_runner import SetupProgress
from booktranscriber.syscheck import GpuInfo, SystemInfo


class FakeRunner(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.starts = []
        self.paused = False

    def start(self, plan, settings):
        self.starts.append((plan, settings))

    def pause(self):
        self.paused = True

    def is_running(self):
        return False


@pytest.fixture
def system(monkeypatch):
    def use(info, existing=None):
        monkeypatch.setattr(setup_view, "detect_system", lambda d: info)
        monkeypatch.setattr(setup_view, "find_existing_model", lambda dirs, model: existing)
    return use


OK = SystemInfo("linux", GpuInfo("NVIDIA GeForce RTX 4050 Laptop GPU", 6141), 120 * 10**9)


def make(qtbot, lang="en", settings=None):
    runner = FakeRunner()
    v = SetupView(I18n(lang), settings or Settings(), runner)
    qtbot.addWidget(v)
    return v, runner


def label(v, name):
    return v.findChild(QLabel, name).text()


def test_welcome_shows_gpu_and_space(qtbot, system):
    system(OK)
    v, _ = make(qtbot)
    assert v.state() == "welcome"
    assert "RTX 4050" in label(v, "check_line") and v.start_button.isEnabled()
    assert "120.0 GB" in label(v, "space_line")


def test_welcome_without_gpu(qtbot, system):
    system(SystemInfo("linux", None, 120 * 10**9))
    v, _ = make(qtbot)
    assert "slower" in label(v, "check_line")


def test_welcome_blocks_when_disk_full(qtbot, system):
    system(SystemInfo("linux", OK.gpu, 10**9))
    v, _ = make(qtbot)
    assert not v.start_button.isEnabled()


def test_reuse_checkbox_when_existing_model(qtbot, system):
    system(OK, existing=Path("/m"))
    v, runner = make(qtbot)
    assert not v.reuse_box.isHidden() and v.reuse_box.isChecked()
    qtbot.mouseClick(v.start_button, Qt.LeftButton)
    assert runner.starts[0][0].reuse_model_path == Path("/m") and v.state() == "downloading"


def test_reuse_unticked_downloads(qtbot, system):
    system(OK, existing=Path("/m"))
    v, runner = make(qtbot)
    v.reuse_box.setChecked(False)
    qtbot.mouseClick(v.start_button, Qt.LeftButton)
    assert runner.starts[0][0].reuse_model_path is None


def test_no_reuse_checkbox_without_existing(qtbot, system):
    system(OK)
    v, _ = make(qtbot)
    assert v.reuse_box.isHidden()


def test_progress_updates_rows(qtbot, system):
    system(OK)
    v, runner = make(qtbot)
    v.start()
    runner.progress.emit(SetupProgress("whisper", 1_000_000_000, 3_000_000_000, 2_000, 4_000, 4e6, 300))
    assert v.overall_bar.value() == 50
    assert "5 min" in label(v, "overall_status")
    assert "1.0 GB / 3.0 GB" in v.rows["whisper"].status.text()
    assert v.rows["gpu"].status.text() == "done"


def test_pause_and_continue(qtbot, system):
    system(OK)
    v, runner = make(qtbot)
    v.start()
    qtbot.mouseClick(v.pause_button, Qt.LeftButton)
    assert runner.paused
    runner.failed.emit("cancelled")
    assert v.state() == "downloading" and v.pause_button.text() == "Continue"
    qtbot.mouseClick(v.pause_button, Qt.LeftButton)
    assert len(runner.starts) == 2


def test_network_error_then_retry(qtbot, system):
    system(OK)
    v, runner = make(qtbot)
    v.start()
    runner.progress.emit(SetupProgress("whisper", 0, 1, 2_100_000_000, 4_000_000_000, 0, None))
    runner.failed.emit("network")
    assert v.state() == "error" and "2.1 GB" in label(v, "error_body")
    qtbot.mouseClick(v.retry_button, Qt.LeftButton)
    assert len(runner.starts) == 2 and v.state() == "downloading"


def test_gpu_error_offers_cpu(qtbot, system):
    system(OK)
    v, runner = make(qtbot)
    v.start()
    runner.failed.emit("gpu")
    assert not v.cpu_button.isHidden()
    qtbot.mouseClick(v.cpu_button, Qt.LeftButton)
    assert runner.starts[-1][1].device == "cpu"


def test_ready_emits_completed(qtbot, system):
    system(OK)
    v, runner = make(qtbot)
    v.start()
    runner.finished.emit(Settings(setup_done=True, whisper_model_path="/m"))
    assert v.state() == "ready"
    with qtbot.waitSignal(v.completed) as blocker:
        qtbot.mouseClick(v.go_button, Qt.LeftButton)
    assert blocker.args[0].whisper_model_path == "/m"


def test_persian_digits(qtbot, system):
    system(OK)
    v, _ = make(qtbot, "fa")
    t = label(v, "space_line")
    assert re.search("[۰-۹]", t) and not re.search("[0-9]", t)


def test_retranslate(qtbot, system):
    system(OK)
    i18n = I18n("en")
    v = SetupView(i18n, Settings(), FakeRunner())
    qtbot.addWidget(v)
    i18n.set_language("fa")
    v.retranslate()
    assert v.start_button.text() == "شروع دانلود"


def test_disk_error_shows_real_numbers(qtbot, system):
    from booktranscriber.setup_runner import SetupError
    system(OK)
    v, runner = make(qtbot)
    v.start()
    runner.last_error = SetupError("disk", needed=1_400_000_000, free=300_000_000)
    runner.failed.emit("disk")
    body = label(v, "error_body")
    assert "1.4 GB" in body and "300 MB" in body
