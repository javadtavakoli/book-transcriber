from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from booktranscriber import downloads, paths
from booktranscriber.gui import downloads_dialog, main_window, setup_view
from booktranscriber.gui.downloads_dialog import DownloadsDialog
from booktranscriber.gui.main_window import MainWindow
from booktranscriber.gui.setup_view import SetupView
from booktranscriber.i18n import I18n
from booktranscriber.settings import Settings, load_settings, save_settings
from booktranscriber.syscheck import GpuInfo, SystemInfo

from .test_setup_view import FakeRunner

TB = 10**12
OK = SystemInfo("linux", GpuInfo("NVIDIA GeForce RTX 4050 Laptop GPU", 6141), 120 * 10**9)


@pytest.fixture
def system(monkeypatch):
    """detect_system returns info (or what free(path) says), and records the folders it measured."""
    calls = []

    def use(info=OK, free=None):
        def detect(d):
            calls.append(Path(d))
            return SystemInfo(info.os, info.gpu, free(Path(d)) if free else info.free_bytes)
        monkeypatch.setattr(setup_view, "detect_system", detect)
        monkeypatch.setattr(setup_view, "find_existing_model", lambda dirs, model: None)
        return calls
    return use


def make_setup(qtbot, settings=None):
    runner = FakeRunner()
    v = SetupView(I18n("en"), settings or Settings(), runner)
    qtbot.addWidget(v)
    return v, runner


def label(w, name):
    return w.findChild(QLabel, name)


# --- the welcome page --------------------------------------------------------------
def test_welcome_shows_location_and_free(qtbot, system):
    system()
    v, _ = make_setup(qtbot)
    text = label(v, "location_line").text()
    assert str(paths.data_dir_path()) in text and "free" in text and "120.0 GB" in text
    assert v.downloads_target == paths.data_dir_path()


def test_change_picks_subfolder_and_rechecks_space(qtbot, system, monkeypatch, tmp_path):
    picked = tmp_path / "Big"
    picked.mkdir()
    (picked / "photos").mkdir()     # not empty and not ours: a WritingParrot folder inside
    target = picked / downloads.FOLDER_NAME
    calls = system(SystemInfo("linux", OK.gpu, 10**9), free=lambda d: TB if d == target else 10**9)
    v, _ = make_setup(qtbot)
    assert not v.start_button.isEnabled()       # not enough room in the app folder
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: picked)
    qtbot.mouseClick(v.change_button, Qt.LeftButton)
    assert v.downloads_target == target
    assert calls[-1] == target
    assert v.start_button.isEnabled()
    assert str(target) in label(v, "location_line").text()


def test_unwritable_pick_shows_message(qtbot, system, monkeypatch, tmp_path):
    system()
    v, _ = make_setup(qtbot)
    before = v.downloads_target
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: tmp_path / "ro")
    monkeypatch.setattr(downloads, "writable", lambda folder: False)
    qtbot.mouseClick(v.change_button, Qt.LeftButton)
    msg = label(v, "location_problem")
    assert msg.isVisibleTo(v) and "color: #c0392b" in msg.styleSheet()
    assert "can't" in msg.text()
    assert v.downloads_target == before


def test_c_full_suggestion_explained(qtbot, system, monkeypatch, tmp_path):
    d = tmp_path / "D" / downloads.FOLDER_NAME
    seen = []
    monkeypatch.setattr(downloads, "suggest_default", lambda needed: seen.append(needed) or (d, "c_full"))
    calls = system()
    v, _ = make_setup(qtbot)
    note = label(v, "location_note")
    assert note.isVisibleTo(v) and "not enough" in note.text()
    assert v.downloads_target == d
    assert seen and seen[0] > 0             # the plan's size was asked about
    assert calls[-1] == tmp_path            # the free space measured on that drive (its nearest folder)


def test_no_suggestion_on_repair_run(qtbot, system, monkeypatch, tmp_path):
    folder = tmp_path / "mine"
    folder.mkdir()
    monkeypatch.setattr(downloads, "suggest_default", lambda needed: pytest.fail("asked for a suggestion"))
    calls = system()
    v, _ = make_setup(qtbot, Settings(downloads_dir=str(folder)))
    assert v.downloads_target == folder and calls[-1] == folder
    assert not label(v, "location_note").isVisibleTo(v)


