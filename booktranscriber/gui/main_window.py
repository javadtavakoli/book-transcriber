"""Main window: one page at a time (setup, home, flow, export, review), language toggle, close guard."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

from .. import paths
from ..i18n import I18n
from ..settings import Settings, save_settings
from .runners import SetupRunner, TranscribeRunner

PAGES = ("setup", "home", "flow", "export", "review")


def model_ready(settings: Settings) -> bool:
    p = settings.whisper_model_path
    return bool(settings.setup_done and p and os.path.isfile(os.path.join(p, "model.bin")))


class MainWindow(QMainWindow):
    def __init__(self, i18n: I18n, settings: Settings):
        super().__init__()
        self.i18n, self.settings = i18n, settings
        self.transcriber = TranscribeRunner(self)
        self.setup_runner = SetupRunner(self)
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

    def busy(self) -> bool:
        return self.transcriber.is_running() or self.setup_runner.is_running()

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
        self.transcriber.cancel()
        self.setup_runner.stop_and_wait()
        event.accept()
