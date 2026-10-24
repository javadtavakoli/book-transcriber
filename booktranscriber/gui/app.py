"""GUI entry point."""
import sys

from PySide6.QtCore import QLocale
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from .. import paths
from ..i18n import I18n, initial_language
from ..llm_server import reap_stale
from ..settings import load_settings


def apply_app_identity(app) -> None:
    """Name and icon, so the window, taskbar and dock show Writing Parrot."""
    app.setApplicationName("Writing Parrot")
    app.setWindowIcon(QIcon(str(paths.asset("icon.png"))))
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WritingParrot.App")
        except Exception:
            pass


def prepare_data() -> None:
    """Migrate first: anything that touches data_dir() would create the new folder and block it."""
    paths.migrate_old_data_dir()
    reap_stale()    # an AI helper left running by an earlier run that crashed would hold the graphics memory


def main(argv=None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    apply_app_identity(app)
    font = QFont(app.font())
    font.setFamilies([font.family(), "Vazirmatn", "Noto Sans Arabic"])   # Persian fallbacks
    app.setFont(font)

    prepare_data()
    from .main_window import MainWindow
    settings = load_settings(paths.settings_file())
    i18n = I18n(initial_language(settings.ui_language, QLocale.system().name()))
    w = MainWindow(i18n, settings)
    w.show()
    w.check_downloads_folder()
    return app.exec()
