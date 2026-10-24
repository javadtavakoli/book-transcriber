from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from booktranscriber import paths
from booktranscriber.gui.main_window import MainWindow
from booktranscriber.i18n import I18n
from booktranscriber.settings import Settings, load_settings


def test_starts_on_setup_when_not_done(qtbot):
    w = MainWindow(I18n("en"), Settings())
    qtbot.addWidget(w)
    assert w.current_page() == "setup"


def test_starts_on_setup_when_model_missing(qtbot, tmp_path):
    w = MainWindow(I18n("en"), Settings(setup_done=True, whisper_model_path=str(tmp_path / "gone")))
    qtbot.addWidget(w)
    assert w.current_page() == "setup"


def test_starts_on_home_when_done(qtbot, tmp_path):
    (tmp_path / "model.bin").write_bytes(b"x")
    w = MainWindow(I18n("en"), Settings(setup_done=True, whisper_model_path=str(tmp_path)))
    qtbot.addWidget(w)
    assert w.current_page() == "home"


def test_language_toggle_flips_direction_and_saves(qtbot):
    w = MainWindow(I18n("en"), Settings())
    qtbot.addWidget(w)
    assert w.lang_button.text() == "فا"
    qtbot.mouseClick(w.lang_button, Qt.LeftButton)
    assert QApplication.layoutDirection() == Qt.RightToLeft and w.lang_button.text() == "EN"
    assert w.windowTitle() == "کتاب‌نویس"
    assert load_settings(paths.settings_file()).ui_language == "fa"
    qtbot.mouseClick(w.lang_button, Qt.LeftButton)
    assert QApplication.layoutDirection() == Qt.LeftToRight
