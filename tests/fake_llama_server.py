"""Stand-in for llama-server: scripted startup log, /health and /v1/chat/completions.

Usage: fake_llama_server.py <mode> --port N [real llama-server arguments, unknown ones ignored]
Modes: ok, slow (echo answers), fix (echo with one spelling fixed), think (echo after a
<think> block), dropfirst (first answer omits its last line, later ones echo), http500 (chat fails),
holdchat (echo, but only after HOLD_SECONDS: a request stays in flight), diefix (echoes the first
request, then dies like a native crash on the next), oom and crash (exit during load), hang (never ready).
If FAKE_LLAMA_LOG is set, the argument list is appended to that file as one JSON line.
If FAKE_LLAMA_CHATS is set, a line is appended to that file as each chat request arrives.
"""
import argparse
import json
import os
import re
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Real b11539 log lines (timestamp prefix M.SS.mmm.uuu, then a level letter).
LOAD_LINES = [
    "0.00.010.112 I build: 11539 (fake) with cc for x86_64-linux-gnu",
    "0.00.120.441 I load_model: loading model '{model}'",
    "0.01.440.317 I llama_model_loader: loaded meta data with 46 key-value pairs and 720 tensors",
    "0.02.251.405 I load_tensors: loading model tensors, this can take a while... (load_mode = mmap)",
    "1.20.004.019 I load_tensors:      Vulkan0 model buffer size =  3900.00 MiB",
    "2.50.110.902 I llama_context: constructing llama_context",
    "2.51.020.331 I llama_kv_cache:    Vulkan0 KV buffer size =   512.00 MiB",
    "3.10.300.556 I common_init_from_params: warming up the model with an empty run",
]
READY_LINE = "3.15.707.724 I srv  update_slots: all slots are idle"
OOM_LINES = [
    "0.03.112.870 E ggml_vulkan: Device memory allocation of size 2147483648 failed.",
    "0.03.112.901 E ggml_vulkan: vk::Device::allocateMemory: ErrorOutOfDeviceMemory",
    "0.03.113.004 E llama_model_load: error loading model: unable to allocate Vulkan0 buffer",
]
HOLD_SECONDS = 30   # long enough that a test waiting it out fails, short enough not to hang forever
LOADING = {"error": {"message": "Loading model", "type": "unavailable_error", "code": 503}}

ready = threading.Event()
chats = []   # one entry per chat request answered


def log(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def answer(mode: str, body: dict) -> str:
    user = next((m["content"] for m in reversed(body.get("messages", [])) if m.get("role") == "user"), "")
    lines = "\n".join(l for l in user.splitlines() if re.match(r"\s*\[\d+\]", l))
    if mode == "fix":
        lines = lines.replace("انقاشی", "نقاشی")
    if mode == "think":
        lines = "<think>\nThe user wants spelling fixes. Let me check each line.\n</think>\n" + lines
    if mode == "dropfirst" and not chats:
        lines = "\n".join(lines.splitlines()[:-1])
    return lines


def die() -> None:
    log("0.03.200.000 W ggml_vulkan: device lost")
    # Die abruptly like a native crash, but without a core dump (SIGKILL; Windows has no signals).
    if sys.platform == "win32":
        os._exit(3)
    os.kill(os.getpid(), signal.SIGKILL)


def make_handler(mode: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, data: dict) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path != "/health":
                return self._send(404, {"error": {"message": "File Not Found", "code": 404}})
            if ready.is_set():
                self._send(200, {"status": "ok"})
            else:
                self._send(503, LOADING)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path != "/v1/chat/completions":
                return self._send(404, {"error": {"message": "File Not Found", "code": 404}})
            if not ready.is_set():
                return self._send(503, LOADING)
            if os.environ.get("FAKE_LLAMA_CHATS"):
                with open(os.environ["FAKE_LLAMA_CHATS"], "a", encoding="utf-8") as f:
                    f.write("chat\n")
            if mode == "holdchat":
                time.sleep(HOLD_SECONDS)
            if mode == "diefix" and chats:
                die()
            if mode == "http500":
                return self._send(500, {"error": {"message": "fake failure", "type": "server_error",
                                                  "code": 500}})
            content = answer(mode, body)
            chats.append(body)
            self._send(200, {
                "id": "chatcmpl-fake", "object": "chat.completion", "model": "fake",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": len(content.split()),
                          "total_tokens": 100 + len(content.split())},
            })

        def log_message(self, *args):
            pass

    return Handler


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode")
    p.add_argument("-m", "--model", default="")
    p.add_argument("-c", "--ctx-size", default="4096")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--jinja", action="store_true")
    p.add_argument("-ngl", "--n-gpu-layers", default=None)
    p.add_argument("-lv", "--verbosity", default=None)
    args, _unknown = p.parse_known_args()
    if os.environ.get("FAKE_LLAMA_LOG"):
        with open(os.environ["FAKE_LLAMA_LOG"], "a", encoding="utf-8") as f:
            f.write(json.dumps(sys.argv[2:]) + "\n")

    # Like llama-server, listen first and answer 503 while the model loads.
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.mode))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    delay = 0.35 if args.mode == "slow" else 0.05
    stop_after = 4 if args.mode in ("oom", "crash", "hang") else len(LOAD_LINES)
    for line in LOAD_LINES[:stop_after]:
        log(line.format(model=args.model))
        time.sleep(delay)
    if args.mode == "oom":
        for line in OOM_LINES:
            log(line)
        sys.exit(1)
    if args.mode == "crash":
        die()
    if args.mode == "hang":
        while True:
            time.sleep(1)
    ready.set()
    log(READY_LINE)
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
