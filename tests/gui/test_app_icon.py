from PySide6.QtWidgets import QApplication

from booktranscriber.gui.app import apply_app_identity
from booktranscriber.gui.main_window import MainWindow
from booktranscriber.i18n import I18n
from booktranscriber.settings import Settings


def test_window_has_icon(qtbot):
    apply_app_identity(QApplication.instance())
    w = MainWindow(I18n("en"), Settings())
    qtbot.addWidget(w)
    assert not QApplication.windowIcon().isNull()
    assert QApplication.applicationName() == "Writing Parrot"
