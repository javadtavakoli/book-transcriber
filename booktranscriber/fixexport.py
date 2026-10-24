"""Fixing a transcript with an AI: numbered-line protocol, export parts, reading answers back, guardrails.

The AI may only fix misheard words and names. Lines go out numbered and must come back with
the same numbers; any line it changed more than a misheard-word fix plausibly would keeps
the original.
"""
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

TS_RE = re.compile(r"^\[(\d+:\d{2}:\d{2})\]\s?")
_ANSWER_RE = re.compile(r"^\s*(?:\[\s*(\d+)\s*\]|(\d+)\s*[.)])\s?(.*?)\s*$")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

MAX_PART_CHARS = 6000
MAX_CHANGE_RATIO = 0.5

# English instructions: chat AIs follow them most reliably; the transcript itself stays in its language.
INSTRUCTIONS = """You are correcting an automatic speech-to-text transcript of a recorded conversation.

Rules:
- Fix ONLY words the speech recognizer misheard, and the spelling of proper names.
- Never change the meaning. Do not rephrase, summarize, shorten, explain, or improve the style.
- Keep word order, sentence boundaries, filler words and colloquial speech exactly as they are.
- Never add, remove, merge, or split lines.
- Keep the text in its original language.
{names}
Reply with exactly the same numbered lines, in the form [n] text, and nothing else."""


@dataclass
class ExportPart:
    index: int
    total: int
    first_line: int
    last_line: int
    text: str


@dataclass
class LineFix:
    n: int
    original: str
    proposed: str | None
    accepted: bool
    reason: str     # "same" | "fixed" | "missing" | "too_different"


def split_timestamp(line: str) -> tuple[str, str]:
    m = TS_RE.match(line)
    return (line[: m.end()], line[m.end():]) if m else ("", line)


def _instructions(names: list[str]) -> str:
    names_line = f"- Correct spellings of names: {'، '.join(names)}\n" if names else ""
    return INSTRUCTIONS.format(names=names_line)


def build_export_parts(lines: list[str], names: list[str], max_chars: int = MAX_PART_CHARS) -> list[ExportPart]:
    numbered = [(n, f"[{n}] {text}") for n, line in enumerate(lines, 1)
                if (text := split_timestamp(line)[1].strip())]
    groups, cur, size = [], [], 0
    for n, row in numbered:
        if cur and size + len(row) + 1 > max_chars:
            groups.append(cur)
            cur, size = [], 0
        cur.append((n, row))
        size += len(row) + 1
    if cur:
        groups.append(cur)
    head = _instructions(names)
    return [ExportPart(i, len(groups), g[0][0], g[-1][0],
                       f"{head}\n\nPart {i} of {len(groups)}\n\n" + "\n".join(r for _, r in g))
            for i, g in enumerate(groups, 1)]


def parse_answer(text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for line in text.translate(_DIGITS).splitlines():
        m = _ANSWER_RE.match(line)
        if m:
            out.setdefault(int(m.group(1) or m.group(2)), m.group(3))
    return out


def _too_different(a: str, b: str, max_change: float) -> bool:
    wa, wb = len(a.split()), len(b.split())
    return (1 - SequenceMatcher(None, a, b).ratio() > max_change
            or abs(wa - wb) > max(2, wa // 4))


def apply_answer(lines: list[str], answer: dict[int, str], max_change: float = MAX_CHANGE_RATIO) -> list[LineFix]:
    fixes = []
    for n, line in enumerate(lines, 1):
        text = split_timestamp(line)[1].strip()
        proposed = answer.get(n)
        if not text:
            fixes.append(LineFix(n, "", None, False, "same"))
        elif proposed is None:
            fixes.append(LineFix(n, text, None, False, "missing"))
        elif proposed.strip() == text:
            fixes.append(LineFix(n, text, proposed.strip(), False, "same"))
        elif _too_different(text, proposed.strip(), max_change):
            fixes.append(LineFix(n, text, proposed.strip(), False, "too_different"))
        else:
            fixes.append(LineFix(n, text, proposed.strip(), True, "fixed"))
    return fixes


def corrected_lines(lines: list[str], fixes: list[LineFix]) -> list[str]:
    out = []
    for line, fix in zip(lines, fixes):
        ts = split_timestamp(line)[0]
        out.append(ts + fix.proposed if fix.accepted and fix.proposed is not None else line)
    return out


def word_diff(a: str, b: str) -> list[tuple[str, str]]:
    wa, wb = a.split(), b.split()
    out = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, wa, wb).get_opcodes():
        if op == "equal":
            out.append(("same", " ".join(wa[i1:i2])))
            continue
        if i2 > i1:
            out.append(("removed", " ".join(wa[i1:i2])))
        if j2 > j1:
            out.append(("added", " ".join(wb[j1:j2])))
    return out
