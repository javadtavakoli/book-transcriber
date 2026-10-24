import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # GUI tests run headless

import sys
import wave
from pathlib import Path

import pytest

FAKE_LLAMA = Path(__file__).with_name("fake_llama_server.py")
WINDOWS = sys.platform == "win32"


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
def fake_llama(tmp_path, monkeypatch):
    """Factory: fake_llama(mode) -> an executable that behaves like llama-server in that mode.

    Every server still running at teardown is stopped, so no fake outlives its test.
    """
    if WINDOWS:
        monkeypatch.setenv("FAKE_LLAMA_PIDS", str(tmp_path / "fake-llama-pids"))

    def make(mode: str) -> Path:
        if WINDOWS:
            # Windows runs only real executables, so a .cmd starts Python: the server's pid is cmd.exe's,
            # and the fake is its child (it records its pid; see llama_alive).
            launcher = tmp_path / f"llama-server-{mode}.cmd"
            launcher.write_text(f'@"{sys.executable}" "{FAKE_LLAMA}" {mode} %*\r\n')
        else:
            launcher = tmp_path / f"llama-server-{mode}"
            # A Python script run directly: the server's pid is the fake itself (terminate() reaches it),
            # and its command line holds the launcher's path, like a real llama-server's would.
            launcher.write_text(f"#!{sys.executable}\nimport runpy, sys\n"
                                f"sys.argv = [{str(FAKE_LLAMA)!r}, {mode!r}] + sys.argv[1:]\n"
                                f"runpy.run_path({str(FAKE_LLAMA)!r}, run_name='__main__')\n")
            launcher.chmod(0o755)
        return launcher

    yield make
    from booktranscriber import llm_server
    llm_server._stop_all()


def _pid_alive(pid: int) -> bool:
    if WINDOWS:     # os.kill(pid, 0) there sends a Ctrl+C rather than checking
        from booktranscriber import winjob
        return winjob.alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def llama_alive(tmp_path):
    """llama_alive(pid) -> whether the fake llama-server started as `pid` is still running.

    On Windows `pid` is the .cmd launcher; the Python fake under it counts too, as it is what holds
    the port. With no pid recorded the fake never started.
    """
    def alive(pid: int) -> bool:
        pids = [pid]
        recorded = tmp_path / "fake-llama-pids" / str(pid)
        if WINDOWS and recorded.exists():
            pids.append(int(recorded.read_text()))
        return any(_pid_alive(p) for p in pids)
    return alive