def test_start_applies_downloads_dir(qtbot, system, monkeypatch, tmp_path):
    picked = tmp_path / "empty"
    picked.mkdir()
    system()
    s = Settings()
    v, runner = make_setup(qtbot, s)
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: picked)
    qtbot.mouseClick(v.change_button, Qt.LeftButton)
    assert v.downloads_target == picked         # empty: used as it is
    assert s.downloads_dir is None              # nothing is saved before Start
    v.start()
    assert s.downloads_dir == str(picked) and runner.starts
    assert (picked / downloads.MARKER).exists()
    assert load_settings(paths.settings_file()).downloads_dir == str(picked)


# --- the Settings dialog -----------------------------------------------------------
def fake_downloads(root: Path) -> list[Path]:
    files = [root / "models" / "m" / "model.bin", root / "llm" / "helper.gguf"]
    for f in files:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * 1000)
    return files


def test_move_dialog_moves(qtbot, monkeypatch, tmp_path):
    old = paths.data_dir()
    fake_downloads(old)
    new = tmp_path / "new"
    s = Settings(setup_done=True, whisper_model_path=str(old / "models" / "m"))
    dlg = DownloadsDialog(I18n("en"), s)
    qtbot.addWidget(dlg)
    assert str(old) in dlg.folder_label.text() and "0 MB" in dlg.size_label.text()
    asked = []
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: new)
    monkeypatch.setattr(downloads_dialog, "ask_move", lambda parent, i18n, size: asked.append(size) or "move")
    qtbot.mouseClick(dlg.change_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: not dlg.is_moving(), timeout=5000)
    assert asked == [2000]
    assert (new / "models" / "m" / "model.bin").read_bytes() == b"x" * 1000
    assert not (old / "models" / "m" / "model.bin").exists()
    assert s.downloads_dir == str(new) and s.whisper_model_path == str(new / "models" / "m")
    assert "moved" in dlg.status_label.text().lower()


def test_move_dialog_dont_move_sets_folder_and_asks_repair(qtbot, monkeypatch, tmp_path):
    fake_downloads(paths.data_dir())
    new = tmp_path / "new"
    s = Settings(setup_done=True)
    dlg = DownloadsDialog(I18n("en"), s)
    qtbot.addWidget(dlg)
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: new)
    monkeypatch.setattr(downloads_dialog, "ask_move", lambda parent, i18n, size: "dont")
    with qtbot.waitSignal(dlg.repair_needed):
        qtbot.mouseClick(dlg.change_button, Qt.LeftButton)
    assert s.downloads_dir == str(new)
    assert (paths.data_dir() / "llm" / "helper.gguf").exists()     # left where it was


def test_move_dialog_cancel_question_changes_nothing(qtbot, monkeypatch, tmp_path):
    fake_downloads(paths.data_dir())
    s = Settings(setup_done=True)
    dlg = DownloadsDialog(I18n("en"), s)
    qtbot.addWidget(dlg)
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: tmp_path / "new")
    monkeypatch.setattr(downloads_dialog, "ask_move", lambda parent, i18n, size: "cancel")
    qtbot.mouseClick(dlg.change_button, Qt.LeftButton)
    assert s.downloads_dir is None and not dlg.is_moving()


def test_move_dialog_shows_space_error(qtbot, monkeypatch, tmp_path):
    fake_downloads(paths.data_dir())
    s = Settings(setup_done=True)
    dlg = DownloadsDialog(I18n("en"), s)
    qtbot.addWidget(dlg)

    def no_room(settings, new_root, progress, cancel):
        raise downloads.MoveError("space", needed=5 * 10**9, free=10**9)
    monkeypatch.setattr(downloads, "move_downloads", no_room)
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: tmp_path / "new")
    monkeypatch.setattr(downloads_dialog, "ask_move", lambda parent, i18n, size: "move")
    qtbot.mouseClick(dlg.change_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: not dlg.is_moving(), timeout=5000)
    text = dlg.status_label.text()
    assert "5.0 GB" in text and "1.0 GB" in text and s.downloads_dir is None


