"""App settings persisted as JSON; anything missing or unreadable falls back to defaults."""
import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Settings:
    ui_language: str | None = None
    setup_done: bool = False
    whisper_model: str = "large-v3"
    whisper_model_path: str | None = None
    device: str = "auto"
    language: str = "fa"
    timestamps: bool = False


def load_settings(path: Path) -> Settings:
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in data.items() if k in known})


def write_json_atomic(path: Path, data) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)


def save_settings(s: Settings, path: Path) -> None:
    write_json_atomic(path, asdict(s))
