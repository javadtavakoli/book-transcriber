"""After a recording is chosen: names (optional) → transcribing → result, one step at a time."""
import dataclasses
import os
from datetime import datetime

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QStackedLayout,
                               QToolButton, QVBoxLayout, QWidget)

from .. import paths
from ..engine import output_path
from ..i18n import fmt_duration
from ..namelists import build_prompt, import_prompt_file, list_lists, load_list, parse_names, save_list
from ..recents import RecentItem, add_recent
from ..settings import save_settings
from .runners import TranscribeJob
from .widgets import body_label, primary_button, secondary_button, title_label

STATES = ("names", "transcribing", "result")
LANGUAGE_CHOICES = [("fa", "فارسی"), ("en", "English"), ("ar", "العربية"), ("ru", "Русский"),
                    ("de", "Deutsch"), ("fr", "Français"), ("tr", "Türkçe")]
DEVICES = ("auto", "cuda", "cpu")


def folder_writable(folder: str) -> bool:
    return os.path.isdir(folder) and os.access(folder, os.W_OK)


def set_text_direction(widget, language: str) -> None:
    widget.setLayoutDirection(Qt.RightToLeft if language in ("fa", "ar") else Qt.LeftToRight)


class FlowView(QWidget):
    transcribed = Signal(object)
    back_home = Signal()

    def __init__(self, i18n, settings, runner, parent=None):
        super().__init__(parent)
        self.i18n, self.settings, self.runner = i18n, settings, runner
        self.audio = None
        self.job: TranscribeJob | None = None
        self.item: RecentItem | None = None
        self.total = 0.0
        self.problem_kind = None

        self.stack = QStackedLayout(self)
        self.pages = {}
        for name, build in (("names", self._build_names), ("transcribing", self._build_transcribing),
                            ("result", self._build_result)):
            page = QWidget()
            build(page)
            self.pages[name] = page
            self.stack.addWidget(page)

        runner.loaded.connect(self._on_loaded)
        runner.duration.connect(self._on_duration)
        runner.segment.connect(self._on_segment)
        runner.progress.connect(self._on_progress)
        runner.finished.connect(self._on_finished)
        runner.failed.connect(self._on_failed)
        self.retranslate()

    # --- names step -----------------------------------------------------------
    def _build_names(self, page):
        lay = QVBoxLayout(page)
        self.home_button_names = QPushButton(flat=True)
        self.home_button_names.clicked.connect(self.back_home)
        lay.addWidget(self.home_button_names, 0, Qt.AlignLeft)
        self.file_label = body_label()
        lay.addWidget(self.file_label)
        self.names_title = title_label()
        self.names_hint = body_label()
        lay.addWidget(self.names_title)
        lay.addWidget(self.names_hint)
        tools = QHBoxLayout()
        self.list_combo = QComboBox()
        self.list_combo.activated.connect(self._load_selected_list)
        self.list_combo.currentIndexChanged.connect(self._load_selected_list)
        self.import_button = secondary_button()
        self.import_button.clicked.connect(self._import_file)
        tools.addWidget(self.list_combo, 1)
        tools.addWidget(self.import_button)
        lay.addLayout(tools)
        self.names_edit = QPlainTextEdit()
        lay.addWidget(self.names_edit, 1)
        save_row = QHBoxLayout()
        self.save_box = QCheckBox()
        self.save_name = QLineEdit()
        save_row.addWidget(self.save_box)
        save_row.addWidget(self.save_name, 1)
        lay.addLayout(save_row)

        self.advanced_toggle = QToolButton(checkable=True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        lay.addWidget(self.advanced_toggle, 0, Qt.AlignLeft)
        self.advanced = QWidget()
        form = QFormLayout(self.advanced)
        self.language_combo = QComboBox(editable=True)
        for code, name in LANGUAGE_CHOICES:
            self.language_combo.addItem(f"{name} ({code})", code)
        self.model_combo = QComboBox()
        self.model_combo.setEnabled(False)
        self.timestamps_box = QCheckBox()
        self.device_combo = QComboBox()
        for d in DEVICES:
            self.device_combo.addItem(d, d)
        self.lbl_language, self.lbl_model, self.lbl_device = QLabel(), QLabel(), QLabel()
        form.addRow(self.lbl_language, self.language_combo)
        form.addRow(self.lbl_model, self.model_combo)
        form.addRow(self.lbl_device, self.device_combo)
        form.addRow(self.timestamps_box)
        self.advanced.hide()
        lay.addWidget(self.advanced)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.skip_button = secondary_button()
        self.skip_button.clicked.connect(lambda: self._start([]))
        self.continue_button = primary_button()
        self.continue_button.clicked.connect(lambda: self._start(self.names(), save=True))
        buttons.addWidget(self.skip_button)
        buttons.addWidget(self.continue_button)
        lay.addLayout(buttons)

    def _toggle_advanced(self, on: bool) -> None:
        self.advanced.setVisible(on)
        self.advanced_toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)

    def names(self) -> list[str]:
        return parse_names(self.names_edit.toPlainText())

    def refresh_lists(self) -> None:
        self.list_combo.blockSignals(True)
        self.list_combo.clear()
        self.list_combo.addItem(self.i18n.tr("flow.names.load"), None)
        for name in list_lists(paths.namelists_dir()):
            self.list_combo.addItem(name, name)
        self.list_combo.blockSignals(False)

    def _load_selected_list(self, index: int) -> None:
        name = self.list_combo.itemData(index)
        if name:
            self.names_edit.setPlainText("\n".join(load_list(paths.namelists_dir(), name)))
            self.save_name.setText(name)

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.import_button.text(), os.path.expanduser("~"),
                                              "Text (*.txt)")
        if path:
            self.names_edit.setPlainText("\n".join(import_prompt_file(path)))

    def language(self) -> str:
        text = self.language_combo.currentText().strip()
        idx = self.language_combo.findText(text)
        if idx >= 0 and self.language_combo.itemData(idx):
            return self.language_combo.itemData(idx)
        if text.endswith(")") and "(" in text:
            return text.rsplit("(", 1)[1].rstrip(")").strip()
        return text or "fa"

    def begin(self, audio: str) -> None:
        self.audio = audio
        self.file_label.setText("🎙️ " + os.path.basename(audio))
        self.names_edit.clear()
        self.save_box.setChecked(False)
        self.save_name.clear()
        self.refresh_lists()
        s = self.settings
        idx = self.language_combo.findData(s.language)
        if idx >= 0:
            self.language_combo.setCurrentIndex(idx)
        else:
            self.language_combo.setEditText(s.language)
        self.model_combo.clear()
        self.model_combo.addItem(s.whisper_model)
        self.timestamps_box.setChecked(s.timestamps)
        self.device_combo.setCurrentIndex(max(0, self.device_combo.findData(s.device)))
        set_text_direction(self.names_edit, s.language)
        self._show("names")

    def ask_save_path(self, default: str) -> str | None:
        start = os.path.join(os.path.expanduser("~/Documents"), os.path.basename(default))
        path, _ = QFileDialog.getSaveFileName(self, self.i18n.tr("flow.choose_location"), start, "Text (*.txt)")
        return path or None

    def _start(self, names: list[str], save: bool = False) -> None:
        if save and names and self.save_box.isChecked() and self.save_name.text().strip():
            save_list(paths.namelists_dir(), self.save_name.text(), names)
        lang = self.language()
        self.settings.language = lang
        self.settings.timestamps = self.timestamps_box.isChecked()
        self.settings.device = self.device_combo.currentData()
        save_settings(self.settings, paths.settings_file())

        out = output_path(self.audio)
        if not folder_writable(os.path.dirname(out)):
            out = self.ask_save_path(out)
            if not out:
                return
        self.job = TranscribeJob(audio=self.audio, out=out,
                                 model=self.settings.whisper_model_path or self.settings.whisper_model,
                                 download_root=None, language=lang, prompt=build_prompt(names, lang),
                                 timestamps=self.settings.timestamps, device=self.settings.device)
        self._run(self.job)

    def _run(self, job: TranscribeJob) -> None:
        self.job = job
        self.total = 0.0
        self.live_text.clear()
        set_text_direction(self.live_text, job.language)
        self.progress_bar.setValue(0)
        self.eta_label.clear()
        self.status_label.setText(self.i18n.tr("flow.loading"))
        self._set_problem(None)
        self.cancel_button.show()
        self.runner.start(job)
        self._show("transcribing")

    # --- transcribing step ------------------------------------------------------
    def _build_transcribing(self, page):
        lay = QVBoxLayout(page)
        self.trans_title = title_label()
        lay.addWidget(self.trans_title)
        self.status_label = body_label()
        lay.addWidget(self.status_label)
        row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.eta_label = QLabel()
        row.addWidget(self.progress_bar, 1)
        row.addWidget(self.eta_label)
        lay.addLayout(row)
        self.live_text = QPlainTextEdit(readOnly=True)
        lay.addWidget(self.live_text, 1)
        self.problem_label = QLabel()
        self.problem_label.setWordWrap(True)
        self.problem_label.setStyleSheet("color: #c0392b; font-size: 15px;")
        lay.addWidget(self.problem_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.details_button = secondary_button()
        self.details_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.logs_dir()))))
        self.problem_button = primary_button()
        self.problem_button.clicked.connect(self._problem_action)
        self.cancel_button = secondary_button()
        self.cancel_button.clicked.connect(self._cancel)
        for b in (self.details_button, self.problem_button, self.cancel_button):
            buttons.addWidget(b)
        lay.addLayout(buttons)
        self._set_problem(None)

    def confirm_cancel(self) -> bool:
        box = QMessageBox(self)
        box.setText(self.i18n.tr("flow.confirm_cancel"))
        yes = box.addButton(self.i18n.tr("flow.confirm_cancel_yes"), QMessageBox.AcceptRole)
        box.addButton(self.i18n.tr("flow.confirm_cancel_no"), QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _cancel(self) -> None:
        if self.confirm_cancel():
            self.runner.cancel()
            self._show("names")

    def _on_loaded(self, backend: str) -> None:
        self.status_label.setText(self.i18n.tr("flow.transcribing"))

    def _on_duration(self, seconds: float) -> None:
        self.total = seconds

    def _on_segment(self, start: float, text: str) -> None:
        self.live_text.appendPlainText(text)

    def _on_progress(self, done: float, total: float, eta: float) -> None:
        self.progress_bar.setValue(int(100 * done / total) if total else 0)
        self.eta_label.setText(self.i18n.tr("flow.eta", time=fmt_duration(eta, self.i18n.language)))

    def _on_finished(self, out: str, segments: int) -> None:
        self.cancel_button.hide()
        if segments == 0:
            self._set_problem("no_speech")
            return
        self.progress_bar.setValue(100)
        self.item = RecentItem(self.audio, out, None, datetime.now().isoformat(timespec="seconds"))
        add_recent(paths.recents_file(), self.item)
        self.open_result(self.item)
        self.transcribed.emit(self.item)

    def _on_failed(self, kind: str, message: str) -> None:
        self.cancel_button.hide()
        self._set_problem(kind if kind in ("bad_audio", "not_found", "model", "write") else "unknown")

    def _set_problem(self, kind: str | None) -> None:
        self.problem_kind = kind
        tr = self.i18n.tr
        self.problem_label.setVisible(kind is not None)
        self.problem_button.setVisible(kind is not None)
        self.details_button.setVisible(kind == "unknown")
        if kind is None:
            return
        self.problem_label.setText(tr("flow.no_speech" if kind == "no_speech" else f"flow.err.{kind}"))
        action = {"no_speech": "flow.another_file", "bad_audio": "flow.another_file",
                  "not_found": "flow.another_file", "model": "flow.try_cpu", "write": "flow.choose_location",
                  "unknown": "flow.try_again"}[kind]
        self.problem_button.setText(tr(action))
        self.details_button.setText(tr("flow.details"))

    def _problem_action(self) -> None:
        kind = self.problem_kind
        if kind in ("no_speech", "bad_audio", "not_found"):
            self.back_home.emit()
        elif kind == "model":
            self.settings.device = "cpu"
            save_settings(self.settings, paths.settings_file())
            self._run(dataclasses.replace(self.job, device="cpu"))
        elif kind == "write":
            out = self.ask_save_path(self.job.out)
            if out:
                self._run(dataclasses.replace(self.job, out=out))
        else:
            self._run(self.job)

    # --- result step (extended by the fix/export flow) ---------------------------
    def _build_result(self, page):
        lay = QVBoxLayout(page)
        self.home_button_result = QPushButton(flat=True)
        self.home_button_result.clicked.connect(self.back_home)
        lay.addWidget(self.home_button_result, 0, Qt.AlignLeft)
        self.result_title = title_label()
        lay.addWidget(self.result_title)
        self.result_text = QPlainTextEdit(readOnly=True)
        lay.addWidget(self.result_text, 1)
        row = QHBoxLayout()
        self.saved_label = body_label()
        self.open_folder_button = secondary_button()
        self.open_folder_button.clicked.connect(self._open_folder)
        row.addWidget(self.saved_label, 1)
        row.addWidget(self.open_folder_button)
        lay.addLayout(row)
        self.result_layout = lay

    def open_result(self, item: RecentItem) -> None:
        self.item = item
        self.audio = item.audio
        try:
            text = open(item.raw_path, encoding="utf-8").read()
        except OSError:
            text = ""
        self.result_text.setPlainText(text)
        set_text_direction(self.result_text, self.job.language if self.job else self.settings.language)
        self.saved_label.setText(self.i18n.tr("result.saved_at", path=item.raw_path))
        self._show("result")

    def _open_folder(self) -> None:
        if self.item:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.item.raw_path)))

    # --- common -------------------------------------------------------------------
    def state(self) -> str:
        return STATES[self.stack.currentIndex()]

    def _show(self, state: str) -> None:
        self.stack.setCurrentWidget(self.pages[state])

    def retranslate(self) -> None:
        tr = self.i18n.tr
        self.home_button_names.setText(tr("flow.home"))
        self.home_button_result.setText(tr("flow.home"))
        self.names_title.setText(tr("flow.names.title"))
        self.names_hint.setText(tr("flow.names.hint"))
        self.import_button.setText(tr("flow.names.import"))
        self.save_box.setText(tr("flow.names.save"))
        self.save_name.setPlaceholderText(tr("flow.names.save_placeholder"))
        self.advanced_toggle.setText(tr("flow.advanced"))
        self.lbl_language.setText(tr("flow.adv.language"))
        self.lbl_model.setText(tr("flow.adv.model"))
        self.lbl_device.setText(tr("flow.adv.device"))
        self.timestamps_box.setText(tr("flow.adv.timestamps"))
        for i, d in enumerate(DEVICES):
            self.device_combo.setItemText(i, tr(f"device.{d}"))
        if self.list_combo.count():
            self.list_combo.setItemText(0, tr("flow.names.load"))
        self.skip_button.setText(tr("flow.skip"))
        self.continue_button.setText(tr("flow.continue"))
        self.trans_title.setText(tr("flow.transcribing"))
        self.cancel_button.setText(tr("flow.cancel"))
        self.result_title.setText(tr("result.title"))
        self.open_folder_button.setText(tr("result.open_folder"))
        if self.item:
            self.saved_label.setText(tr("result.saved_at", path=self.item.raw_path))
        self._set_problem(self.problem_kind)
