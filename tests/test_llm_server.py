import gc
import json
import os
import socket
import threading

import httpx
import pytest

from booktranscriber import llm_server
from booktranscriber.downloader import DownloadCancelled
from booktranscriber.llm_server import (LlamaServer, LlmStartError, LoadEstimator, parse_stage,
                                        start_with_fallback)
from booktranscriber.settings import Settings

REAL_LINES = [
    "0.00.010.112 I build: 11539 (abc1234) with cc for x86_64-linux-gnu",
    "0.00.120.441 I load_model: loading model '/models/gemma.gguf'",
    "0.01.440.317 I llama_model_loader: loaded meta data with 46 key-value pairs and 720 tensors",
    "0.02.251.405 I load_tensors: loading model tensors, this can take a while... (load_mode = mmap)",
    "1.20.000.000 I load_tensors:      Vulkan0 model buffer size =  3900.00 MiB",
    "2.50.000.000 I llama_context: constructing llama_context",
    "2.51.000.000 I llama_kv_cache:    Vulkan0 KV buffer size =   512.00 MiB",
    "3.10.000.000 I common_init_from_params: warming up the model with an empty run",
    "3.15.707.724 I srv  update_slots: all slots are idle",
]


@pytest.fixture
def model(tmp_path):
    path = tmp_path / "model.gguf"
    path.write_bytes(b"GGUF")
    return path


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_parse_stage_monotonic():
    seen, current = [], 0.0
    for line in REAL_LINES:
        current = parse_stage(line, current)
        seen.append(current)
    assert seen == sorted(seen)
    assert seen[1] == 0.05 and seen[3] == 0.25 and seen[-1] == 1.0
    assert parse_stage("0.02.251.405 I load_tensors: loading model tensors", 0.85) == 0.85
    assert parse_stage("something unrelated", 0.3) == 0.3


def test_estimator_uses_previous_duration():
    est = LoadEstimator(100)
    assert est.fraction(0.25, 50) == 0.5
    assert est.fraction(0.9, 50) == 0.9
    assert est.fraction(0.3, 500) == 0.97
    assert est.eta(40) == 60
    assert est.eta(150) is None
    unknown = LoadEstimator(None)
    assert unknown.fraction(0.3, 50) == 0.3
    assert unknown.eta(50) is None


def test_start_reports_progress_and_ready(fake_llama, model):
    values = []
    srv = LlamaServer(fake_llama("ok"), model, gpu=True)
    srv.start(lambda f, eta: values.append(f), threading.Event(), timeout=20)
    try:
        assert srv.is_ready()
        assert values == sorted(values) and values[-1] == 1.0
        assert len(set(values)) >= 3
        assert srv.load_seconds is not None and srv.load_seconds > 0
        r = httpx.get(f"http://127.0.0.1:{srv.port}/health")
        assert r.json() == {"status": "ok"}
    finally:
        srv.stop()


def test_gpu_route_passes_no_ngl_and_cpu_route_passes_zero(fake_llama, model, tmp_path, monkeypatch):
    log = tmp_path / "argv.jsonl"
    monkeypatch.setenv("FAKE_LLAMA_LOG", str(log))
    for gpu in (True, False):
        srv = LlamaServer(fake_llama("ok"), model, gpu=gpu, ctx=4096)
        srv.start(lambda f, eta: None, threading.Event(), timeout=20)
        srv.stop()
    gpu_argv, cpu_argv = [json.loads(line) for line in log.read_text().splitlines()]
    for argv in (gpu_argv, cpu_argv):
        assert argv[argv.index("-m") + 1] == str(model)
        assert argv[argv.index("-c") + 1] == "4096"
        assert argv[argv.index("--host") + 1] == "127.0.0.1"
        assert "--jinja" in argv
        assert argv[argv.index("-lv") + 1] == "4"   # default verbosity hides the loading stages
    assert "-ngl" not in gpu_argv
    assert cpu_argv[cpu_argv.index("-ngl") + 1] == "0"


