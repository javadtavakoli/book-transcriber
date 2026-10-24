"""Per-user data directory layout. Override the root with BT_DATA_DIR (used by tests)."""
import os
from pathlib import Path

APP_NAME = "BookTranscriber"


def data_dir() -> Path:
    env = os.environ.get("BT_DATA_DIR")
    if env:
        d = Path(env)
    else:
        import platformdirs
        d = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))
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
