"""Fixing a transcript with the local AI helper: chunked requests to the running llama-server.

Lines go out numbered in small chunks (a small model loses track in long ones); answers are
read back and checked by the shared guardrails in fixexport.
"""
import re
import threading
from typing import Callable

import httpx

from .downloader import DownloadCancelled
from .fixexport import LineFix, apply_answer, parse_answer, split_timestamp
from .llm_server import local_client

LINES_PER_REQUEST = 15
REQUEST_TIMEOUT = 600   # a 6 GB GPU with partial offload took ~25 s per 15 lines

# English instructions (small models follow them best); the worked example is deliberately
# not from any real recording.
LOCAL_PROMPT = """You fix speech-recognition errors in Persian transcripts of a book-club conversation.
The recognizer often writes a word that SOUNDS like the right one but is spelled wrong or is a different word.
These lines DO contain such errors. Find them and replace each misheard word with the word the speaker actually said.

Rules:
- Change only misheard words and misspelled names. Keep everything else exactly.
- Keep colloquial Persian as spoken (میگه، اینجوری، نمیدونم). Do not make it formal.
- Never rephrase, summarize, add or remove sentences, or merge/split lines.
- If a line is fine, return it unchanged.
- Reply with the same numbered lines, [n] text, and nothing else.
{names}
Example input:
[1] دیروز رفتیم کطابخونه و یه رمان از داستایوسکی گرفطیم
[2] نویسندش خیلی معرفه
[3] آره خب
Example output:
[1] دیروز رفتیم کتابخونه و یه رمان از داستایفسکی گرفتیم
[2] نویسندش خیلی معروفه
[3] آره خب"""

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def build_prompt(names: list[str]) -> str:
    names_line = f"- Correct spellings of names: {'، '.join(names)}\n" if names else ""
    return LOCAL_PROMPT.replace("{names}", names_line)


def chunk_lines(lines: list[str], per: int = LINES_PER_REQUEST) -> list[list[int]]:
    """1-based numbers of the non-empty lines, `per` at a time."""
    numbers = [n for n, line in enumerate(lines, 1) if split_timestamp(line)[1].strip()]
    return [numbers[i:i + per] for i in range(0, len(numbers), per)]


def _ask(client: httpx.Client, port: int, system: str, user: str) -> str:
    r = client.post(f"http://127.0.0.1:{port}/v1/chat/completions", json={
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": 4096,
        "chat_template_kwargs": {"enable_thinking": False},
    })
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


def _request(client: httpx.Client, port: int, system: str, rows: dict[int, str]) -> dict[int, str]:
    """The answers for the given numbered rows; {} when the request or its reply is unusable."""
    user = "\n".join(f"[{n}] {text}" for n, text in rows.items())
    try:
        answer = parse_answer(_THINK_RE.sub("", _ask(client, port, system, user)))
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return {}
    return {n: t for n, t in answer.items() if n in rows}


def fix_transcript(lines: list[str], names: list[str], port: int,
                   on_progress: Callable[[int, int], None], cancel: threading.Event,
                   client: httpx.Client | None = None) -> list[LineFix]:
    system = build_prompt(names)
    chunks = chunk_lines(lines)
    own = client is None
    client = client or local_client(REQUEST_TIMEOUT)
    answer: dict[int, str] = {}
    try:
        on_progress(0, len(chunks))
        for done, chunk in enumerate(chunks, 1):
            if cancel.is_set():
                raise DownloadCancelled()
            rows = {n: split_timestamp(lines[n - 1])[1].strip() for n in chunk}
            got = _request(client, port, system, rows)
            missing = {n: t for n, t in rows.items() if n not in got}
            if missing and not cancel.is_set():
                got.update(_request(client, port, system, missing))   # one retry, only what is missing
            answer.update(got)
            on_progress(done, len(chunks))
            if cancel.is_set() and done < len(chunks):
                raise DownloadCancelled()
    finally:
        if own:
            client.close()
    return apply_answer(lines, answer)