def test_oom_is_memory_kind(fake_llama, model):
    srv = LlamaServer(fake_llama("oom"), model, gpu=True)
    with pytest.raises(LlmStartError) as e:
        srv.start(lambda f, eta: None, threading.Event(), timeout=20)
    assert e.value.kind == "memory"
    assert not srv.is_ready()


def test_crash_is_crash_kind(fake_llama, model):
    srv = LlamaServer(fake_llama("crash"), model, gpu=True)
    with pytest.raises(LlmStartError) as e:
        srv.start(lambda f, eta: None, threading.Event(), timeout=20)
    assert e.value.kind == "crash"


def test_missing_binary_is_missing_kind(tmp_path, model):
    srv = LlamaServer(tmp_path / "nope" / "llama-server", model, gpu=True)
    with pytest.raises(LlmStartError) as e:
        srv.start(lambda f, eta: None, threading.Event())
    assert e.value.kind == "missing"


def test_hang_times_out_and_kills(fake_llama, model):
    srv = LlamaServer(fake_llama("hang"), model, gpu=True)
    with pytest.raises(LlmStartError) as e:
        srv.start(lambda f, eta: None, threading.Event(), timeout=1.5)
    assert e.value.kind == "timeout"
    assert _gone(srv.pid)


def _binaries(monkeypatch, mapping):
    calls = []

    def fake_binary(backend):
        calls.append(backend)
        return mapping.get(backend)
    monkeypatch.setattr(llm_server, "server_binary", fake_binary)
    return calls


def test_crash_falls_back_to_cpu_once(fake_llama, model, monkeypatch):
    calls = _binaries(monkeypatch, {"vulkan": fake_llama("crash"), "cpu": fake_llama("ok")})
    settings = Settings(llm_model_path=str(model), llm_backend="vulkan")
    fallbacks = []
    srv = start_with_fallback(settings, lambda f, eta: None, threading.Event(),
                              lambda: fallbacks.append(1))
    try:
        assert fallbacks == [1]
        assert calls == ["vulkan", "cpu"]
        assert srv.is_ready() and not srv.gpu
        assert settings.llm_load_seconds == srv.load_seconds
    finally:
        srv.stop()


def test_missing_gpu_binary_falls_back_to_cpu(fake_llama, model, monkeypatch):
    _binaries(monkeypatch, {"cpu": fake_llama("ok")})
    settings = Settings(llm_model_path=str(model), llm_backend="vulkan")
    fallbacks = []
    srv = start_with_fallback(settings, lambda f, eta: None, threading.Event(),
                              lambda: fallbacks.append(1))
    try:
        assert fallbacks == [1] and srv.is_ready()
    finally:
        srv.stop()


def test_oom_does_not_fall_back(fake_llama, model, monkeypatch):
    calls = _binaries(monkeypatch, {"vulkan": fake_llama("oom"), "cpu": fake_llama("ok")})
    settings = Settings(llm_model_path=str(model), llm_backend="vulkan")
    fallbacks = []
    with pytest.raises(LlmStartError) as e:
        start_with_fallback(settings, lambda f, eta: None, threading.Event(),
                            lambda: fallbacks.append(1))
    assert e.value.kind == "memory"
    assert fallbacks == [] and calls == ["vulkan"]
    assert settings.llm_load_seconds is None


def test_cpu_crash_is_not_retried(fake_llama, model, monkeypatch):
    calls = _binaries(monkeypatch, {"vulkan": fake_llama("crash"), "cpu": fake_llama("crash")})
    settings = Settings(llm_model_path=str(model), llm_backend="vulkan")
    fallbacks = []
    with pytest.raises(LlmStartError) as e:
        start_with_fallback(settings, lambda f, eta: None, threading.Event(),
                            lambda: fallbacks.append(1))
    assert e.value.kind == "crash"
    assert fallbacks == [1] and calls == ["vulkan", "cpu"]


