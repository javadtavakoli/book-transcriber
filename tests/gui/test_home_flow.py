from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Qt, Signal

from booktranscriber import paths
from booktranscriber.gui import flow_view
from booktranscriber.gui.flow_view import FlowView
from booktranscriber.gui.home_view import HomeView, validate_drop
from booktranscriber.gui.main_window import MainWindow
from booktranscriber.i18n import I18n
from booktranscriber.namelists import list_lists
from booktranscriber.recents import RecentItem, add_recent, load_recents
from booktranscriber.settings import Settings


class FakeRunner(QObject):
    loaded = Signal(str)
    duration = Signal(float)
    segment = Signal(float, str)
    progress = Signal(float, float, float)
    finished = Signal(str, int)
    failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.jobs, self.cancel_called, self.running = [], False, False

    def start(self, job):
        self.jobs.append(job)
        self.running = True

    def cancel(self):
        self.cancel_called, self.running = True, False

    def is_running(self):
        return self.running

    @property
    def last_job(self):
        return self.jobs[-1]


@pytest.fixture
def flow(qtbot, tmp_path):
    runner = FakeRunner()
    v = FlowView(I18n("en"), Settings(setup_done=True, whisper_model_path=str(tmp_path / "model")), runner)
    qtbot.addWidget(v)
    audio = tmp_path / "جلسه ۱۲.m4a"
    audio.write_bytes(b"x")
    v.begin(str(audio))
    return v, runner, audio


@pytest.mark.parametrize("names,err", [(["a.m4a", "b.m4a"], "home.err.many"), (["book.pdf"], "home.err.not_audio")])
def test_validate_drop_errors(tmp_path, names, err):
    files = [tmp_path / n for n in names]
    for f in files:
        f.write_bytes(b"x")
    assert validate_drop([str(f) for f in files])[1] == err


def test_validate_drop_folder_and_missing(tmp_path):
    assert validate_drop([str(tmp_path)])[1] == "home.err.folder"
    assert validate_drop([str(tmp_path / "x.m4a")])[1] == "home.err.missing"
    assert validate_drop([])[1] == "home.err.missing"


def test_validate_drop_persian_name_and_case(tmp_path):
    f = tmp_path / "جلسه ۱۲.M4A"
    f.write_bytes(b"x")
    assert validate_drop([str(f)]) == (str(f), None)


def test_home_drop_error_shows_message(qtbot, tmp_path):
    v = HomeView(I18n("en"), Settings())
    qtbot.addWidget(v)
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"x")
    got = []
    v.audio_selected.connect(got.append)
    v.handle_files([str(pdf)])
    assert got == [] and "recording" in v.error_label.text() and not v.error_label.isHidden()


def test_home_lists_recents(qtbot, tmp_path):
    raw = tmp_path / "s11 - متن خام.txt"
    raw.write_text("x", "utf-8")
    add_recent(paths.recents_file(), RecentItem(str(tmp_path / "s11.m4a"), str(raw), None, "t"))
    v = HomeView(I18n("en"), Settings())
    qtbot.addWidget(v)
    assert v.recent_list.count() == 1 and "s11" in v.recent_list.item(0).text()
    got = []
    v.recent_opened.connect(got.append)
    v.recent_list.itemActivated.emit(v.recent_list.item(0))
    assert got[0].raw_path == str(raw)


def test_names_skip_starts_with_default_prompt(qtbot, flow):
    v, runner, audio = flow
    assert v.state() == "names"
    qtbot.mouseClick(v.skip_button, Qt.LeftButton)
    job = runner.last_job
    assert job.prompt == "جلسهٔ کتاب‌خوانی به زبان فارسی." and job.audio == str(audio)
    assert job.out == str(audio.with_name("جلسه ۱۲ - متن خام.txt")) and v.state() == "transcribing"


def test_names_continue_builds_prompt_and_saves_list(qtbot, flow):
    v, runner, _ = flow
    v.names_edit.setPlainText("هومر\nکافکا")
    v.save_box.setChecked(True)
    v.save_name.setText("Homer")
    qtbot.mouseClick(v.continue_button, Qt.LeftButton)
    assert "هومر، کافکا" in runner.last_job.prompt
    assert list_lists(paths.namelists_dir()) == ["Homer"]
    assert v.names() == ["هومر", "کافکا"]


def test_load_saved_list(qtbot, flow):
    from booktranscriber.namelists import save_list
    v, _, _ = flow
    save_list(paths.namelists_dir(), "Homer", ["هومر"])
    v.refresh_lists()
    v.list_combo.setCurrentIndex(v.list_combo.findText("Homer"))
    assert v.names_edit.toPlainText() == "هومر"


def test_advanced_options_go_into_job(qtbot, flow):
    v, runner, _ = flow
    v.timestamps_box.setChecked(True)
    v.device_combo.setCurrentIndex(v.device_combo.findData("cpu"))
    v.language_combo.setEditText("en")
    qtbot.mouseClick(v.skip_button, Qt.LeftButton)
    j = runner.last_job
    assert j.timestamps and j.device == "cpu" and j.language == "en" and j.prompt is None


