import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # GUI tests run headless

import sys
import wave
from pathlib import Path

import pytest

FAKE_LLAMA = Path(__file__).with_name("fake_llama_server.py")


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BT_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def wav_file(tmp_path):
    """2 s of 16 kHz mono silence."""
    path = tmp_path / "silence.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 32000)
    return path


@pytest.fixture
def fake_llama(tmp_path):
    """Factory: fake_llama(mode) -> an executable that behaves like llama-server in that mode.

    Every server still running at teardown is stopped, so no fake outlives its test.
    """
    def make(mode: str) -> Path:
        if sys.platform == "win32":
            launcher = tmp_path / f"llama-server-{mode}.cmd"
            launcher.write_text(f'@"{sys.executable}" "{FAKE_LLAMA}" {mode} %*\r\n')
        else:
            launcher = tmp_path / f"llama-server-{mode}"
            # exec, so the server's pid is the fake itself and terminate() reaches it.
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_LLAMA}" {mode} "$@"\n')
            launcher.chmod(0o755)
        return launcher

    yield make
    from booktranscriber import llm_server
    llm_server._stop_all()