def test_move_dialog_cancel_button_stops_the_move(qtbot, monkeypatch, tmp_path):
    fake_downloads(paths.data_dir())
    s = Settings(setup_done=True)
    dlg = DownloadsDialog(I18n("en"), s)
    qtbot.addWidget(dlg)

    def slow(settings, new_root, progress, cancel):
        progress(downloads.MoveProgress(1, 2))
        assert cancel.wait(5)
        raise downloads.MoveCancelled()
    monkeypatch.setattr(downloads, "move_downloads", slow)
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: tmp_path / "new")
    monkeypatch.setattr(downloads_dialog, "ask_move", lambda parent, i18n, size: "move")
    qtbot.mouseClick(dlg.change_button, Qt.LeftButton)
    assert dlg.is_moving()
    qtbot.waitUntil(lambda: dlg.bar.value() == 50, timeout=5000)
    qtbot.mouseClick(dlg.cancel_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: not dlg.is_moving(), timeout=5000)
    assert s.downloads_dir is None and dlg.change_button.isEnabled()


# --- the main window ---------------------------------------------------------------
def ready_settings(tmp_path, **kw) -> Settings:
    model = tmp_path / "model"
    model.mkdir(exist_ok=True)
    (model / "model.bin").write_bytes(b"x")
    return Settings(setup_done=True, whisper_model_path=str(model), **kw)


def driving(qtbot, opened):
    """A run_dialog that presses Change… and waits for the move, as a person would before closing."""
    def run(dlg):
        opened.append(dlg)
        qtbot.mouseClick(dlg.change_button, Qt.LeftButton)
        qtbot.waitUntil(lambda: not dlg.is_moving(), timeout=5000)
    return run


def test_move_through_menu_keeps_one_settings_object(qtbot, monkeypatch, tmp_path):
    fake_downloads(paths.data_dir())
    new = tmp_path / "new"
    w = MainWindow(I18n("en"), ready_settings(tmp_path))
    qtbot.addWidget(w)
    stops = []
    monkeypatch.setattr(w.local_runner, "stop_server", lambda: stops.append(1))
    monkeypatch.setattr(main_window, "reap_stale", lambda: None)
    opened = []
    monkeypatch.setattr(downloads_dialog, "run_dialog", driving(qtbot, opened))
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: new)

    def ask(parent, i18n, size):
        assert not stops        # asked first; the helper is stopped only once Move is chosen
        return "move"
    monkeypatch.setattr(downloads_dialog, "ask_move", ask)
    w.downloads_action.trigger()
    [dlg] = opened
    assert dlg.settings is w.settings
    assert stops == [1]
    assert w.settings is w.flow_view.settings is w.setup_view.settings
    assert w.settings.downloads_dir == str(new) == w.flow_view.settings.downloads_dir
    assert (new / "llm" / "helper.gguf").exists()


def test_setup_after_a_menu_move_starts_in_the_new_folder(qtbot, monkeypatch, tmp_path):
    data = paths.data_dir()
    fake_downloads(data)
    new = tmp_path / "new"
    w = MainWindow(I18n("en"), Settings(setup_done=True, whisper_model_path=str(data / "models" / "m")))
    qtbot.addWidget(w)
    starts = []
    monkeypatch.setattr(w.setup_runner, "start", lambda plan, settings: starts.append(settings))
    w.open_repair()
    w.setup_view._on_failed("gpu")
    w.setup_view._continue_on_cpu()         # the error page's "Continue without graphics card"
    w.setup_view._on_failed("network")
    assert w.current_page() == "setup" and w.setup_view.state() == "error"
    monkeypatch.setattr(downloads_dialog, "run_dialog", driving(qtbot, []))
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: new)
    monkeypatch.setattr(downloads_dialog, "ask_move", lambda parent, i18n, size: "move")
    w.downloads_action.trigger()
    assert w.setup_view.state() == "welcome" and w.setup_view.downloads_target == new
    w.setup_view.start()
    s = starts[-1]
    assert s is w.settings and s.device == "cpu"
    assert s.downloads_dir == str(new) and s.whisper_model_path == str(new / "models" / "m")
    saved = load_settings(paths.settings_file())
    assert saved.downloads_dir == str(new) and saved.whisper_model_path == str(new / "models" / "m")


