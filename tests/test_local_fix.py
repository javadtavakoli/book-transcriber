import threading
from pathlib import Path

import httpx
import pytest

from booktranscriber import local_fix
from booktranscriber.downloader import DownloadCancelled
from booktranscriber.llm_server import LlamaServer

TRANSCRIPT = Path(__file__).with_name("fixtures") / "transcript_fa.txt"


@pytest.fixture
def lines():
    return TRANSCRIPT.read_text(encoding="utf-8").splitlines()


@pytest.fixture
def server(fake_llama, tmp_path):
    started = []

    def start(mode):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"x")
        s = LlamaServer(fake_llama(mode), model, gpu=True)
        s.start(lambda f, e: None, threading.Event())
        started.append(s)
        return s
    yield start
    for s in started:
        s.stop()


def run(lines, port, cancel=None, progress=None):
    return local_fix.fix_transcript(lines, [], port, progress or (lambda d, t: None), cancel or threading.Event())


def test_fix_mode_fixes_and_keeps_rest(server, lines):
    fixes = run(lines, server("fix").port)
    assert len(fixes) == len(lines)
    fixed = [f for f in fixes if f.accepted]
    assert [f.proposed for f in fixed] == ["من این هفته یه کتاب درباره نقاشی خوندم"]
    assert all(f.reason in ("same", "fixed") for f in fixes)


def test_think_block_is_ignored(server, lines):
    fixes = run(lines, server("think").port)
    assert all(f.reason == "same" for f in fixes)


def test_http500_chunk_kept_original_and_others_fixed(server, lines):
    assert len(lines) > local_fix.LINES_PER_REQUEST
    fixes = run(lines, server("http500").port)
    assert all(f.reason == "missing" and not f.accepted for f in fixes)
    # one chunk failing (request and its retry) must not stop the others
    srv = server("ok")
    real = local_fix._ask
    calls = []

    def flaky(client, port, system, user):
        calls.append(1)
        if len(calls) <= 2:
            raise local_fix.httpx.HTTPError("boom")
        return real(client, port, system, user)
    local_fix._ask, saved = flaky, local_fix._ask
    try:
        fixes = run(lines, srv.port)
    finally:
        local_fix._ask = saved
    n = local_fix.LINES_PER_REQUEST
    assert all(f.reason == "missing" for f in fixes[:n])
    assert all(f.reason == "same" for f in fixes[n:])


def test_missing_lines_retried_once(server, lines):
    srv = server("dropfirst")
    fixes = run(lines[:5], srv.port)
    assert all(f.reason == "same" for f in fixes)


def test_missing_lines_stay_missing_after_one_retry(server, lines):
    seen = []

    def never(client, port, system, user):
        seen.append(user)
        return "[1] " + lines[0].split("] ", 1)[1]
    saved, local_fix._ask = local_fix._ask, never
    try:
        fixes = run(lines[:3], server("ok").port)
    finally:
        local_fix._ask = saved
    assert len(seen) == 2 and seen[1].startswith("[2]")
    assert [f.reason for f in fixes] == ["same", "missing", "missing"]


def test_cancel_stops_between_chunks(server, lines):
    cancel = threading.Event()
    done = []

    def progress(d, t):
        done.append((d, t))
        if d == 1:
            cancel.set()
    with pytest.raises(DownloadCancelled):
        run(lines, server("ok").port, cancel, progress)
    assert done == [(0, 2), (1, 2)]


def test_chunk_lines_skips_empty_and_splits():
    assert local_fix.chunk_lines(["a", "", "b", "[0:00:01] ", "c"], 2) == [[1, 3], [5]]


def test_names_line_only_when_given():
    assert "Correct spellings of names" not in local_fix.build_prompt([])
    assert "- Correct spellings of names: الف، ب\n" in local_fix.build_prompt(["الف", "ب"])


def test_prompt_example_does_not_overlap_test_transcript(lines):
    prompt = local_fix.LOCAL_PROMPT
    example = prompt.split("Example input:")[1]
    words = []
    for row in example.splitlines():
        words.append(row.split("] ", 1)[1].split() if "] " in row else [])
    grams = {tuple(w[i:i + 3]) for w in words for i in range(len(w) - 2)}
    assert grams
    transcript = [w for l in lines for w in l.split("] ", 1)[-1].split()]
    seen = {tuple(transcript[i:i + 3]) for i in range(len(transcript) - 2)}
    assert not grams & seen


def _json_reply(body):
    return lambda request: httpx.Response(200, json=body)


@pytest.mark.parametrize("handler", [
    _json_reply({"choices": [{"message": {"content": "Sure! Here you go, nothing else to say."}}]}),   # chatter
    _json_reply({"choices": [{"message": {"content": ""}}]}),                                          # empty
    _json_reply({"choices": [{"message": {"content": "[1] Hello there\n[2] Fine"}}]}),                 # non-Persian
    lambda request: httpx.Response(200, content=b"{not json"),                                        # malformed JSON
    _json_reply({"error": "no choices"}),                                                              # missing choices
    _json_reply(["unexpected", "list"]),                                                               # list body
    _json_reply({"choices": [{"message": {"content": ["not", "a", "string"]}}]}),                      # content not a string
    _json_reply({"choices": [{"message": {"content": 42}}]}),                                          # content a number
], ids=["chatter", "empty", "non_persian", "bad_json", "no_choices", "list_body", "list_content", "int_content"])
def test_bad_answers_keep_originals_and_finish(lines, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    fixes = local_fix.fix_transcript(lines, [], 1, lambda d, t: None, threading.Event(), client)
    assert len(fixes) == len(lines)
    assert not any(f.accepted for f in fixes)
