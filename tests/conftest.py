import wave

import pytest


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
