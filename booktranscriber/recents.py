"""Index of recent transcripts shown on the home screen."""
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .settings import write_json_atomic


@dataclass
class RecentItem:
    audio: str
    raw_path: str
    corrected_path: str | None
    created: str


def _read(path: Path) -> list[RecentItem]:
    try:
        data = json.loads(Path(path).read_text("utf-8"))
        return [RecentItem(**d) for d in data]
    except (OSError, ValueError, TypeError):
        return []


def load_recents(path: Path) -> list[RecentItem]:
    return [i for i in _read(path) if os.path.isfile(i.raw_path)]


def add_recent(path: Path, item: RecentItem, limit: int = 20) -> list[RecentItem]:
    items = [item] + [i for i in _read(path) if i.raw_path != item.raw_path]
    items = items[:limit]
    write_json_atomic(path, [asdict(i) for i in items])
    return items
