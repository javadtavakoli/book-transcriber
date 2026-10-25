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
    app.setDesktopFileName("writing-parrot")    # Wayland: matches the .deb's writing-parrot.desktop
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


def smoke(out_path: str | None) -> int:
    """`--smoke`: prove a build starts (Qt, the bundled icon, the engine's native parts) without
    touching the network or the user's data. A windowed exe has no stdout, so the verdict goes to a file."""
    import importlib
    import os
    import traceback
    import tempfile
    from .. import __version__
    if not os.environ.get("BT_DATA_DIR"):   # a manual --smoke must not create the real data folder
        os.environ["BT_DATA_DIR"] = tempfile.mkdtemp(prefix="wp-smoke-")
    try:
        for name in ("ctranslate2", "av", "faster_whisper", "onnxruntime", "httpx"):
            importlib.import_module(name)
        from faster_whisper.utils import get_assets_path
        vad = os.path.join(get_assets_path(), "silero_vad_v6.onnx")
        if not os.path.isfile(vad):
            raise FileNotFoundError(vad)
        app = QApplication.instance() or QApplication([sys.argv[0]])
        apply_app_identity(app)
        if app.windowIcon().isNull():
            raise FileNotFoundError(paths.asset("icon.png"))
        from .main_window import MainWindow
        settings = load_settings(paths.settings_file())
        MainWindow(I18n(initial_language(settings.ui_language, "en")), settings)
        verdict, code = f"SMOKE OK {__version__}\n", 0
    except BaseException:
        verdict, code = "SMOKE FAIL\n" + traceback.format_exc(), 1
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(verdict)
    elif sys.stdout is not None:     # None in a windowed exe
        print(verdict, end="")
    return code


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
    w.check_for_updates()
    return app.exec()
