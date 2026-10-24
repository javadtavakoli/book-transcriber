"""The downloads folder: choosing where it lives, and moving it there safely."""
import os
import shutil
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths
from .settings import Settings, save_settings

DOWNLOAD_SUBDIRS = ("models", "gpu", "llm")
FOLDER_NAME = "WritingParrot"
MARKER = ".writingparrot"
CHUNK = 1024 * 1024
SPACE_MARGIN = 1.05
DRIVE_REMOVABLE, DRIVE_FIXED = 2, 3


class MoveError(Exception):
    def __init__(self, kind: str, needed: int = 0, free: int = 0):
        super().__init__(kind)
        self.kind, self.needed, self.free = kind, needed, free


class MoveCancelled(Exception):
    pass


@dataclass
class MoveProgress:
    done: int
    total: int


def choose_target(picked: Path) -> Path:
    """The picked folder itself when it is empty or ours, else a WritingParrot folder inside it.

    Only the marker file, or being the app folder, makes a folder ours: a user's own models/ does not.
    """
    picked = Path(picked)
    try:
        if picked.resolve() == paths.data_dir_path().resolve():
            return picked       # back to the default
        entries = {p.name for p in picked.iterdir()}
    except FileNotFoundError:
        return picked
    if not entries or MARKER in entries:
        return picked
    return picked / FOLDER_NAME


def writable(folder: Path) -> bool:
    try:
        Path(folder).mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=folder, prefix=".write-test-")
        os.close(fd)
        os.remove(name)
        return True
    except OSError:
        return False


def _pid_file() -> Path:
    # llm_server keeps the running server's pid in the app folder's llm/, which is the default
    # downloads llm/ too: it belongs to the app folder and never moves.
    return (paths.data_dir_path() / "llm" / "server.pid").resolve()


def _files(root: Path) -> list[Path]:
    """Every file under the download subfolders of root, except the llama-server pid file."""
    out, pid = [], _pid_file()
    for sub in DOWNLOAD_SUBDIRS:
        for dirpath, _dirs, names in os.walk(Path(root) / sub):
            out += [Path(dirpath) / n for n in sorted(names)]
    return [p for p in out if p.is_file() and p.resolve() != pid]


def downloads_size(root: Path) -> int:
    return sum(p.stat().st_size for p in _files(root))


def _free(path: Path) -> int:
    """Free bytes on the drive holding path, which need not exist yet."""
    path = Path(path)
    while not path.exists() and path.parent != path:
        path = path.parent
    return shutil.disk_usage(path).free


def _windows_drives() -> list[tuple[Path, int, bool]]:
    import ctypes
    k32 = ctypes.windll.kernel32
    mask, drives = k32.GetLogicalDrives(), []
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(ord('A') + i)}:\\"
        kind = k32.GetDriveTypeW(root)
        if kind not in (DRIVE_FIXED, DRIVE_REMOVABLE):
            continue
        try:
            free = shutil.disk_usage(root).free
        except OSError:     # an empty card reader, a locked BitLocker drive
            continue
        drives.append((Path(root), free, kind == DRIVE_REMOVABLE))
    return drives


def suggest_default(needed_bytes: int, drives: list[tuple[Path, int, bool]] | None = None
                    ) -> tuple[Path, str | None]:
    """The app folder when its drive has room, else the first other fixed drive that does ("c_full")."""
    app = paths.data_dir_path()
    try:
        if _free(app) >= needed_bytes:
            return app, None
    except OSError:
        pass
    if drives is None:
        drives = _windows_drives() if sys.platform == "win32" else []
    system = Path(app.anchor)       # the app folder's drive is the one that is full
    for root, free, removable in drives:
        if not removable and Path(root) != system and free >= needed_bytes:
            return Path(root) / FOLDER_NAME, "c_full"
    return app, None


def mirror_to_registry(folder: Path) -> None:
    """Windows: record the folder under HKCU so the uninstaller can find the downloads."""
    if sys.platform != "win32":
        return
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\WritingParrot") as key:
            winreg.SetValueEx(key, "DownloadsDir", 0, winreg.REG_SZ, str(folder))
    except OSError:
        pass


