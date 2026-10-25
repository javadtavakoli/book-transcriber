"""Small shared widgets and styling."""
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

PRIMARY = ("QPushButton { background: #2f6fde; color: white; border-radius: 9px; padding: 9px 18px;"
           " font-weight: 600; } QPushButton:disabled { background: #a9b9d8; }")
SECONDARY = "QPushButton { background: #eef1f5; color: #333; border-radius: 9px; padding: 9px 18px; }"


def primary_button(parent=None) -> QPushButton:
    b = QPushButton(parent)
    b.setStyleSheet(PRIMARY)
    return b


def secondary_button(parent=None) -> QPushButton:
    b = QPushButton(parent)
    b.setStyleSheet(SECONDARY)
    return b


def title_label(parent=None) -> QLabel:
    l = QLabel(parent)
    l.setStyleSheet("font-size: 20px; font-weight: 650;")
    l.setWordWrap(True)
    return l


def body_label(parent=None) -> QLabel:
    l = QLabel(parent)
    l.setWordWrap(True)
    l.setStyleSheet("color: #555;")
    return l


class ProgressRow(QWidget):
    """One setup item: icon, name, status text, and its own bar while active."""
    ICONS = {"waiting": "⏳", "active": "⬇️", "done": "✅", "testing": "🧪"}

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        row = QHBoxLayout()
        self.icon, self.name, self.status = QLabel(), QLabel(), QLabel()
        self.status.setStyleSheet("color: #6b7280;")
        row.addWidget(self.icon)
        row.addWidget(self.name, 1)
        row.addWidget(self.status)
        lay.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(8)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.state = "waiting"

    def set_state(self, state: str, status: str, fraction: float | None = None) -> None:
        self.state = state
        self.icon.setText(self.ICONS[state])
        self.status.setText(status)
        self.bar.setVisible(state == "active" and fraction is not None)
        if fraction is not None:
            self.bar.setValue(int(fraction * 100))


def retry_text(i18n, retry: int) -> str:
    """'No internet connection. Trying again in 5 seconds (3 of 30)…' while setup waits to retry."""
    from .. import setup_runner
    from ..i18n import fmt_number
    lang = i18n.language
    return i18n.tr("net.retrying", secs=fmt_number(int(setup_runner.RETRY_DELAY), lang),
                   n=fmt_number(retry, lang), max=fmt_number(setup_runner.NETWORK_RETRIES, lang))