def test_change_on_repair_run_with_downloads_offers_the_move(qtbot, monkeypatch, tmp_path):
    data = paths.data_dir()
    fake_downloads(data)
    w = MainWindow(I18n("en"), Settings(setup_done=True, whisper_model_path=str(data / "models" / "m")))
    qtbot.addWidget(w)
    w.open_repair()
    opened = []
    monkeypatch.setattr(downloads_dialog, "run_dialog", opened.append)
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: pytest.fail("setup picked"))
    qtbot.mouseClick(w.setup_view.change_button, Qt.LeftButton)
    assert len(opened) == 1 and opened[0].settings is w.settings
    assert w.setup_view.downloads_target == data


def test_move_blocked_while_busy(qtbot, monkeypatch, tmp_path):
    w = MainWindow(I18n("en"), ready_settings(tmp_path))
    qtbot.addWidget(w)
    monkeypatch.setattr(w, "busy", lambda: True)
    monkeypatch.setattr(w, "confirm_quit", lambda: True)      # closing at teardown
    shown, opened = [], []
    monkeypatch.setattr(downloads_dialog, "show_message", lambda parent, text: shown.append(text))
    monkeypatch.setattr(downloads_dialog, "run_dialog", opened.append)
    w.downloads_action.trigger()
    assert shown == ["Finish or cancel the current work first."] and opened == []


def test_menu_has_downloads_entry(qtbot, tmp_path):
    w = MainWindow(I18n("en"), ready_settings(tmp_path))
    qtbot.addWidget(w)
    assert w.downloads_action.text() == "Downloads folder…"


def test_missing_downloads_folder_prompts(qtbot, monkeypatch, tmp_path):
    gone = tmp_path / "usb" / "WritingParrot"
    w = MainWindow(I18n("en"), ready_settings(tmp_path, downloads_dir=str(gone)))
    qtbot.addWidget(w)
    asked = []

    def ask(parent, i18n, path):
        asked.append(path)
        if len(asked) == 1:
            return "retry"      # still missing: asked again
        return "choose"
    monkeypatch.setattr(downloads_dialog, "ask_missing", ask)
    other = tmp_path / "other"
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: other)
    w.check_downloads_folder()
    assert asked == [gone, gone]
    assert w.settings.downloads_dir == str(other)
    assert load_settings(paths.settings_file()).downloads_dir == str(other)
    assert w.current_page() == "setup"


def test_present_downloads_folder_asks_nothing(qtbot, monkeypatch, tmp_path):
    w = MainWindow(I18n("en"), ready_settings(tmp_path, downloads_dir=str(tmp_path)))
    qtbot.addWidget(w)
    monkeypatch.setattr(downloads_dialog, "ask_missing", lambda *a: pytest.fail("asked"))
    w.check_downloads_folder()


def test_missing_prompt_strings_in_english():
    tr = I18n("en").tr
    assert tr("downloads.retry") == "Try again" and tr("downloads.choose") == "Choose another folder"


def unplugged(monkeypatch, gone: Path):
    """Simulate a Windows drive that isn't connected: measuring anywhere on it (even E:\\) fails."""
    data = paths.data_dir_path()

    def detect(d):
        if Path(d) != data and Path(d) != gone:
            raise OSError("no such drive")
        return OK
    monkeypatch.setattr(setup_view, "detect_system", detect)


def saved_window(qtbot, gone: Path) -> MainWindow:
    """Settings on disk too, so paths.downloads_dir_path() really is the missing folder."""
    s = Settings(setup_done=True, whisper_model_path=str(gone / "models" / "m"), downloads_dir=str(gone))
    save_settings(s, paths.settings_file())
    assert paths.downloads_dir_path() == gone
    w = MainWindow(I18n("en"), s)
    qtbot.addWidget(w)
    return w


