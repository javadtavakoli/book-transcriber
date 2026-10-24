"""Fix it here: loading the local AI helper (it takes minutes), fixing part by part, friendly errors (spec §5.2)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ..i18n import fmt_duration, fmt_number
from ..local_fix import chunk_lines
from .widgets import body_label, primary_button, secondary_button, title_label

STATES = ("loading", "fixing", "error")


class LocalView(QWidget):
    review_ready = Signal(object)    # list[LineFix]
    export_instead = Signal()
    back = Signal()

    def __init__(self, i18n, settings, runner, parent=None):
        super().__init__(parent)
        self.i18n, self.settings, self.runner = i18n, settings, runner
        self.raw_path, self.lines, self.names, self.language = "", [], [], "fa"
        self._state = "loading"
        self.error_kind = None
        self.part = (0, 0)

        lay = QVBoxLayout(self)
        self.back_button = QPushButton(flat=True)
        self.back_button.clicked.connect(self._cancel)
        lay.addWidget(self.back_button, 0, Qt.AlignLeft)
        lay.addStretch(1)
        self.title = title_label()
        lay.addWidget(self.title)
        self.body = body_label()
        lay.addWidget(self.body)
        row = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.status = QLabel()
        self.eta_label = QLabel()
        self.eta_label.setStyleSheet("color: #6b7280;")
        row.addWidget(self.bar, 1)
        row.addWidget(self.eta_label)
        lay.addWidget(self.status)
        lay.addLayout(row)
        self.fallback_note = QLabel()
        self.fallback_note.setWordWrap(True)
        self.fallback_note.setStyleSheet("background: #fff6db; border-radius: 6px; padding: 8px;")
        lay.addWidget(self.fallback_note)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #c0392b; font-size: 15px;")
        lay.addWidget(self.error_label)
        lay.addStretch(2)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = secondary_button()
        self.cancel_button.clicked.connect(self._cancel)
        self.export_button = primary_button()
        self.export_button.clicked.connect(self.export_instead)
        self.retry_button = primary_button()
        self.retry_button.clicked.connect(self._retry)
        for b in (self.cancel_button, self.export_button, self.retry_button):
            buttons.addWidget(b)
        lay.addLayout(buttons)

        runner.load_progress.connect(self._on_load_progress)
        runner.fallback.connect(self._on_fallback)
        runner.fix_progress.connect(self._on_fix_progress)
        runner.finished.connect(self._on_finished)
        runner.failed.connect(self._on_failed)
        self.eta_label.hide()
        self._set_state("loading")

    def state(self) -> str:
        return self._state

    def start(self, raw_path: str, names: list[str], language: str) -> None:
        self.raw_path, self.names, self.language = raw_path, list(names), language
        with open(raw_path, encoding="utf-8") as f:
            self.lines = f.read().splitlines()
        self._begin()

    def _begin(self) -> None:
        self.error_kind = None
        self.fallback_note.hide()
        self.bar.setValue(0)
        self.eta_label.clear()
        self.eta_label.hide()
        if self.runner.server_loaded():
            self.part = (0, len(chunk_lines(self.lines)))
            self._set_state("fixing")
        else:
            self._set_state("loading")
        self.runner.start(self.lines, self.names, self.settings)

    def _set_state(self, state: str) -> None:
        self._state = state
        working = state != "error"
        for w in (self.body, self.bar, self.status, self.cancel_button):
            w.setVisible(working)
        self.error_label.setVisible(not working)
        self.export_button.setVisible(state == "error" and self.error_kind == "memory")
        self.retry_button.setVisible(state == "error" and self.error_kind != "memory")
        if state != "loading":
            self.eta_label.hide()
        if state == "error":
            self.fallback_note.hide()
        self.retranslate()

    # --- runner events --------------------------------------------------------
    def _on_load_progress(self, fraction: float, eta) -> None:
        if self._state != "loading":
            return
        self.bar.setValue(int(100 * fraction))
        # Time left only once this computer has loaded the helper before; the first time it is a guess.
        self.eta_label.setVisible(eta is not None)
        if eta is not None:
            self.eta_label.setText(self.i18n.tr("flow.eta", time=fmt_duration(eta, self.i18n.language)))

    def _on_fallback(self) -> None:
        self.fallback_note.show()

    def _on_fix_progress(self, done: int, total: int) -> None:
        self.part = (done, total)
        self.bar.setValue(int(100 * done / total) if total else 0)
        if self._state != "fixing":
            self._set_state("fixing")
        else:
            self._retranslate_status()

    def _on_finished(self, fixes) -> None:
        self.bar.setValue(100)
        self.review_ready.emit(fixes)

    def _on_failed(self, kind: str) -> None:
        if kind == "cancelled":
            return
        self.error_kind = kind
        self._set_state("error")

    # --- actions ------------------------------------------------------------------
    def _cancel(self) -> None:
        if self._state != "error":
            self.runner.cancel()
        self.back.emit()

    def _retry(self) -> None:
        self._begin()

    def _retranslate_status(self) -> None:
        tr, lang = self.i18n.tr, self.i18n.language
        if self._state == "fixing":
            done, n = self.part
            i = min(done + 1, n) if n else 1
            self.status.setText(tr("local.fixing", i=fmt_number(i, lang), n=fmt_number(max(n, 1), lang)))
        else:
            self.status.clear()

    def retranslate(self) -> None:
        tr = self.i18n.tr
        self.back_button.setText(tr("local.back"))
        if self._state == "error":
            self.title.setText(tr("local.err.title"))
        else:
            self.title.setText(tr("local.loading.title" if self._state == "loading" else "result.local"))
        self.body.setText(tr("local.loading.body" if self._state == "loading" else "local.fixing.body"))
        self.fallback_note.setText(tr("local.fallback"))
        self.error_label.setText(tr("local.err.memory" if self.error_kind == "memory" else "local.err.generic"))
        self.cancel_button.setText(tr("flow.cancel"))
        self.export_button.setText(tr("local.export_instead"))
        self.retry_button.setText(tr("error.try_again"))
        self._retranslate_status()
