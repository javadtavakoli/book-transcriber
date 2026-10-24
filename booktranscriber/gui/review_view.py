"""Review the AI's corrections line by line, highlighted, with a per-line revert, then save."""
import html
import os
from datetime import datetime

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import paths
from ..engine import corrected_path_for
from ..fixexport import LineFix, corrected_lines, word_diff
from ..i18n import fmt_number
from ..recents import RecentItem, add_recent, load_recents
from .widgets import body_label, primary_button, secondary_button, title_label

COL_N, COL_ORIG, COL_FIX, COL_USE = range(4)
CHANGED = ("fixed", "too_different")


def diff_html(a: str, b: str) -> tuple[str, str]:
    left, right = [], []
    for op, text in word_diff(a, b):
        t = html.escape(text)
        if op == "same":
            left.append(t)
            right.append(t)
        elif op == "removed":
            left.append(f'<span style="color:#c0392b;text-decoration:line-through">{t}</span>')
        else:
            right.append(f'<b style="color:#1e8449">{t}</b>')
    return " ".join(left), " ".join(right)


class ReviewView(QWidget):
    back = Signal()
    saved = Signal(str)

    def __init__(self, i18n, parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self.raw_path, self.lines, self.fixes, self.language = "", [], [], "fa"
        self.saved_path = None
        self.local = False

        lay = QVBoxLayout(self)
        self.back_button = QPushButton(flat=True)
        self.back_button.clicked.connect(self.back)
        lay.addWidget(self.back_button, 0, Qt.AlignLeft)
        self.title = title_label()
        lay.addWidget(self.title)
        # The local helper is a first pass that makes mistakes (spec §5.2): say so where the changes are checked.
        self.local_banner = QLabel()
        self.local_banner.setWordWrap(True)
        self.local_banner.setStyleSheet("background: #fff6db; border-radius: 6px; padding: 8px;")
        self.local_banner.hide()
        lay.addWidget(self.local_banner)
        self.summary_label = body_label()
        lay.addWidget(self.summary_label)
        self.only_changed_box = QCheckBox()
        self.only_changed_box.setChecked(True)
        self.only_changed_box.toggled.connect(self._apply_filter)
        lay.addWidget(self.only_changed_box)
        self.table = QTableWidget(0, 4)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(True)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(COL_N, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_ORIG, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_FIX, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_USE, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.saved_label = body_label()
        row.addWidget(self.saved_label, 1)
        self.open_folder_button = secondary_button()
        self.open_folder_button.clicked.connect(self._open_folder)
        self.open_folder_button.hide()
        self.copy_button = secondary_button()
        self.copy_button.clicked.connect(
            lambda: QGuiApplication.clipboard().setText("\n".join(corrected_lines(self.lines, self.fixes))))
        self.save_button = primary_button()
        self.save_button.clicked.connect(self.save)
        for b in (self.open_folder_button, self.copy_button, self.save_button):
            row.addWidget(b)
        lay.addLayout(row)
        self.retranslate()

    def load(self, raw_path: str, lines: list[str], fixes: list[LineFix], language: str,
             local: bool = False) -> None:
        self.raw_path, self.lines, self.fixes, self.language = raw_path, lines, fixes, language
        self.local = local
        self.local_banner.setVisible(local)
        self.back_button.setText(self.i18n.tr("review.back_result" if local else "review.back"))
        self.saved_path = None
        self.saved_label.clear()
        self.open_folder_button.hide()
        direction = Qt.RightToLeft if language in ("fa", "ar") else Qt.LeftToRight
        self.table.blockSignals(True)
        self.table.setRowCount(len(fixes))
        for r, fix in enumerate(fixes):
            self.table.setItem(r, COL_N, QTableWidgetItem(fmt_number(fix.n, self.i18n.language)))
            if fix.reason in CHANGED:
                left, right = diff_html(fix.original, fix.proposed)
            else:
                left = right = html.escape(fix.original)
            for col, text in ((COL_ORIG, left), (COL_FIX, right)):
                label = QLabel(text)
                label.setTextFormat(Qt.RichText)
                label.setWordWrap(True)
                label.setLayoutDirection(direction)
                label.setAlignment((Qt.AlignRight if direction == Qt.RightToLeft else Qt.AlignLeft) | Qt.AlignVCenter)
                self.table.setCellWidget(r, col, label)
            use = QTableWidgetItem()
            if fix.reason in CHANGED:
                use.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                use.setCheckState(Qt.Checked if fix.accepted else Qt.Unchecked)
                if fix.reason == "too_different":
                    use.setToolTip(self.i18n.tr("review.too_different"))
            else:
                use.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, COL_USE, use)
        self.table.blockSignals(False)
        self.table.resizeRowsToContents()
        self._apply_filter()
        self._update_summary()

    def use_fix(self, n: int) -> bool:
        return self.fixes[n - 1].accepted

    def set_use_fix(self, n: int, on: bool) -> None:
        item = self.table.item(n - 1, COL_USE)
        if self.fixes[n - 1].reason in CHANGED:
            item.setCheckState(Qt.Checked if on else Qt.Unchecked)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == COL_USE and self.fixes[item.row()].reason in CHANGED:
            self.fixes[item.row()].accepted = item.checkState() == Qt.Checked
            self._update_summary()

    def _apply_filter(self) -> None:
        only = self.only_changed_box.isChecked()
        for r, fix in enumerate(self.fixes):
            self.table.setRowHidden(r, only and fix.reason not in CHANGED)

    def _update_summary(self) -> None:
        lang = self.i18n.language
        fixed = sum(f.accepted for f in self.fixes)
        missing = sum(f.reason == "missing" for f in self.fixes)
        kept = sum(1 for f in self.fixes if f.original and not f.accepted and f.reason != "missing")
        self.summary_label.setText(self.i18n.tr("review.summary", fixed=fmt_number(fixed, lang),
                                                kept=fmt_number(kept, lang), missing=fmt_number(missing, lang)))

    def save(self) -> None:
        path = corrected_path_for(self.raw_path)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(corrected_lines(self.lines, self.fixes)) + "\n")
        self.saved_path = path
        known = next((i for i in load_recents(paths.recents_file()) if i.raw_path == self.raw_path), None)
        add_recent(paths.recents_file(), RecentItem(known.audio if known else self.raw_path, self.raw_path, path,
                                                    known.created if known else
                                                    datetime.now().isoformat(timespec="seconds")))
        self.saved_label.setText(self.i18n.tr("review.saved", path=path))
        self.open_folder_button.show()
        self.saved.emit(path)

    def _open_folder(self) -> None:
        if self.saved_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.saved_path)))

    def retranslate(self) -> None:
        tr = self.i18n.tr
        self.back_button.setText(tr("review.back_result" if self.local else "review.back"))
        self.title.setText(tr("review.title"))
        self.local_banner.setText(tr("review.local_banner"))
        self.only_changed_box.setText(tr("review.only_changed"))
        self.table.setHorizontalHeaderLabels([tr("review.col_n"), tr("review.col_original"),
                                              tr("review.col_corrected"), tr("review.col_use")])
        self.copy_button.setText(tr("review.copy"))
        self.save_button.setText(tr("review.save"))
        self.open_folder_button.setText(tr("result.open_folder"))
        if self.saved_path:
            self.saved_label.setText(tr("review.saved", path=self.saved_path))
        if self.fixes:
            self._update_summary()
