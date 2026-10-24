"""Per-user data directory layout. Override the root with BT_DATA_DIR (used by tests)."""
import os
import sys
from pathlib import Path

APP_NAME = "WritingParrot"
OLD_APP_NAME = "BookTranscriber"      # the data folder's name before the rename


def _platform_data_dir(app_name: str) -> Path:
    import platformdirs
    return Path(platformdirs.user_data_dir(app_name, appauthor=False))


def migrate_old_data_dir() -> bool:
    """Rename the pre-rename data folder to the new name. True if it was renamed."""
    if os.environ.get("BT_DATA_DIR"):
        return False
    old, new = _platform_data_dir(OLD_APP_NAME), _platform_data_dir(APP_NAME)
    if not old.is_dir() or new.exists():
        return False
    try:
        os.rename(old, new)
    except OSError:
        return False
    return True


def asset(name: str) -> Path:
    """A bundled asset, from the source tree or a PyInstaller build."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "booktranscriber" / "assets" / name
    return Path(__file__).resolve().parent / "assets" / name


def data_dir_path() -> Path:
    """Where app data lives, without creating anything."""
    env = os.environ.get("BT_DATA_DIR")
    if env:
        return Path(env)
    return _platform_data_dir(APP_NAME)


def data_dir() -> Path:
    d = data_dir_path()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sub(name: str) -> Path:
    d = data_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    return _sub("models")


def gpu_dir() -> Path:
    return _sub("gpu")


def namelists_dir() -> Path:
    return _sub("namelists")


def logs_dir() -> Path:
    return _sub("logs")


def settings_file() -> Path:
    return data_dir() / "settings.json"


def recents_file() -> Path:
    return data_dir() / "recents.json"