def test_unwritable_folder_asks_for_location(qtbot, flow, monkeypatch, tmp_path):
    v, runner, audio = flow
    monkeypatch.setattr(flow_view, "folder_writable", lambda d: False)
    monkeypatch.setattr(v, "ask_save_path", lambda default: str(tmp_path / "elsewhere.txt"))
    qtbot.mouseClick(v.skip_button, Qt.LeftButton)
    assert runner.last_job.out == str(tmp_path / "elsewhere.txt")


def test_unwritable_folder_cancelled_stays(qtbot, flow, monkeypatch):
    v, runner, _ = flow
    monkeypatch.setattr(flow_view, "folder_writable", lambda d: False)
    monkeypatch.setattr(v, "ask_save_path", lambda default: None)
    qtbot.mouseClick(v.skip_button, Qt.LeftButton)
    assert runner.jobs == [] and v.state() == "names"


def test_progress_and_segments_shown(qtbot, flow):
    v, runner, _ = flow
    qtbot.mouseClick(v.skip_button, Qt.LeftButton)
    runner.loaded.emit("cuda/float16")
    runner.duration.emit(100.0)
    runner.progress.emit(25.0, 100.0, 60.0)
    runner.segment.emit(0.0, "سلام")
    assert v.progress_bar.value() == 25 and "سلام" in v.live_text.toPlainText()
    assert "about 1 min" in v.eta_label.text()


def test_finished_adds_recent_and_emits(qtbot, flow):
    v, runner, audio = flow
    qtbot.mouseClick(v.skip_button, Qt.LeftButton)
    out = Path(runner.last_job.out)
    out.write_text("سلام\n", "utf-8")
    with qtbot.waitSignal(v.transcribed) as blocker:
        runner.finished.emit(str(out), 1)
    assert blocker.args[0].raw_path == str(out) and v.state() == "result"
    assert [i.raw_path for i in load_recents(paths.recents_file())] == [str(out)]


def test_no_speech_message(qtbot, flow):
    v, runner, _ = flow
    qtbot.mouseClick(v.skip_button, Qt.LeftButton)
    runner.finished.emit(runner.last_job.out, 0)
    assert "No speech" in v.problem_label.text() and not v.problem_label.isHidden()
    assert load_recents(paths.recents_file()) == []


def test_bad_audio_error_offers_another_file(qtbot, flow):
    v, runner, _ = flow
    qtbot.mouseClick(v.skip_button, Qt.LeftButton)
    runner.failed.emit("bad_audio", "x")
    assert "can't be played" in v.problem_label.text()
    with qtbot.waitSignal(v.back_home):
        qtbot.mouseClick(v.problem_button, Qt.LeftButton)


def test_model_error_retries_on_cpu(qtbot, flow):
    v, runner, _ = flow
    qtbot.mouseClick(v.skip_button, Qt.LeftButton)
    runner.failed.emit("model", "cublas")
    qtbot.mouseClick(v.problem_button, Qt.LeftButton)
    assert len(runner.jobs) == 2 and runner.last_job.device == "cpu"


def test_cancel_returns_to_names(qtbot, flow, monkeypatch):
    v, runner, _ = flow
    monkeypatch.setattr(v, "confirm_cancel", lambda: True)
    qtbot.mouseClick(v.skip_button, Qt.LeftButton)
    qtbot.mouseClick(v.cancel_button, Qt.LeftButton)
    assert runner.cancel_called and v.state() == "names"


def test_cancel_declined_keeps_going(qtbot, flow, monkeypatch):
    v, runner, _ = flow
    monkeypatch.setattr(v, "confirm_cancel", lambda: False)
    qtbot.mouseClick(v.skip_button, Qt.LeftButton)
    qtbot.mouseClick(v.cancel_button, Qt.LeftButton)
    assert not runner.cancel_called and v.state() == "transcribing"


def test_close_while_busy_asks_and_kills(qtbot, monkeypatch, tmp_path):
    (tmp_path / "model.bin").write_bytes(b"x")
    w = MainWindow(I18n("en"), Settings(setup_done=True, whisper_model_path=str(tmp_path)))
    qtbot.addWidget(w)
    w.show()
    monkeypatch.setattr(w.transcriber, "is_running", lambda: True)
    cancelled = []
    monkeypatch.setattr(w.transcriber, "cancel", lambda: cancelled.append(1))
    monkeypatch.setattr(w, "confirm_quit", lambda: False)
    w.close()
    assert w.isVisible() and cancelled == []
    monkeypatch.setattr(w, "confirm_quit", lambda: True)
    w.close()
    assert not w.isVisible() and cancelled == [1]


def test_main_window_home_to_flow(qtbot, tmp_path):
    (tmp_path / "model.bin").write_bytes(b"x")
    w = MainWindow(I18n("en"), Settings(setup_done=True, whisper_model_path=str(tmp_path)))
    qtbot.addWidget(w)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    w.home_view.handle_files([str(audio)])
    assert w.current_page() == "flow" and w.flow_view.state() == "names"
    w.flow_view.back_home.emit()
    assert w.current_page() == "home"
