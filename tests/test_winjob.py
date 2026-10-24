import ctypes
import json
import os
import subprocess
import sys
import time

import pytest

from booktranscriber import llm_server, paths, winjob

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Win32 Job Objects and process handles")
SLEEP = "import time; time.sleep(60)"


def _wait_dead(pid: int, seconds: float = 5) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not winjob.alive(pid):
            return True
        time.sleep(0.1)
    return False


@windows_only
def test_job_kills_child_tree(tmp_path):
    job = winjob.create_kill_on_close_job()
    assert job is not None
    pid_file = tmp_path / "grandchild.pid"
    script = f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"
    proc = subprocess.Popen(["cmd", "/c", sys.executable, "-c", script], creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        assert winjob.assign(job, proc.pid)
        deadline = time.monotonic() + 10
        while not pid_file.exists() or not pid_file.read_text():
            assert time.monotonic() < deadline, "the python grandchild never started"
            time.sleep(0.1)
        grandchild = int(pid_file.read_text())
        assert grandchild != proc.pid and winjob.alive(grandchild)
        winjob.terminate_tree(job)
        assert _wait_dead(grandchild)
        assert proc.wait(5) is not None
    finally:
        winjob.close(job)
        if proc.poll() is None:
            proc.kill()


@windows_only
def test_image_path_of_self():
    expected = {os.path.normcase(sys.executable), os.path.normcase(getattr(sys, "_base_executable", ""))}
    assert os.path.normcase(winjob.image_path(os.getpid())) in expected


@windows_only
def test_alive_and_kill():
    proc = subprocess.Popen([sys.executable, "-c", SLEEP])
    try:
        assert winjob.alive(proc.pid)
        winjob.kill(proc.pid)
        assert proc.wait(5) is not None
        assert not winjob.alive(proc.pid)    # exited, though this Popen still holds its handle
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.skipif(ctypes.sizeof(ctypes.c_void_p) != 8, reason="the app ships 64-bit only")
def test_extended_limits_layout_matches_win64():
    # SetInformationJobObject rejects a wrong size, and that can't be seen off Windows; check it everywhere.
    assert ctypes.sizeof(winjob._BasicLimits) == 64
    assert ctypes.sizeof(winjob._ExtendedLimits) == 144


@pytest.mark.skipif(sys.platform == "win32", reason="the no-op path is for other systems")
def test_off_windows_noops():
    assert winjob.create_kill_on_close_job() is None
    assert winjob.assign(1, os.getpid()) is False
    assert winjob.image_path(os.getpid()) is None
    assert winjob.alive(os.getpid()) is False
    winjob.terminate_tree(1)
    winjob.kill(os.getpid())    # must not touch this process
    winjob.close(1)


# --- reap_stale on Windows matches the recorded image path --------------------------------
def _record(pid: int, binary: str) -> None:
    f = paths.data_dir() / "llm" / "server.pid"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"pid": pid, "binary": binary}), "utf-8")


@windows_only
def test_reap_stale_kills_recorded_image():
    child = subprocess.Popen([sys.executable, "-c", SLEEP])
    try:
        _record(child.pid, sys.executable)
        assert llm_server.reap_stale() is True
        assert child.wait(10) is not None
    finally:
        if child.poll() is None:
            child.kill()


@windows_only
def test_reap_stale_ignores_other_image(tmp_path):
    child = subprocess.Popen([sys.executable, "-c", SLEEP])
    try:
        _record(child.pid, str(tmp_path / "llama-server.exe"))
        assert llm_server.reap_stale() is False
        assert child.poll() is None and winjob.alive(child.pid)
    finally:
        child.kill()
        child.wait()
