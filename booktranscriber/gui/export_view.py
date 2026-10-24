"""Fix with an online AI: numbered parts to copy, then paste the answers back (spec §5.3)."""
import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..engine import RAW_SUFFIX
from ..fixexport import ExportPart, apply_answer, build_export_parts, parse_answer
from ..i18n import fmt_number
from ..namelists import parse_names
from .flow_view import set_text_direction
from .widgets import body_label, primary_button, secondary_button, title_label


class ExportView(QWidget):
    review_ready = Signal(object)    # list[LineFix]
    back = Signal()

    def __init__(self, i18n, parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self.raw_path, self.lines, self.language = "", [], "fa"
        self.parts: list[ExportPart] = []
        self.copy_buttons: list[QPushButton] = []
        self.part_labels: list[QLabel] = []

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        self.back_button = QPushButton(flat=True)
        self.back_button.clicked.connect(self.back)
        lay.addWidget(self.back_button, 0, Qt.AlignLeft)
        self.title = title_label()
        self.howto = body_label()
        lay.addWidget(self.title)
        lay.addWidget(self.howto)
        self.names_label = QLabel()
        lay.addWidget(self.names_label)
        self.names_edit = QPlainTextEdit()
        self.names_edit.setMaximumHeight(80)
        self.names_edit.textChanged.connect(self._rebuild)
        lay.addWidget(self.names_edit)
        self.parts_box = QVBoxLayout()
        lay.addLayout(self.parts_box)
        self.save_all_button = secondary_button()
        self.save_all_button.clicked.connect(self._save_all)
        lay.addWidget(self.save_all_button, 0, Qt.AlignLeft)
        self.paste_label = QLabel()
        lay.addWidget(self.paste_label)
        self.paste_edit = QPlainTextEdit()
        self.paste_edit.setMinimumHeight(180)
        lay.addWidget(self.paste_edit)
        self.nothing_label = QLabel()
        self.nothing_label.setWordWrap(True)
        self.nothing_label.setStyleSheet("color: #c0392b;")
        self.nothing_label.hide()
        lay.addWidget(self.nothing_label)
        self.check_button = primary_button()
        self.check_button.clicked.connect(self._check)
        lay.addWidget(self.check_button, 0, Qt.AlignRight)
        self.retranslate()

    def load(self, raw_path: str, names: list[str], language: str) -> None:
        self.raw_path, self.language = raw_path, language
        with open(raw_path, encoding="utf-8") as f:
            self.lines = f.read().splitlines()
        self.paste_edit.clear()
        self.nothing_label.hide()
        set_text_direction(self.paste_edit, language)
        set_text_direction(self.names_edit, language)
        self.names_edit.blockSignals(True)
        self.names_edit.setPlainText("\n".join(names))
        self.names_edit.blockSignals(False)
        self._rebuild()

    def _rebuild(self) -> None:
        self.parts = build_export_parts(self.lines, parse_names(self.names_edit.toPlainText()))
        while self.parts_box.count():
            item = self.parts_box.takeAt(0)
            if item.layout():
                while item.layout().count():
                    w = item.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()
        self.copy_buttons, self.part_labels = [], []
        for i, _ in enumerate(self.parts):
            row = QHBoxLayout()
            label = QLabel()
            button = secondary_button()
            button.clicked.connect(lambda _=False, i=i: self.copy(i))
            row.addWidget(label, 1)
            row.addWidget(button)
            self.parts_box.addLayout(row)
            self.part_labels.append(label)
            self.copy_buttons.append(button)
        self._retranslate_parts()

    def copy(self, i: int) -> None:
        QGuiApplication.clipboard().setText(self.parts[i].text)
        b = self.copy_buttons[i]
        b.setText(self.i18n.tr("export.copied"))
        # Bound to the button, so the timer is dropped if the button is deleted first.
        QTimer.singleShot(2500, b, lambda: b.setText(self.i18n.tr("export.copy")))

    def ask_folder(self) -> str | None:
        d = QFileDialog.getExistingDirectory(self, self.save_all_button.text(), os.path.dirname(self.raw_path))
        return d or None

    def _save_all(self) -> None:
        folder = self.ask_folder()
        if not folder:
            return
        name = os.path.basename(self.raw_path)
        stem = name[: -len(RAW_SUFFIX)] if name.endswith(RAW_SUFFIX) else os.path.splitext(name)[0]
        for p in self.parts:
            path = os.path.join(folder, f"{stem} - part {p.index} of {p.total}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(p.text + "\n")

    def _check(self) -> None:
        answer = parse_answer(self.paste_edit.toPlainText())
        if not answer:
            self.nothing_label.show()
            return
        self.nothing_label.hide()
        self.review_ready.emit(apply_answer(self.lines, answer))

    def _retranslate_parts(self) -> None:
        tr, lang = self.i18n.tr, self.i18n.language
        for p, label, button in zip(self.parts, self.part_labels, self.copy_buttons):
            label.setText(tr("export.part", i=fmt_number(p.index, lang), n=fmt_number(p.total, lang)))
            button.setText(tr("export.copy"))

    def retranslate(self) -> None:
        tr = self.i18n.tr
        self.back_button.setText(tr("export.back"))
        self.title.setText(tr("export.title"))
        self.howto.setText(tr("export.howto"))
        self.names_label.setText(tr("export.names"))
        self.save_all_button.setText(tr("export.save_all"))
        self.paste_label.setText(tr("export.paste_label"))
        self.nothing_label.setText(tr("export.nothing"))
        self.check_button.setText(tr("export.check"))
        self._retranslate_parts()
