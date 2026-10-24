"""Fixing a transcript with an AI: numbered-line protocol, export parts, reading answers back, guardrails.

The AI may only fix misheard words and names. Lines go out numbered and must come back with
the same numbers; any line it changed more than a misheard-word fix plausibly would keeps
the original.
"""
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

TS_RE = re.compile(r"^\[(\d+:\d{2}:\d{2})\]\s?")
# A line number, optionally wrapped in markdown (**[2]**, - [3], > [4], * 5.): "[n]" or "n." / "n)".
_ANSWER_RE = re.compile(r"^[\s>*_\-•]*(?:\[\s*([0-9۰-۹٠-٩]+)\s*\]|([0-9۰-۹٠-٩]+)\s*[.)])[*_]*\s?(.*?)\s*$")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
# Invisible direction marks chat apps add around RTL text. ZWNJ (U+200C) is part of Persian words and stays.
_BIDI = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u061c\ufeff"))

MAX_PART_CHARS = 6000
MAX_CHANGE_RATIO = 0.5
MERGE_SIMILARITY = 0.7    # fewer words back: how alike the joined-up removed words must be

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
    """Numbered lines from an AI's answer. A "[n]" line beats an "n." line for the same number
    (chat AIs often add their own numbered notes); otherwise the first occurrence wins."""
    bracketed: dict[int, str] = {}
    plain: dict[int, str] = {}
    for line in text.translate(_BIDI).splitlines():
        m = _ANSWER_RE.match(line)
        if m:
            target = bracketed if m.group(1) else plain
            n = int((m.group(1) or m.group(2)).translate(_DIGITS))
            target.setdefault(n, m.group(3))
    return {n: bracketed.get(n, plain.get(n)) for n in sorted(bracketed.keys() | plain.keys())}


def _drops_word(a: str, b: str) -> bool:
    """A word removed without a matching word added right before or after it.

    Allowed: a replacement (as many words come back as went, or more), and a merge, where fewer
    words come back but they are the removed ones joined («علی رزا» → «علیرضا», «می گه» → «میگه»):
    the removed words without spaces must be at least MERGE_SIMILARITY alike the added text.
    Anything else hides a lost word behind a changed neighbour («چی بگیر» → «چیز»).
    """
    diff = word_diff(a, b)
    return any(kind == "removed" and not any(_replaces(text, t) for k, t in diff[max(i - 1, 0): i + 2]
                                             if k == "added")
               for i, (kind, text) in enumerate(diff))


def _replaces(removed: str, added: str) -> bool:
    if len(removed.split()) <= len(added.split()):
        return True
    return SequenceMatcher(None, _joined(removed), _joined(added)).ratio() >= MERGE_SIMILARITY


def _joined(text: str) -> str:
    """The letters alone: no spaces, no ZWNJ (a merge may come back with either)."""
    return "".join(text.split()).replace("\u200c", "")


def _too_different(a: str, b: str, max_change: float) -> bool:
    wa, wb = len(a.split()), len(b.split())
    return (1 - SequenceMatcher(None, a, b).ratio() > max_change
            or abs(wa - wb) > max(2, wa // 4)
            or _drops_word(a, b))


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
