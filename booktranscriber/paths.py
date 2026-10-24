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
    _repoint_settings(old, new)
    return True


def _repoint_settings(old: Path, new: Path) -> None:
    """Stored model paths that lay under the old folder now point into the new one."""
    import json
    from .settings import write_json_atomic
    f = new / "settings.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        changed = False
        for key in ("whisper_model_path", "llm_model_path"):
            v = data.get(key)
            if isinstance(v, str):
                try:
                    rel = Path(v).relative_to(old)
                except ValueError:
                    continue
                data[key] = str(new / rel)
                changed = True
        if changed:
            write_json_atomic(f, data)
    except (OSError, ValueError, AttributeError):
        pass


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


def downloads_dir_path() -> Path:
    """Where the big downloads live (models, GPU libraries, the AI helper), without creating anything.

    settings.json's downloads_dir when set, else the app folder. Read straight from the JSON so this
    module never imports settings; a missing or broken file means the default.
    """
    import json
    try:
        data = json.loads((data_dir_path() / "settings.json").read_text("utf-8"))
        v = data.get("downloads_dir") if isinstance(data, dict) else None
    except (OSError, ValueError):
        v = None
    return Path(v) if isinstance(v, str) and v else data_dir_path()


def downloads_dir() -> Path:
    d = downloads_dir_path()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sub(name: str, root=data_dir) -> Path:
    d = root() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    return _sub("models", downloads_dir)


def gpu_dir() -> Path:
    return _sub("gpu", downloads_dir)


def llm_dir() -> Path:
    return _sub("llm", downloads_dir)


def namelists_dir() -> Path:
    return _sub("namelists")


def logs_dir() -> Path:
    return _sub("logs")


def settings_file() -> Path:
    return data_dir() / "settings.json"


def recents_file() -> Path:
    return data_dir() / "recents.json"
