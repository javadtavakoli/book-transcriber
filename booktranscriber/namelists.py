"""Saved lists of proper nouns per book, used to seed Whisper (and the AI fix)."""
import re
from pathlib import Path

from .engine import DEFAULT_PROMPT_FA

_BAD_CHARS = re.compile(r'[/\\:*?"<>|]')


def _dedupe(items) -> list[str]:
    seen, out = set(), []
    for s in items:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def parse_names(text: str) -> list[str]:
    return _dedupe(text.splitlines())


def build_prompt(names: list[str], language: str) -> str | None:
    if language == "fa":
        return DEFAULT_PROMPT_FA + (" " + "، ".join(names) + "." if names else "")
    return ", ".join(names) + "." if names else None


def list_lists(d: Path) -> list[str]:
    return sorted(p.stem for p in Path(d).glob("*.txt"))


def load_list(d: Path, name: str) -> list[str]:
    return parse_names((Path(d) / f"{name}.txt").read_text("utf-8-sig"))


def save_list(d: Path, name: str, names: list[str]) -> None:
    safe = _BAD_CHARS.sub("_", name.strip()) or "names"
    (Path(d) / f"{safe}.txt").write_text("\n".join(names) + "\n", "utf-8")


def import_prompt_file(path: Path) -> list[str]:
    """Turn an old prose prompt file (prompts/*.txt) into a list of names."""
    text = Path(path).read_text("utf-8-sig")
    default = DEFAULT_PROMPT_FA.rstrip(".")
    pieces = []
    for piece in re.split(r"[\n،,.]", text):
        piece = piece.split(":", 1)[1] if ":" in piece else piece
        if piece.strip() != default:
            pieces.append(piece)
    return _dedupe(pieces)