def test_missing_model_is_missing_kind(tmp_path):
    settings = Settings(llm_model_path=str(tmp_path / "gone.gguf"), llm_backend="vulkan")
    with pytest.raises(LlmStartError) as e:
        start_with_fallback(settings, lambda f, eta: None, threading.Event(), lambda: None)
    assert e.value.kind == "missing"


def test_cancel_during_load_kills_process(fake_llama, model):
    cancel = threading.Event()
    srv = LlamaServer(fake_llama("slow"), model, gpu=True)

    def on_progress(fraction, eta):
        if fraction >= 0.15:
            cancel.set()
    with pytest.raises(DownloadCancelled):
        srv.start(on_progress, cancel, timeout=20)
    assert _gone(srv.pid)
    assert not srv.is_ready()


def test_stop_is_idempotent_and_frees_port(fake_llama, model):
    srv = LlamaServer(fake_llama("ok"), model, gpu=True)
    srv.start(lambda f, eta: None, threading.Event(), timeout=20)
    port = srv.port
    srv.stop()
    srv.stop()
    assert not srv.is_ready()
    assert _gone(srv.pid)
    with pytest.raises(httpx.TransportError):
        httpx.get(f"http://127.0.0.1:{port}/health")
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))   # fails while anything still listens on it
        s.listen()


def test_no_orphan_after_owner_dies(fake_llama, model):
    srv = LlamaServer(fake_llama("ok"), model, gpu=True)
    srv.start(lambda f, eta: None, threading.Event(), timeout=20)
    pid = srv.pid
    del srv
    gc.collect()
    llm_server._stop_all()
    assert _gone(pid)


def test_chat_completions_echo_and_fix(fake_llama, model):
    user = "Fix these lines:\n[1] انقاشی خوب بود\n[2] آره خب"
    body = {"messages": [{"role": "system", "content": "rules"}, {"role": "user", "content": user}]}
    answers = {}
    for mode in ("ok", "fix", "think", "http500"):
        srv = LlamaServer(fake_llama(mode), model, gpu=True)
        srv.start(lambda f, eta: None, threading.Event(), timeout=20)
        try:
            r = httpx.post(f"http://127.0.0.1:{srv.port}/v1/chat/completions", json=body)
            answers[mode] = r
        finally:
            srv.stop()
    assert answers["ok"].json()["choices"][0]["message"]["content"] == "[1] انقاشی خوب بود\n[2] آره خب"
    assert answers["fix"].json()["choices"][0]["message"]["content"] == "[1] نقاشی خوب بود\n[2] آره خب"
    assert "usage" in answers["ok"].json()
    think = answers["think"].json()["choices"][0]["message"]["content"]
    assert think.startswith("<think>") and think.endswith("[1] انقاشی خوب بود\n[2] آره خب")
    assert answers["http500"].status_code == 500


def test_stop_all_stops_live_servers(fake_llama, model):
    srv = LlamaServer(fake_llama("ok"), model, gpu=True)
    srv.start(lambda f, eta: None, threading.Event(), timeout=20)
    llm_server._stop_all()
    assert not srv.is_ready() and _gone(srv.pid)


def test_progress_callback_error_stops_process(fake_llama, model):
    srv = LlamaServer(fake_llama("slow"), model, gpu=True)

    def on_progress(fraction, eta):
        raise RuntimeError("window closed")
    with pytest.raises(RuntimeError):
        srv.start(on_progress, threading.Event(), timeout=20)
    assert _gone(srv.pid)


def test_stop_from_another_thread_during_load_is_a_cancel(fake_llama, model, monkeypatch):
    calls = _binaries(monkeypatch, {"vulkan": fake_llama("slow"), "cpu": fake_llama("ok")})
    settings = Settings(llm_model_path=str(model), llm_backend="vulkan")
    fallbacks, servers = [], []
    real_start = LlamaServer.start

    def tracked_start(self, *args, **kwargs):
        servers.append(self)
        threading.Timer(0.4, self.stop).start()
        return real_start(self, *args, **kwargs)
    monkeypatch.setattr(LlamaServer, "start", tracked_start)
    with pytest.raises(DownloadCancelled):
        start_with_fallback(settings, lambda f, eta: None, threading.Event(),
                            lambda: fallbacks.append(1))
    assert fallbacks == [] and calls == ["vulkan"]
    assert _gone(servers[0].pid)


