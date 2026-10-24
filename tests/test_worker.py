import os
import sys
from types import SimpleNamespace

import pytest

from booktranscriber.worker import run, worker_command


def _segs(*items):
    return [SimpleNamespace(start=s, end=e, text=t) for s, e, t in items]


class FakeModel:
    def __init__(self, segments, explode_with=None):
        self.segments, self.explode_with, self.calls = segments, explode_with, []

    def transcribe(self, audio, **kw):
        self.calls.append(kw)

        def gen():
            yield from self.segments
            if self.explode_with:
                raise self.explode_with
        return gen(), SimpleNamespace(duration=4.0)


def make_loader(model):
    return lambda name, device, download_root, log: (model, "cpu/int8")


@pytest.fixture
def fake_loader():
    return make_loader(FakeModel(_segs((0.0, 2.0, " سلام "), (2.0, 4.0, "دنیا"))))


@pytest.fixture
def exploding_loader():
    return make_loader(FakeModel(_segs((0.0, 2.0, "سلام")), explode_with=ValueError("boom")))


@pytest.fixture
def cuda_failing_loader():
    err = RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")
    return make_loader(FakeModel(_segs((0.0, 2.0, "سلام")), explode_with=err))


def no_load(*a, **k):
    pytest.fail("model must not load")


def test_missing_file_emits_not_found(tmp_path):
    events = []
    rc = run(["--audio", str(tmp_path / "nope.m4a"), "--out", str(tmp_path / "o.txt"), "--model", "x"],
             events.append, loader=no_load)
    assert rc == 1 and events[-1]["type"] == "error" and events[-1]["kind"] == "not_found"


def test_non_audio_file_emits_bad_audio_before_model_load(tmp_path):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4 not audio")
    events = []
    rc = run(["--audio", str(pdf), "--out", str(tmp_path / "o.txt"), "--model", "x"], events.append, loader=no_load)
    assert rc == 1 and events[-1]["kind"] == "bad_audio"


def test_success_writes_atomically(tmp_path, wav_file, fake_loader):
    out = tmp_path / "ضبط - متن خام.txt"
    events = []
    rc = run(["--audio", str(wav_file), "--out", str(out), "--model", "x", "--timestamps"],
             events.append, loader=fake_loader)
    assert rc == 0
    assert out.read_text("utf-8") == "[0:00:00] سلام\n[0:00:02] دنیا\n"
    assert not (tmp_path / (out.name + ".part")).exists()
    types = [e["type"] for e in events]
    assert types[0] == "loaded" and "duration" in types and types.count("segment") == 2
    assert events[-1] == {"type": "done", "out": str(out), "segments": 2}


def test_prompt_and_language_passed(tmp_path, wav_file):
    model = FakeModel(_segs((0.0, 1.0, "hi")))
    run(["--audio", str(wav_file), "--out", str(tmp_path / "o.txt"), "--model", "x",
         "--language", "en", "--prompt", "Homer."], lambda e: None, loader=make_loader(model))
    assert model.calls[0]["language"] == "en" and model.calls[0]["initial_prompt"] == "Homer."


def test_failure_removes_part(tmp_path, wav_file, exploding_loader):
    out = tmp_path / "o.txt"
    events = []
    rc = run(["--audio", str(wav_file), "--out", str(out), "--model", "x"], events.append, loader=exploding_loader)
    assert rc == 1 and not out.exists() and not (tmp_path / "o.txt.part").exists()
    assert events[-1]["kind"] == "unknown"


def test_cuda_error_mid_stream_is_model_kind(tmp_path, wav_file, cuda_failing_loader):
    out = tmp_path / "o.txt"
    events = []
    rc = run(["--audio", str(wav_file), "--out", str(out), "--model", "x"], events.append, loader=cuda_failing_loader)
    assert rc == 1 and events[-1]["kind"] == "model" and not (tmp_path / "o.txt.part").exists()


def test_model_load_failure_is_model_kind(tmp_path, wav_file):
    from booktranscriber.engine import ModelLoadError

    def failing(*a, **k):
        raise ModelLoadError("nope")
    events = []
    assert run(["--audio", str(wav_file), "--out", str(tmp_path / "o.txt"), "--model", "x"],
               events.append, loader=failing) == 1
    assert events[-1]["kind"] == "model"


def test_selftest_consumes_segments_without_vad():
    model = FakeModel(_segs((0.0, 1.0, "x")))
    events = []
    assert run(["--selftest", "--model", "x"], events.append, loader=make_loader(model)) == 0
    assert model.calls[0]["vad_filter"] is False
    assert events[0]["type"] == "loaded" and events[-1] == {"type": "done", "out": "", "segments": 1}


def test_worker_command_source_mode(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert worker_command(["--selftest"])[1:] == ["-m", "booktranscriber.worker", "--selftest"]


def test_worker_command_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert worker_command(["--selftest"])[1:] == ["--worker", "--selftest"]


def test_worker_env_finds_package_and_libs(monkeypatch):
    from pathlib import Path

    import booktranscriber
    from booktranscriber.worker import worker_env
    monkeypatch.delattr(sys, "frozen", raising=False)
    env = worker_env(["/libs/a"], {"PYTHONPATH": "/x"})
    root = str(Path(booktranscriber.__file__).resolve().parent.parent)
    assert env["PYTHONPATH"].split(os.pathsep) == [root, "/x"]
    key = "PATH" if sys.platform == "win32" else "LD_LIBRARY_PATH"
    assert env[key].startswith("/libs/a")


def test_no_speech_keeps_existing_transcript(tmp_path, wav_file):
    out = tmp_path / "o.txt"
    out.write_text("an earlier good transcript\n", "utf-8")
    events = []
    rc = run(["--audio", str(wav_file), "--out", str(out), "--model", "x"], events.append,
             loader=make_loader(FakeModel([])))
    assert rc == 0 and events[-1] == {"type": "done", "out": str(out), "segments": 0}
    assert out.read_text("utf-8") == "an earlier good transcript\n"
    assert not (tmp_path / "o.txt.part").exists()


def test_ensure_stdio_rebinds_none(monkeypatch):
    from booktranscriber.worker import ensure_stdio
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    ensure_stdio()
    assert sys.stdout is not None and sys.stderr is not None
    sys.stdout.write("")
    sys.stderr.write("x")
    sys.stderr.flush()
