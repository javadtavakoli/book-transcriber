"""Settings → About: name, version, what the app is, where to find it, and its license."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from .. import __version__
from .widgets import secondary_button

GITHUB_PAGE = "https://github.com/javadtavakoli/book-transcriber"


def open_url(url: str) -> None:
    """A hook, so tests never open a browser."""
    QDesktopServices.openUrl(QUrl(url))


def run_dialog(dialog: QDialog) -> None:
    dialog.exec()


class AboutDialog(QDialog):
    def __init__(self, i18n, parent=None):
        super().__init__(parent)
        tr = i18n.tr
        self.setWindowTitle(tr("about.title"))
        lay = QVBoxLayout(self)
        name = QLabel(tr("app.title"))
        name.setStyleSheet("font-weight: 600; font-size: 18px;")
        self.text = QLabel("<br>".join([
            tr("about.version", version=__version__),
            tr("about.body"),
            f'<a href="{GITHUB_PAGE}">{GITHUB_PAGE}</a>',
            tr("about.license"),
        ]))
        self.text.setTextFormat(Qt.RichText)
        self.text.setWordWrap(True)
        self.text.linkActivated.connect(open_url)
        close = secondary_button()
        close.setText(tr("downloads.close"))
        close.clicked.connect(self.accept)
        for w in (name, self.text, close):
            lay.addWidget(w)
