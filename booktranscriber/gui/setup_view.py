"""First-run setup: welcome → downloading → ready, with friendly errors (spec §4.1)."""
import dataclasses

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QProgressBar, QStackedLayout, QVBoxLayout,
                               QWidget)

from .. import paths
from ..i18n import fmt_bytes, fmt_duration, fmt_number
from ..settings import Settings
from ..setup_runner import ITEMS, MODEL_ESTIMATE, SetupProgress, make_plan
from ..syscheck import detect_system, find_existing_model, source_checkout_dir
from .widgets import ProgressRow, body_label, primary_button, secondary_button, title_label

ASSUMED_SPEED = 4_000_000   # bytes/s, for the welcome screen's time estimate
STATES = ("welcome", "downloading", "ready", "error")


class SetupView(QWidget):
    completed = Signal(object)

    def __init__(self, i18n, settings: Settings, runner, parent=None):
        super().__init__(parent)
        self.i18n, self.settings, self.runner = i18n, settings, runner
        self.info = self.existing = self.plan = None
        self.last_done = 0
        self.error_kind = None
        self.result: Settings | None = None
        self.paused = False

        self.stack = QStackedLayout(self)
        self.pages = {}
        for name, build in (("welcome", self._build_welcome), ("downloading", self._build_downloading),
                            ("ready", self._build_ready), ("error", self._build_error)):
            page = QWidget()
            build(page)
            self.pages[name] = page
            self.stack.addWidget(page)

        runner.progress.connect(self._on_progress)
        runner.finished.connect(self._on_finished)
        runner.failed.connect(self._on_failed)
        self.retranslate()
        self.refresh()

    # --- building -----------------------------------------------------------
    def _build_welcome(self, page):
        lay = QVBoxLayout(page)
        lay.addStretch(1)
        icon = QLabel("📚🎙️")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 40px;")
        lay.addWidget(icon)
        self.welcome_title = title_label()
        self.welcome_title.setAlignment(Qt.AlignCenter)
        self.welcome_body = body_label()
        self.welcome_body.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.welcome_title)
        lay.addWidget(self.welcome_body)
        self.check_line, self.time_line, self.space_line = QLabel(), QLabel(), QLabel()
        for name, l in (("check_line", self.check_line), ("time_line", self.time_line),
                        ("space_line", self.space_line)):
            l.setObjectName(name)
            l.setWordWrap(True)
            lay.addWidget(l)
        self.reuse_box = QCheckBox()
        self.reuse_box.setChecked(True)
        self.reuse_box.toggled.connect(self._update_welcome)
        lay.addWidget(self.reuse_box)
        self.start_button = primary_button()
        self.start_button.clicked.connect(self.start)
        lay.addWidget(self.start_button, 0, Qt.AlignCenter)
        lay.addStretch(2)

    def _build_downloading(self, page):
        lay = QVBoxLayout(page)
        self.dl_title = title_label()
        self.resume_note = body_label()
        lay.addWidget(self.dl_title)
        lay.addWidget(self.resume_note)
        head = QHBoxLayout()
        self.overall_label = QLabel()
        self.overall_label.setStyleSheet("font-weight: 600;")
        self.overall_status = QLabel()
        self.overall_status.setObjectName("overall_status")
        head.addWidget(self.overall_label)
        head.addStretch(1)
        head.addWidget(self.overall_status)
        lay.addLayout(head)
        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setTextVisible(False)
        lay.addWidget(self.overall_bar)
        self.rows = {}
        for item in ITEMS:
            self.rows[item] = ProgressRow()
            lay.addWidget(self.rows[item])
        lay.addStretch(1)
        self.pause_button = secondary_button()
        self.pause_button.clicked.connect(self._pause_or_continue)
        lay.addWidget(self.pause_button, 0, Qt.AlignRight)

    def _build_ready(self, page):
        lay = QVBoxLayout(page)
        lay.addStretch(1)
        icon = QLabel("🎉")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 44px;")
        lay.addWidget(icon)
        self.ready_title = title_label()
        self.ready_title.setAlignment(Qt.AlignCenter)
        self.ready_body = body_label()
        self.ready_body.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.ready_title)
        lay.addWidget(self.ready_body)
        self.go_button = primary_button()
        self.go_button.clicked.connect(lambda: self.completed.emit(self.result))
        lay.addWidget(self.go_button, 0, Qt.AlignCenter)
        lay.addStretch(2)

    def _build_error(self, page):
        lay = QVBoxLayout(page)
        lay.addStretch(1)
        self.error_title = title_label()
        self.error_body = body_label()
        self.error_body.setObjectName("error_body")
        lay.addWidget(self.error_title)
        lay.addWidget(self.error_body)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.details_button = secondary_button()
        self.details_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.logs_dir()))))
        self.cpu_button = secondary_button()
        self.cpu_button.clicked.connect(self._continue_on_cpu)
        self.retry_button = primary_button()
        self.retry_button.clicked.connect(self._retry)
        for b in (self.details_button, self.cpu_button, self.retry_button):
            buttons.addWidget(b)
        lay.addLayout(buttons)
        lay.addStretch(2)

    # --- state --------------------------------------------------------------
    def state(self) -> str:
        return STATES[self.stack.currentIndex()]

    def _show(self, state: str) -> None:
        self.stack.setCurrentWidget(self.pages[state])

    def refresh(self) -> None:
        """Check the computer again and show the welcome screen."""
        self.info = detect_system(paths.data_dir())
        root = source_checkout_dir()
        model = make_plan(self.info, None).whisper_model
        self.existing = find_existing_model([root / "models"], model) if root else None
        self.reuse_box.setVisible(self.existing is not None)
        self._update_welcome()
        self._show("welcome")

    def _current_plan(self):
        reuse = self.existing if self.existing is not None and self.reuse_box.isChecked() else None
        return make_plan(self.info, reuse)

    def _update_welcome(self) -> None:
        if self.info is None:
            return
        tr, lang = self.i18n.tr, self.i18n.language
        plan = self._current_plan()
        gpu = self.info.gpu
        self.check_line.setText("✔ " + (tr("setup.check.gpu_ok", gpu=gpu.name) if gpu else tr("setup.check.no_gpu")))
        self.time_line.setText("⏱ " + tr("setup.check.time",
                                         time=fmt_duration(plan.needed_bytes / ASSUMED_SPEED, lang)))
        enough = self.info.free_bytes >= plan.needed_bytes
        key = "setup.check.space" if enough else "setup.check.space_low"
        self.space_line.setText("💾 " + tr(key, needed=fmt_bytes(plan.needed_bytes, lang),
                                           free=fmt_bytes(self.info.free_bytes, lang)))
        self.space_line.setStyleSheet("" if enough else "color: #c0392b;")
        self.start_button.setEnabled(enough)
        self.reuse_box.setText(tr("setup.reuse_existing", size=fmt_bytes(MODEL_ESTIMATE[plan.whisper_model], lang)))

    def start(self) -> None:
        self.plan = self._current_plan()
        self.paused = False
        self.error_kind = None
        for item in ITEMS:
            self._set_row_waiting(item)
        self.rows["gpu"].setVisible(self.plan.include_gpu)
        self.runner.start(self.plan, self.settings)
        self.retranslate()
        self._show("downloading")

    def _pause_or_continue(self) -> None:
        if self.paused:
            self.start()
        else:
            self.runner.pause()

    def _retry(self) -> None:
        if self.error_kind == "disk":
            self.refresh()
        else:
            self.start()

    def _continue_on_cpu(self) -> None:
        self.settings = dataclasses.replace(self.settings, device="cpu")
        self.start()

    # --- runner events --------------------------------------------------------
    def _set_row_waiting(self, item: str) -> None:
        self.rows[item].set_state("waiting", self.i18n.tr("setup.item.waiting"))

    def _on_progress(self, p: SetupProgress) -> None:
        tr, lang = self.i18n.tr, self.i18n.language
        self.last_done = p.overall_done
        pct = int(100 * p.overall_done / p.overall_total) if p.overall_total else 0
        self.overall_bar.setValue(pct)
        if p.eta_seconds is not None:
            self.overall_status.setText(tr("setup.overall_status", pct=fmt_number(pct, lang),
                                           time=fmt_duration(p.eta_seconds, lang)))
        else:
            self.overall_status.setText(tr("setup.overall_status_noeta", pct=fmt_number(pct, lang)))
        active = ITEMS.index(p.item)
        for item in ITEMS[:active]:
            self.rows[item].set_state("done", tr("setup.item.done"))
        row = self.rows[p.item]
        if p.item_total and p.item_done >= p.item_total:
            row.set_state("done", tr("setup.item.done"))
        elif p.item == "test":
            row.set_state("testing", tr("setup.item.testing"))
        else:
            row.set_state("active", tr("setup.item.bytes", done=fmt_bytes(p.item_done, lang),
                                       total=fmt_bytes(p.item_total, lang)),
                          p.item_done / p.item_total if p.item_total else None)

    def _on_finished(self, settings: Settings) -> None:
        self.result = settings
        self._show("ready")

    def _on_failed(self, kind: str) -> None:
        if kind == "cancelled":
            self.paused = True
            self.pause_button.setText(self.i18n.tr("setup.continue"))
            self._show("downloading")
            return
        self.error_kind = kind
        self._fill_error()
        self._show("error")

    def _fill_error(self) -> None:
        tr, lang, kind = self.i18n.tr, self.i18n.language, self.error_kind
        if kind is None:
            return
        self.error_title.setText(tr(f"error.{kind}.title"))
        err = getattr(self.runner, "last_error", None)    # the setup's own measurement, when it has one
        if err is not None and err.kind == "disk":
            needed, free = fmt_bytes(err.needed, lang), fmt_bytes(err.free, lang)
        else:
            needed = fmt_bytes(self.plan.needed_bytes if self.plan else 0, lang)
            free = fmt_bytes(self.info.free_bytes if self.info else 0, lang)
        self.error_body.setText(tr(f"error.{kind}.body", done=fmt_bytes(self.last_done, lang), needed=needed,
                                   free=free) if kind in ("network", "disk") else tr(f"error.{kind}.body"))
        self.retry_button.setText(tr("error.check_again" if kind == "disk" else "error.try_again"))
        self.cpu_button.setText(tr("error.use_cpu"))
        self.cpu_button.setVisible(kind == "gpu")
        self.details_button.setText(tr("error.details"))
        self.details_button.setVisible(kind == "test")

    def retranslate(self) -> None:
        tr = self.i18n.tr
        self.welcome_title.setText(tr("setup.welcome.title"))
        self.welcome_body.setText(tr("setup.welcome.body"))
        self.start_button.setText(tr("setup.start"))
        self.dl_title.setText(tr("setup.downloading.title"))
        self.resume_note.setText(tr("setup.resume_note"))
        self.overall_label.setText(tr("setup.overall"))
        self.pause_button.setText(tr("setup.continue" if self.paused else "setup.pause"))
        for item in ITEMS:
            self.rows[item].name.setText(tr(f"setup.item.{item}"))
        self.ready_title.setText(tr("setup.ready.title"))
        self.ready_body.setText(tr("setup.ready.body"))
        self.go_button.setText(tr("setup.ready.go"))
        self._update_welcome()
        self._fill_error()
