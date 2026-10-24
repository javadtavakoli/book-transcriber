"""GUI entry point."""
import sys

from PySide6.QtCore import QLocale
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .. import paths
from ..i18n import I18n, initial_language
from ..settings import load_settings


def main(argv=None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    font = QFont(app.font())
    font.setFamilies([font.family(), "Vazirmatn", "Noto Sans Arabic"])   # Persian fallbacks
    app.setFont(font)

    from .main_window import MainWindow
    settings = load_settings(paths.settings_file())
    i18n = I18n(initial_language(settings.ui_language, QLocale.system().name()))
    w = MainWindow(i18n, settings)
    w.show()
    return app.exec()
