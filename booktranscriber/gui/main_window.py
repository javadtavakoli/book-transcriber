"""Main window: one page at a time (setup, home, flow, export, local, review), language toggle, close guard."""
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from .. import downloads, paths
from ..i18n import I18n
from ..llm_server import reap_stale
from ..settings import Settings, save_settings
from . import downloads_dialog
from .downloads_dialog import DownloadsDialog
from .runners import LocalFixRunner, SetupRunner, TranscribeRunner
from .export_view import ExportView
from .flow_view import FlowView
from .home_view import HomeView
from .local_view import LocalView
from .review_view import ReviewView
from .setup_view import SetupView

PAGES = ("setup", "home", "flow", "export", "local", "review")


def model_ready(settings: Settings) -> bool:
    p = settings.whisper_model_path
    return bool(settings.setup_done and p and os.path.isfile(os.path.join(p, "model.bin")))


class MainWindow(QMainWindow):
    def __init__(self, i18n: I18n, settings: Settings):
        super().__init__()
        self.i18n, self.settings = i18n, settings
        self.transcriber = TranscribeRunner(self)
        self.setup_runner = SetupRunner(self)
        self.local_runner = LocalFixRunner(self)
        self.review_back = "export"
        self.resize(900, 680)

        central = QWidget()
        outer = QVBoxLayout(central)
        top = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight: 600; font-size: 15px;")
        top.addWidget(self.title_label)
        top.addStretch(1)
        self.settings_button = QToolButton()
        self.settings_button.setText("⚙")
        self.settings_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.settings_button)
        self.repair_action = menu.addAction("")
        self.repair_action.triggered.connect(self.open_repair)
        self.downloads_action = menu.addAction("")
        self.downloads_action.triggered.connect(self.open_downloads)
        self.settings_button.setMenu(menu)
        top.addWidget(self.settings_button)
        self.lang_button = QToolButton()
        self.lang_button.clicked.connect(self._toggle_language)
        top.addWidget(self.lang_button)
        outer.addLayout(top)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.pages: dict[str, QWidget] = {}
        for name in PAGES:
            self.set_page_widget(name, QWidget())
        self.setup_view = SetupView(i18n, settings, self.setup_runner)
        self.setup_view.completed.connect(self._on_setup_completed)
        self.set_page_widget("setup", self.setup_view)
        self.home_view = HomeView(i18n, settings)
        self.flow_view = FlowView(i18n, settings, self.transcriber, before_transcribe=self._free_graphics_card)
        self.home_view.audio_selected.connect(self._open_audio)
        self.home_view.recent_opened.connect(self._open_recent)
        self.flow_view.back_home.connect(self._go_home)
        self.set_page_widget("home", self.home_view)
        self.set_page_widget("flow", self.flow_view)
        self.export_view = ExportView(i18n)
        self.local_view = LocalView(i18n, settings, self.local_runner)
        self.review_view = ReviewView(i18n)
        self.flow_view.export_requested.connect(self._open_export)
        self.flow_view.local_requested.connect(self._open_local)
        self.export_view.back.connect(lambda: self.show_page("flow"))
        self.export_view.review_ready.connect(self._open_review)
        self.local_view.back.connect(lambda: self.show_page("flow"))
        self.local_view.review_ready.connect(self._open_local_review)
        self.local_view.export_instead.connect(
            lambda: self._open_export(self.local_view.raw_path, self.local_view.names, self.local_view.language))
        self.review_view.back.connect(lambda: self.show_page(self.review_back))
        self.review_view.saved.connect(lambda path: self.home_view.refresh_recents())
        self.set_page_widget("export", self.export_view)
        self.set_page_widget("local", self.local_view)
        self.set_page_widget("review", self.review_view)

        i18n.language_changed.connect(self._on_language)
        self._on_language(i18n.language)
        self.show_page("home" if model_ready(settings) else "setup")

    def set_page_widget(self, name: str, widget: QWidget) -> None:
        old = self.pages.get(name)
        current = old is not None and self.stack.currentWidget() is old
        self.pages[name] = widget
        self.stack.addWidget(widget)
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()
        if current:
            self.stack.setCurrentWidget(widget)

    def show_page(self, name: str) -> None:
        self.stack.setCurrentWidget(self.pages[name])

    def current_page(self) -> str:
        w = self.stack.currentWidget()
        return next(n for n, p in self.pages.items() if p is w)

    def open_repair(self) -> None:
        if self.busy():
            return
        self.local_runner.stop_server()     # setup's test runs the transcriber on the graphics card
        self.setup_view.settings = self.settings
        self.setup_view.refresh()
        self.show_page("setup")

    def open_downloads(self) -> None:
        if self.busy():
            downloads_dialog.show_message(self, self.i18n.tr("busy.finish_first"))
            return
        # self.settings, the object every page holds: a move updates it in place, so no page
        # can later save an old copy that points at the deleted files.
        dlg = DownloadsDialog(self.i18n, self.settings, self, before_move=self._free_graphics_card)
        dlg.repair_needed.connect(self.open_repair)
        downloads_dialog.run_dialog(dlg)

    def check_downloads_folder(self) -> None:
        """At start: a downloads folder on a drive that isn't plugged in. Try again, or pick another."""
        if not (self.settings.setup_done and self.settings.downloads_dir):
            return
        while not Path(self.settings.downloads_dir).is_dir():
            answer = downloads_dialog.ask_missing(self, self.i18n, Path(self.settings.downloads_dir))
            if answer == "retry":
                continue
            if answer != "choose":
                return
            picked = downloads_dialog.pick_folder(self, Path.home())
            if picked is None:
                continue
            target = downloads.choose_target(picked)
            try:
                if not downloads.writable(target):
                    raise OSError
                downloads.set_downloads_dir(self.settings, target)
            except OSError:
                downloads_dialog.show_message(self, self.i18n.tr("setup.location.unwritable"))
                continue
            self.open_repair()      # the new folder is empty: setup downloads what is missing
            return

    def _on_setup_completed(self, new: Settings) -> None:
        for f, v in vars(new).items():
            setattr(self.settings, f, v)
        self.save_settings()
        self.show_page("home")

    def _open_audio(self, audio: str) -> None:
        self.flow_view.begin(audio)
        self.show_page("flow")

    def _open_recent(self, item) -> None:
        self.flow_view.open_result(item, from_recents=True)
        self.show_page("flow")

    def _open_export(self, raw_path: str, names: list, language: str) -> None:
        self.export_view.load(raw_path, names, language)
        self.show_page("export")

    def _open_review(self, fixes) -> None:
        ev = self.export_view
        self.review_view.load(ev.raw_path, ev.lines, fixes, ev.language)
        self.review_back = "export"
        self.show_page("review")

    def _open_local(self, raw_path: str, names: list, language: str) -> None:
        self.local_view.start(raw_path, names, language)
        self.show_page("local")

    def _open_local_review(self, fixes) -> None:
        lv = self.local_view
        self.review_view.load(lv.raw_path, lv.lines, fixes, lv.language, local=True)
        self.review_back = "flow"
        self.show_page("review")

    def _free_graphics_card(self) -> None:
        """Before a transcription: Whisper and the AI helper don't both fit in the graphics memory."""
        self.local_runner.stop_server()
        reap_stale()    # one left behind by an earlier run that crashed

    def _go_home(self) -> None:
        self.home_view.refresh_recents()
        self.show_page("home")

    def busy(self) -> bool:
        return (self.transcriber.is_running() or self.setup_runner.is_running()
                or self.local_runner.is_running() or self.flow_view.llm_download.is_running())

    def save_settings(self) -> None:
        save_settings(self.settings, paths.settings_file())

    def _toggle_language(self) -> None:
        self.i18n.set_language("en" if self.i18n.language == "fa" else "fa")
        self.settings.ui_language = self.i18n.language
        self.save_settings()

    def _on_language(self, lang: str) -> None:
        QApplication.setLayoutDirection(Qt.RightToLeft if self.i18n.is_rtl() else Qt.LeftToRight)
        self.setWindowTitle(self.i18n.tr("app.title"))
        self.title_label.setText(self.i18n.tr("app.title"))
        self.lang_button.setText(self.i18n.tr("lang.switch"))
        self.settings_button.setToolTip(self.i18n.tr("settings.menu"))
        self.repair_action.setText(self.i18n.tr("settings.repair"))
        self.downloads_action.setText(self.i18n.tr("settings.downloads"))
        for page in self.pages.values():
            if hasattr(page, "retranslate"):
                page.retranslate()

    def confirm_quit(self) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setText(self.i18n.tr("confirm.quit_busy"))
        quit_btn = box.addButton(self.i18n.tr("confirm.yes_quit"), QMessageBox.AcceptRole)
        box.addButton(self.i18n.tr("confirm.keep_working"), QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is quit_btn

    def closeEvent(self, event) -> None:
        if self.busy() and not self.confirm_quit():
            event.ignore()
            return
        self.hide()     # disappear at once; stopping a download can take a few seconds
        self.transcriber.cancel()
        self.setup_runner.stop_and_wait()
        self.flow_view.llm_download.stop_and_wait()
        self.local_runner.stop_server()
        event.accept()
