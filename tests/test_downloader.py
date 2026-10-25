import hashlib
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from booktranscriber.downloader import ChecksumError, DownloadCancelled, NetworkError, download_file

PAYLOAD = os.urandom(3 * 1024 * 1024)


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Server:
    honour_range = True
    fail_after = None
    last_range = None
    requests = 0


@pytest.fixture
def server():
    state = Server()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            state.requests += 1
            rng = self.headers.get("Range")
            state.last_range = rng
            start = 0
            if rng and state.honour_range:
                start = int(rng.split("=")[1].split("-")[0])
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}")
            else:
                self.send_response(200)
            body = PAYLOAD[start:]
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if state.fail_after is not None:
                self.wfile.write(body[: state.fail_after])
                self.wfile.flush()
                self.connection.shutdown(2)
                return
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    state.url = f"http://127.0.0.1:{httpd.server_port}/f.bin"
    yield state
    httpd.shutdown()


def noop(n):
    pass


def test_full_download_verifies(server, tmp_path):
    dest = tmp_path / "f.bin"
    seen = []
    download_file(server.url, dest, len(PAYLOAD), sha(PAYLOAD), seen.append, threading.Event())
    assert dest.read_bytes() == PAYLOAD and seen[-1] == len(PAYLOAD)
    assert not (tmp_path / "f.bin.part").exists()


def test_resume_after_drop(server, tmp_path):
    server.fail_after = 1_000_000
    with pytest.raises(NetworkError):
        download_file(server.url, tmp_path / "f.bin", len(PAYLOAD), sha(PAYLOAD), noop, threading.Event())
    assert (tmp_path / "f.bin.part").stat().st_size > 0
    server.fail_after = None
    download_file(server.url, tmp_path / "f.bin", len(PAYLOAD), sha(PAYLOAD), noop, threading.Event())
    assert (tmp_path / "f.bin").read_bytes() == PAYLOAD and server.last_range.startswith("bytes=")


def test_server_ignoring_range_restarts_cleanly(server, tmp_path):
    (tmp_path / "f.bin.part").write_bytes(PAYLOAD[:500_000])
    server.honour_range = False
    seen = []
    download_file(server.url, tmp_path / "f.bin", len(PAYLOAD), sha(PAYLOAD), seen.append, threading.Event())
    assert (tmp_path / "f.bin").read_bytes() == PAYLOAD
    assert 0 in seen    # progress reset when the server restarted from scratch


def test_checksum_mismatch_deletes_part(server, tmp_path):
    with pytest.raises(ChecksumError):
        download_file(server.url, tmp_path / "f.bin", len(PAYLOAD), "0" * 64, noop, threading.Event())
    assert not (tmp_path / "f.bin.part").exists() and not (tmp_path / "f.bin").exists()


def test_size_mismatch_is_checksum_error(server, tmp_path):
    # Shorter than promised: first kept and resumed (a connection that closed early)...
    with pytest.raises(NetworkError):
        download_file(server.url, tmp_path / "f.bin", len(PAYLOAD) + 1, None, noop, threading.Event())
    assert (tmp_path / "f.bin.part").stat().st_size == len(PAYLOAD)
    # ...but when the server has nothing more to send, the file is damaged.
    with pytest.raises(ChecksumError):
        download_file(server.url, tmp_path / "f.bin", len(PAYLOAD) + 1, None, noop, threading.Event())
    assert not (tmp_path / "f.bin.part").exists()


def test_cancel_keeps_part(server, tmp_path):
    ev = threading.Event()

    def prog(n):
        if n > 1_000_000:
            ev.set()
    with pytest.raises(DownloadCancelled):
        download_file(server.url, tmp_path / "f.bin", len(PAYLOAD), None, prog, ev)
    assert (tmp_path / "f.bin.part").exists() and not (tmp_path / "f.bin").exists()


def test_existing_dest_skips(server, tmp_path):
    (tmp_path / "f.bin").write_bytes(PAYLOAD)
    seen = []
    download_file(server.url, tmp_path / "f.bin", len(PAYLOAD), sha(PAYLOAD), seen.append, threading.Event())
    assert server.requests == 0 and seen == [len(PAYLOAD)]


def test_unreachable_server_is_network_error(tmp_path):
    with pytest.raises(NetworkError):
        download_file("http://127.0.0.1:9/x", tmp_path / "f.bin", 10, None, noop, threading.Event())


def test_http_error_status_is_network_error(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(404)))
    with pytest.raises(NetworkError) as e:
        download_file("http://example.invalid/x", tmp_path / "f.bin", 10, None, noop, threading.Event(), client=client)
    assert e.value.transient is False       # the server said no: waiting won't help


def test_checksum_pass_honours_cancel(tmp_path):
    from booktranscriber.downloader import _sha256
    f = tmp_path / "big.bin"
    f.write_bytes(b"x" * (3 * 1024 * 1024))
    ev = threading.Event()
    ev.set()
    with pytest.raises(DownloadCancelled):
        _sha256(f, ev)


def test_status_errors_say_whether_waiting_helps():
    import httpx
    from booktranscriber.downloader import is_transient
    req = httpx.Request("GET", "https://x")

    def err(code):
        return httpx.HTTPStatusError(str(code), request=req, response=httpx.Response(code, request=req))
    assert not is_transient(err(404)) and not is_transient(err(403))
    assert is_transient(err(503)) and is_transient(err(429)) and is_transient(httpx.ConnectError("down"))
