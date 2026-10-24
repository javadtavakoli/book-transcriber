"""Home: one big "drop your recording here" area and the recent transcripts."""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from .. import paths
from ..recents import RecentItem, load_recents
from .widgets import primary_button

AUDIO_EXTS = {".wav", ".m4a", ".mp3", ".ogg", ".opus", ".flac", ".aac", ".wma", ".mp4", ".webm", ".mkv",
              ".amr", ".3gp"}
MAX_RECENTS_SHOWN = 5


def validate_drop(paths_: list[str]) -> tuple[str | None, str | None]:
    """(audio path, None) or (None, error string key)."""
    if len(paths_) > 1:
        return None, "home.err.many"
    if not paths_ or not os.path.exists(paths_[0]):
        return None, "home.err.missing"
    p = paths_[0]
    if os.path.isdir(p):
        return None, "home.err.folder"
    if os.path.splitext(p)[1].lower() not in AUDIO_EXTS:
        return None, "home.err.not_audio"
    return p, None


class DropArea(QFrame):
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("drop")
        self._style(False)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        icon = QLabel("🎙️")
        icon.setStyleSheet("font-size: 40px; border: none;")
        icon.setAlignment(Qt.AlignCenter)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 18px; font-weight: 600; border: none;")
        self.title.setAlignment(Qt.AlignCenter)
        self.or_label = QLabel()
        self.or_label.setStyleSheet("color: #888; border: none;")
        self.or_label.setAlignment(Qt.AlignCenter)
        self.choose_button = primary_button()
        self.choose_button.clicked.connect(self._choose)
        for w in (icon, self.title, self.or_label):
            lay.addWidget(w)
        lay.addWidget(self.choose_button, 0, Qt.AlignCenter)

    def _style(self, hover: bool) -> None:
        color = "#2f6fde" if hover else "#9ab"
        self.setStyleSheet(f"QFrame#drop {{ border: 3px dashed {color}; border-radius: 14px; }}")

    def _choose(self) -> None:
        pattern = " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))
        path, _ = QFileDialog.getOpenFileName(self, self.choose_button.text(), os.path.expanduser("~"),
                                              f"Audio ({pattern})")
        if path:
            self.files_dropped.emit([path])

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._style(True)

    def dragLeaveEvent(self, e) -> None:
        self._style(False)

    def dropEvent(self, e) -> None:
        self._style(False)
        self.files_dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])


class HomeView(QWidget):
    audio_selected = Signal(str)
    recent_opened = Signal(object)

    def __init__(self, i18n, settings, parent=None):
        super().__init__(parent)
        self.i18n, self.settings = i18n, settings
        lay = QVBoxLayout(self)
        self.drop = DropArea()
        self.drop.setMinimumHeight(260)
        self.drop.files_dropped.connect(self.handle_files)
        lay.addWidget(self.drop, 3)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #c0392b;")
        self.error_label.hide()
        lay.addWidget(self.error_label)
        self.recent_title = QLabel()
        self.recent_title.setStyleSheet("color: #6b7280; margin-top: 10px;")
        lay.addWidget(self.recent_title)
        self.recent_list = QListWidget()
        self.recent_list.setMaximumHeight(150)
        self.recent_list.itemActivated.connect(lambda it: self.recent_opened.emit(it.data(Qt.UserRole)))
        self.recent_list.itemClicked.connect(lambda it: self.recent_opened.emit(it.data(Qt.UserRole)))
        lay.addWidget(self.recent_list, 1)
        self._error_key = None
        self.retranslate()
        self.refresh_recents()

    def handle_files(self, files: list) -> None:
        audio, err = validate_drop(files)
        self._error_key = err
        self.error_label.setVisible(err is not None)
        if err:
            self.error_label.setText(self.i18n.tr(err))
            return
        self.audio_selected.emit(audio)

    def refresh_recents(self) -> None:
        self.recent_list.clear()
        items: list[RecentItem] = load_recents(paths.recents_file())[:MAX_RECENTS_SHOWN]
        for it in items:
            name = os.path.splitext(os.path.basename(it.audio))[0]
            row = QListWidgetItem(f"{name}  {'✔' if it.corrected_path else ''}".strip())
            row.setData(Qt.UserRole, it)
            row.setToolTip(it.raw_path)
            self.recent_list.addItem(row)
        self.recent_title.setVisible(bool(items))
        self.recent_list.setVisible(bool(items))

    def retranslate(self) -> None:
        tr = self.i18n.tr
        self.drop.title.setText(tr("home.drop_title"))
        self.drop.or_label.setText(tr("home.or"))
        self.drop.choose_button.setText(tr("home.choose"))
        self.recent_title.setText(tr("home.recent"))
        if self._error_key:
            self.error_label.setText(tr(self._error_key))