@pytest.mark.parametrize("var, proxy", [("HTTP_PROXY", "http://127.0.0.1:9"),
                                        ("ALL_PROXY", "socks5://127.0.0.1:9")])
def test_health_poll_ignores_environment_proxy(fake_llama, model, monkeypatch, var, proxy):
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(var, proxy)
    monkeypatch.setenv(var.lower(), proxy)
    srv = LlamaServer(fake_llama("ok"), model, gpu=True)
    try:
        srv.start(lambda f, eta: None, threading.Event(), timeout=5)
        assert srv.is_ready()
    finally:
        srv.stop()


def test_local_client_ignores_environment_proxy(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:9")
    with llm_server.local_client(3) as client:
        assert client.timeout.read == 3
        assert client.trust_env is False


def test_first_load_uses_guess_for_fraction_but_not_eta():
    est = LoadEstimator(None)
    assert llm_server.FIRST_LOAD_GUESS_SECONDS == 180
    assert est.fraction(0.30, 90) == 0.5
    assert est.fraction(0.30, 10) == 0.30
    assert est.fraction(0.30, 1000) == 0.97
    assert est.eta(90) is None


# --- a llama-server left behind by a crashed app is stopped next time ---------------------
def _pid_file():
    from booktranscriber import paths
    return paths.data_dir() / "llm" / "server.pid"


def test_pid_file_written_on_start_and_removed_on_stop(fake_llama, model):
    srv = LlamaServer(fake_llama("ok"), model, gpu=True)
    srv.start(lambda f, eta: None, threading.Event(), timeout=20)
    data = json.loads(_pid_file().read_text("utf-8"))
    assert data == {"pid": srv.pid, "binary": os.path.abspath(fake_llama("ok"))}
    srv.stop()
    assert not _pid_file().exists()


@pytest.mark.skipif(os.name != "posix", reason="Windows reaping comes with the Windows stage")
def test_reap_stale_stops_a_server_left_by_a_crash(fake_llama, model):
    srv = LlamaServer(fake_llama("ok"), model, gpu=True)
    srv.start(lambda f, eta: None, threading.Event(), timeout=20)
    proc = srv._proc
    # Simulate the app dying: nothing in this process remembers the server any more.
    srv._finalizer.detach()
    srv._proc = None
    llm_server._servers.discard(srv)
    try:
        assert _pid_file().exists() and proc.poll() is None
        assert llm_server.reap_stale() is True
        assert proc.wait(10) is not None
        assert not _pid_file().exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


@pytest.mark.skipif(os.name != "posix", reason="Windows reaping comes with the Windows stage")
def test_reap_stale_leaves_an_unrelated_process_alone(tmp_path):
    import subprocess
    other = subprocess.Popen(["sleep", "30"])
    try:
        _pid_file().parent.mkdir(parents=True, exist_ok=True)
        _pid_file().write_text(json.dumps({"pid": other.pid, "binary": str(tmp_path / "llama-server")}), "utf-8")
        assert llm_server.reap_stale() is False
        assert other.poll() is None and not _pid_file().exists()
    finally:
        other.kill()
        other.wait()


@pytest.mark.parametrize("content", ["not json", '{"pid": "x"}', "[]", None])
def test_reap_stale_cleans_up_dead_or_garbage_files(content):
    import subprocess
    import sys
    _pid_file().parent.mkdir(parents=True, exist_ok=True)
    if content is None:     # a process that has already exited
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        content = json.dumps({"pid": dead.pid, "binary": sys.executable})
    _pid_file().write_text(content, "utf-8")
    assert llm_server.reap_stale() is False
    assert not _pid_file().exists()
    assert llm_server.reap_stale() is False      # no file at all: nothing to do
