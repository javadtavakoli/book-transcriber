import importlib
import os

import pytest

import booktranscriber.engine
import booktranscriber.gpu
from booktranscriber.engine import (CORRECTED_SUFFIX, DECODE_PARAMS, Segment, corrected_path_for,
                                    format_line, format_timestamp, output_path)


def test_output_path_default_next_to_audio(tmp_path):
    audio = tmp_path / "جلسه ۱۲" / "ضبط شده.m4a"
    assert output_path(str(audio)) == str(tmp_path / "جلسه ۱۲" / "ضبط شده - متن خام.txt")


def test_output_path_corrected_suffix(tmp_path):
    assert output_path(str(tmp_path / "a.wav"), suffix=CORRECTED_SUFFIX).endswith("a - متن اصلاح‌شده.txt")


def test_corrected_path_follows_raw_location():
    raw = os.path.join("/docs", "جلسه - متن خام.txt")
    assert corrected_path_for(raw) == os.path.join("/docs", "جلسه - متن اصلاح‌شده.txt")
    assert corrected_path_for(os.path.join("/docs", "notes.txt")) == os.path.join("/docs", "notes - متن اصلاح‌شده.txt")


def test_output_path_explicit_wins():
    assert output_path("/x/a.wav", "/y/out.txt") == "/y/out.txt"


def test_format_timestamp():
    assert format_timestamp(0) == "[0:00:00]"
    assert format_timestamp(65.9) == "[0:01:05]"
    assert format_timestamp(3725) == "[1:02:05]"


def test_format_line():
    s = Segment(65.0, 70.0, "  سلام  ")
    assert format_line(s, False) == "سلام"
    assert format_line(s, True) == "[0:01:05] سلام"


def test_decode_params_unchanged():
    assert DECODE_PARAMS == dict(
        beam_size=5, condition_on_previous_text=False,
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0], compression_ratio_threshold=2.4,
        no_speech_threshold=0.6, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500))


def test_import_has_no_side_effects(monkeypatch):
    monkeypatch.setattr(os, "execv", lambda *a: pytest.fail("execv at import"))
    monkeypatch.setattr(os, "add_dll_directory", lambda *a: pytest.fail("dll dir at import"), raising=False)
    env_before = dict(os.environ)
    importlib.reload(booktranscriber.engine)
    importlib.reload(booktranscriber.gpu)
    assert dict(os.environ) == env_before
