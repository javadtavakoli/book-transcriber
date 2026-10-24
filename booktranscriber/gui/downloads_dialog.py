"""Settings → Downloads folder: where the big downloads live, and moving them somewhere else."""
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QVBoxLayout)

from .. import downloads, paths
from ..i18n import fmt_bytes
from .widgets import primary_button, secondary_button

ERROR_STYLE = "color: #c0392b;"


# --- questions, one function each so tests never block on a modal box ---------------------
def pick_folder(parent, start: Path) -> Path | None:
    d = QFileDialog.getExistingDirectory(parent, "", str(start))
    return Path(d) if d else None


def ask_move(parent, i18n, size: int) -> str:
    """"move", "dont" or "cancel"."""
    tr = i18n.tr
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setText(tr("downloads.move_q", size=fmt_bytes(size, i18n.language)))
    move = box.addButton(tr("downloads.move"), QMessageBox.AcceptRole)
    dont = box.addButton(tr("downloads.dont_move"), QMessageBox.DestructiveRole)
    box.setEscapeButton(box.addButton(tr("downloads.cancel"), QMessageBox.RejectRole))
    box.exec()
    clicked = box.clickedButton()
    return "move" if clicked is move else "dont" if clicked is dont else "cancel"


def ask_delete_old(parent, i18n, path: Path, size: int) -> str:
    """"delete" or "keep" (the default, and what closing the box means)."""
    tr = i18n.tr
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setText(tr("downloads.old_left", path=str(path), size=fmt_bytes(size, i18n.language)))
    delete = box.addButton(tr("downloads.delete_old"), QMessageBox.DestructiveRole)
    keep = box.addButton(tr("downloads.keep_old"), QMessageBox.RejectRole)
    box.setDefaultButton(keep)
    box.setEscapeButton(keep)
    box.exec()
    return "delete" if box.clickedButton() is delete else "keep"


def ask_missing(parent, i18n, path: Path) -> str:
    """"retry", "choose" or "close"."""
    tr = i18n.tr
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setText(tr("downloads.missing", path=str(path)))
    retry = box.addButton(tr("downloads.retry"), QMessageBox.AcceptRole)
    choose = box.addButton(tr("downloads.choose"), QMessageBox.ActionRole)
    box.setEscapeButton(box.addButton(tr("downloads.close"), QMessageBox.RejectRole))
    box.exec()
    clicked = box.clickedButton()
    return "retry" if clicked is retry else "choose" if clicked is choose else "close"


def show_message(parent, text: str) -> None:
    QMessageBox.information(parent, "", text)


def run_dialog(dialog: QDialog) -> None:
    dialog.exec()


# --- the move, off the GUI thread ---------------------------------------------------------
class _MoveThread(QThread):
    progress = Signal(object)       # MoveProgress
    done = Signal()
    error = Signal(object)          # MoveError, MoveCancelled

    def __init__(self, settings, target: Path, cancel: threading.Event):
        super().__init__()
        self.settings, self.target, self.cancel = settings, target, cancel

    def run(self):
        try:
            downloads.move_downloads(self.settings, self.target, self.progress.emit, self.cancel)
            self.done.emit()
        except (downloads.MoveError, downloads.MoveCancelled) as e:
            self.error.emit(e)
        except Exception:
            import traceback
            try:
                (paths.logs_dir() / "move.log").write_text(traceback.format_exc(), "utf-8")
            except OSError:
                pass
            self.error.emit(downloads.MoveError("copy"))