def set_downloads_dir(settings: Settings, folder: Path) -> None:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / MARKER).touch()      # first, so a failure here leaves the saved settings alone
    settings.downloads_dir = str(folder)
    save_settings(settings, paths.settings_file())
    mirror_to_registry(folder)


def _write_chunk(f, data: bytes) -> None:
    f.write(data)


def _nested(old: Path, new: Path) -> bool:
    """Whether a download subfolder of one root lies inside one of the other's (a copy into itself)."""
    for a in DOWNLOAD_SUBDIRS:
        for b in DOWNLOAD_SUBDIRS:
            x, y = new / a, old / b
            if x.is_relative_to(y) or y.is_relative_to(x):
                return True
    return False


def _moved(value: str | None, old: Path, new: Path) -> str | None:
    """A stored model path re-rooted into the new folder, if it lay in one of the old download subfolders."""
    if not value:
        return value
    p = Path(value)
    for sub in DOWNLOAD_SUBDIRS:
        if p.is_relative_to(old / sub):
            return str(new / p.relative_to(old))
    return value


def move_downloads(settings: Settings, new_root: Path, progress: Callable[[MoveProgress], None],
                   cancel: threading.Event) -> None:
    """Copy the downloads to new_root, verify, switch the settings over, then delete the old copy.

    Until the switch nothing old is touched: on cancel or a copy error what was copied is removed
    and the settings stay as they were. Same-drive moves copy too, to keep one simple path.
    """
    old_root, new_root = paths.downloads_dir_path(), Path(new_root)
    try:
        old_r, new_r = old_root.resolve(), new_root.resolve()
        if old_r == new_r:
            return
        if _nested(old_r, new_r):
            raise MoveError("nested")
        files = _files(old_root)
        targets = [new_root / src.relative_to(old_root) for src in files]
        if any(os.path.lexists(t) for t in targets):
            raise MoveError("exists")       # never overwrite (or later delete) a file that was already there
        total = sum(p.stat().st_size for p in files)
        needed = int(total * SPACE_MARGIN)
        free = _free(new_root)
    except OSError as e:
        raise MoveError("target") from e
    if free < needed:
        raise MoveError("space", needed, free)

    made_dirs: list[Path] = []
    written: list[Path] = []

    def ensure_dir(d: Path) -> None:
        missing = []
        while not d.exists():
            missing.append(d)
            d = d.parent
        for m in reversed(missing):
            m.mkdir()
            made_dirs.append(m)

    def undo() -> None:
        for f in written:
            try:
                f.unlink()
            except OSError:
                pass
        for d in reversed(made_dirs):
            shutil.rmtree(d, ignore_errors=True)

    done = 0
    try:
        for src, dst in zip(files, targets):
            ensure_dir(dst.parent)
            with open(src, "rb") as fin, open(dst, "xb") as fout:     # x: fail rather than overwrite
                written.append(dst)
                while True:
                    if cancel.is_set():
                        raise MoveCancelled()
                    data = fin.read(CHUNK)
                    if not data:
                        break
                    _write_chunk(fout, data)
                    done += len(data)
                    progress(MoveProgress(done, total))
        for src, dst in zip(files, targets):
            if dst.stat().st_size != src.stat().st_size:
                raise MoveError("copy", needed, free)
        before = (settings.whisper_model_path, settings.llm_model_path, settings.downloads_dir)
        settings.whisper_model_path = _moved(settings.whisper_model_path, old_root, new_root)
        settings.llm_model_path = _moved(settings.llm_model_path, old_root, new_root)
        try:
            set_downloads_dir(settings, new_root)
        except BaseException:
            settings.whisper_model_path, settings.llm_model_path, settings.downloads_dir = before
            raise
    except (MoveCancelled, MoveError):
        undo()
        raise
    except OSError as e:
        undo()
        raise MoveError("copy", needed, free) from e
    except BaseException:       # a failing progress callback, Ctrl+C: still no partial copy left behind
        undo()
        raise

    # Delete exactly what was moved, then the folders it leaves empty; anything else stays.
    for src in files:
        try:
            src.unlink()
        except OSError:
            pass
    for sub in DOWNLOAD_SUBDIRS:
        for dirpath, _dirs, _names in os.walk(old_root / sub, topdown=False):
            try:
                os.rmdir(dirpath)
            except OSError:     # not empty
                pass