def test_unplugged_drive_does_not_break_start(qtbot, monkeypatch, tmp_path):
    gone = tmp_path / "usb" / "WritingParrot"
    unplugged(monkeypatch, gone)
    w = saved_window(qtbot, gone)
    assert w.current_page() == "setup"      # the model is on that drive
    v = w.setup_view
    assert v.downloads_target == gone and not v.start_button.isEnabled()
    problem = label(v, "location_problem")
    assert problem.isVisibleTo(v) and "isn't connected" in problem.text()
    assert "free" not in label(v, "location_line").text()       # no other drive's free space shown as its
    asked = []
    monkeypatch.setattr(downloads_dialog, "ask_missing", lambda parent, i18n, path: asked.append(path) or "close")
    w.check_downloads_folder()
    assert asked == [gone] and w.current_page() == "setup"


def test_missing_downloads_folder_retry_finds_it(qtbot, monkeypatch, tmp_path):
    gone = tmp_path / "usb" / "WritingParrot"
    unplugged(monkeypatch, gone)
    w = saved_window(qtbot, gone)
    asked = []

    def ask(parent, i18n, path):
        asked.append(path)
        fake_downloads(gone)        # the drive was plugged back in
        return "retry"
    monkeypatch.setattr(downloads_dialog, "ask_missing", ask)
    w.check_downloads_folder()
    assert asked == [gone] and w.settings.downloads_dir == str(gone)
    assert w.current_page() == "home"
    v = w.setup_view
    assert not v.target_missing and not label(v, "location_problem").isVisibleTo(v)


def test_dialog_same_folder_says_so(qtbot, monkeypatch):
    dlg = DownloadsDialog(I18n("en"), Settings(setup_done=True))
    qtbot.addWidget(dlg)
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: paths.data_dir())
    monkeypatch.setattr(downloads_dialog, "ask_move", lambda *a: pytest.fail("asked"))
    qtbot.mouseClick(dlg.change_button, Qt.LeftButton)
    assert "already" in dlg.status_label.text()


def test_dialog_nested_checked_before_creating(qtbot, monkeypatch):
    inside = paths.data_dir() / "models" / "elsewhere"
    dlg = DownloadsDialog(I18n("en"), Settings(setup_done=True))
    qtbot.addWidget(dlg)
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: inside)
    monkeypatch.setattr(downloads, "writable", lambda f: pytest.fail("writable() called"))
    qtbot.mouseClick(dlg.change_button, Qt.LeftButton)
    assert "inside" in dlg.status_label.text() and not inside.exists()


def test_dialog_cancel_removes_the_folder_it_made(qtbot, monkeypatch, tmp_path):
    fake_downloads(paths.data_dir())
    made, kept = tmp_path / "made", tmp_path / "kept"
    kept.mkdir()
    dlg = DownloadsDialog(I18n("en"), Settings(setup_done=True))
    qtbot.addWidget(dlg)
    monkeypatch.setattr(downloads_dialog, "ask_move", lambda parent, i18n, size: "cancel")
    for folder in (made, kept):
        monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start, f=folder: f)
        qtbot.mouseClick(dlg.change_button, Qt.LeftButton)
    assert not made.exists() and kept.is_dir()


def test_flow_measures_downloads_without_creating_it(qtbot, monkeypatch, tmp_path):
    from booktranscriber.gui import flow_view
    later = tmp_path / "later" / "WritingParrot"
    save_settings(Settings(downloads_dir=str(later)), paths.settings_file())
    seen = []
    monkeypatch.setattr(flow_view, "detect_system", lambda d: seen.append(Path(d)) or OK)
    w = MainWindow(I18n("en"), ready_settings(tmp_path, downloads_dir=str(later)))
    qtbot.addWidget(w)
    w.flow_view._llm_pick = None
    w.flow_view._llm_choice()
    assert seen[-1] == tmp_path and not later.exists()