class DownloadsDialog(QDialog):
    repair_needed = Signal()    # the folder changed without the files: setup should fetch them again

    def __init__(self, i18n, settings, parent=None, before_move=None):
        super().__init__(parent)
        # The one Settings object the whole window shares: a move updates it in place.
        self.i18n, self.settings, self.before_move = i18n, settings, before_move
        self._thread: _MoveThread | None = None
        self._cancel = threading.Event()
        self.setWindowTitle(i18n.tr("downloads.title"))
        self.setMinimumWidth(480)

        lay = QVBoxLayout(self)
        self.folder_label, self.size_label, self.status_label = QLabel(), QLabel(), QLabel()
        for l in (self.folder_label, self.size_label, self.status_label):
            l.setWordWrap(True)
            lay.addWidget(l)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.hide()
        lay.addWidget(self.bar)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.change_button = secondary_button()
        self.change_button.setText(i18n.tr("setup.location.change"))
        self.change_button.clicked.connect(self._change)
        self.cancel_button = secondary_button()
        self.cancel_button.setText(i18n.tr("downloads.cancel"))
        self.cancel_button.clicked.connect(lambda: self._cancel.set())
        self.cancel_button.hide()
        self.close_button = primary_button()
        self.close_button.setText(i18n.tr("downloads.close"))
        self.close_button.clicked.connect(self.accept)
        for b in (self.change_button, self.cancel_button, self.close_button):
            buttons.addWidget(b)
        lay.addLayout(buttons)
        self._show_current()

    def is_moving(self) -> bool:
        # Until the thread's finished signal arrives, after its done or error one.
        return self._thread is not None

    def _show_current(self) -> None:
        tr, lang = self.i18n.tr, self.i18n.language
        current = paths.downloads_dir_path()
        self.folder_label.setText(tr("downloads.current", path=str(current)))
        self.size_label.setText(tr("downloads.size", size=fmt_bytes(downloads.downloads_size(current), lang)))

    def _status(self, text: str, error: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(ERROR_STYLE if error else "")

    def _change(self) -> None:
        tr = self.i18n.tr
        current = paths.downloads_dir_path()
        picked = pick_folder(self, current)
        if picked is None:
            return
        target = downloads.choose_target(picked)
        try:
            # Checked before writable(), which creates the folder.
            if target.resolve() == current.resolve():
                self._status(tr("downloads.same"))
                return
            if downloads._nested(current.resolve(), target.resolve()):
                self._status(tr("downloads.failed_nested"), error=True)
                return
        except OSError:
            pass
        created = not target.exists()
        if not downloads.writable(target):
            self._status(tr("downloads.failed_target"), error=True)
            return
        answer = ask_move(self, self.i18n, downloads.downloads_size(current))
        if answer == "cancel" and created:
            try:
                target.rmdir()      # only the folder made just now, and only while it is empty
            except OSError:
                pass
        if answer == "dont":
            try:
                downloads.set_downloads_dir(self.settings, target)
            except OSError:
                self._status(tr("downloads.failed_target"), error=True)
                return
            # Switched: the old copy is now only taking up room. Say where it is, and offer to delete it.
            left = downloads.downloads_size(current)
            if left and ask_delete_old(self, self.i18n, current, left) == "delete":
                if self.before_move is not None:
                    self.before_move()      # a running AI helper keeps its file open (Windows can't delete it)
                downloads.delete_downloads(current)
            self.repair_needed.emit()
            self.accept()
        elif answer == "move":
            self._start_move(target)

    def _start_move(self, target: Path) -> None:
        if self.before_move is not None:
            self.before_move()      # a running AI helper keeps its files open (Windows can't move them)
        self._cancel = threading.Event()
        t = _MoveThread(self.settings, target, self._cancel)
        t.progress.connect(self._on_progress)
        t.done.connect(self._on_done)
        t.error.connect(self._on_error)
        t.finished.connect(self._on_thread_finished)
        self._thread = t
        self._set_moving(True)
        self._status(self.i18n.tr("downloads.moving"))
        t.start()

    def _set_moving(self, moving: bool) -> None:
        self.bar.setValue(0)
        self.bar.setVisible(moving)
        self.cancel_button.setVisible(moving)
        self.change_button.setEnabled(not moving)
        self.close_button.setEnabled(not moving)

    def _on_progress(self, p) -> None:
        self.bar.setValue(int(100 * p.done / p.total) if p.total else 0)

    def _on_done(self) -> None:
        self._show_current()
        self._status(self.i18n.tr("downloads.done"))

    def _on_error(self, e) -> None:
        tr, lang = self.i18n.tr, self.i18n.language
        if isinstance(e, downloads.MoveCancelled):
            self._status(tr("downloads.cancelled"))
        elif e.kind == "space":
            self._status(tr("downloads.failed_space", needed=fmt_bytes(e.needed, lang),
                            free=fmt_bytes(e.free, lang)), error=True)
        else:
            self._status(tr(f"downloads.failed_{e.kind}"), error=True)

    def _on_thread_finished(self) -> None:
        self._thread.wait()     # never drop a QThread that hasn't fully stopped
        self._thread = None
        self._set_moving(False)

    def reject(self) -> None:
        # Escape or the window's close button while moving: stop the move (it checks every
        # megabyte, and undoes what it copied) rather than leave it running without a window.
        if self._thread is not None:
            self._cancel.set()
            self._thread.wait()
        super().reject()
