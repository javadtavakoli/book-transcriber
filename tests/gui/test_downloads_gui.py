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
from booktranscriber.settings import Settings, load_settings
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


def test_move_through_menu_keeps_one_settings_object(qtbot, monkeypatch, tmp_path):
    fake_downloads(paths.data_dir())
    new = tmp_path / "new"
    w = MainWindow(I18n("en"), ready_settings(tmp_path))
    qtbot.addWidget(w)
    stops = []
    monkeypatch.setattr(w.local_runner, "stop_server", lambda: stops.append(1))
    monkeypatch.setattr(main_window, "reap_stale", lambda: None)
    opened = []
    monkeypatch.setattr(downloads_dialog, "run_dialog", opened.append)
    monkeypatch.setattr(downloads_dialog, "pick_folder", lambda parent, start: new)

    def ask(parent, i18n, size):
        assert not stops        # asked first; the helper is stopped only once Move is chosen
        return "move"
    monkeypatch.setattr(downloads_dialog, "ask_move", ask)
    w.downloads_action.trigger()
    [dlg] = opened
    assert dlg.settings is w.settings
    qtbot.mouseClick(dlg.change_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: not dlg.is_moving(), timeout=5000)
    assert stops == [1]
    assert w.settings is w.flow_view.settings is w.setup_view.settings
    assert w.settings.downloads_dir == str(new) == w.flow_view.settings.downloads_dir
    assert (new / "llm" / "helper.gguf").exists()


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


def test_missing_downloads_folder_retry_finds_it(qtbot, monkeypatch, tmp_path):
    back = tmp_path / "usb" / "WritingParrot"
    w = MainWindow(I18n("en"), ready_settings(tmp_path, downloads_dir=str(back)))
    qtbot.addWidget(w)
    asked = []

    def ask(parent, i18n, path):
        asked.append(path)
        back.mkdir(parents=True)     # the drive was plugged back in
        return "retry"
    monkeypatch.setattr(downloads_dialog, "ask_missing", ask)
    w.check_downloads_folder()
    assert asked == [back] and w.settings.downloads_dir == str(back) and w.current_page() == "home"


def test_present_downloads_folder_asks_nothing(qtbot, monkeypatch, tmp_path):
    w = MainWindow(I18n("en"), ready_settings(tmp_path, downloads_dir=str(tmp_path)))
    qtbot.addWidget(w)
    monkeypatch.setattr(downloads_dialog, "ask_missing", lambda *a: pytest.fail("asked"))
    w.check_downloads_folder()


def test_missing_prompt_strings_in_english():
    tr = I18n("en").tr
    assert tr("downloads.retry") == "Try again" and tr("downloads.choose") == "Choose another folder"


def test_unplugged_drive_does_not_break_start(qtbot, monkeypatch, tmp_path):
    """On Windows E:\\ itself is gone when the drive is unplugged: measuring there raises."""
    gone = tmp_path / "usb" / "WritingParrot"
    data = paths.data_dir_path()

    def detect(d):
        if Path(d) != data:
            raise OSError("no such drive")
        return OK
    monkeypatch.setattr(setup_view, "detect_system", detect)
    w = MainWindow(I18n("en"), ready_settings(tmp_path, downloads_dir=str(gone)))
    qtbot.addWidget(w)
    assert w.setup_view.downloads_target == gone
    asked = []
    monkeypatch.setattr(downloads_dialog, "ask_missing", lambda parent, i18n, path: asked.append(path) or "close")
    w.check_downloads_folder()
    assert asked == [gone]
