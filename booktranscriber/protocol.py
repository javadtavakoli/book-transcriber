"""JSON-line events streamed from the worker process to the GUI."""
import json


def encode(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False)


def decode(line: str) -> dict | None:
    """Parse one worker stdout line; None for anything that isn't an event (library noise)."""
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    return ev if isinstance(ev, dict) and "type" in ev else None
