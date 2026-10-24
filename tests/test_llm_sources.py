import io
import os
import tarfile
import threading
import zipfile

import pytest

from booktranscriber import llm_catalog as cat
from booktranscriber import llm_sources as src
from booktranscriber.downloader import DownloadCancelled


def _tar(path, members):
    """members: (name, data, mode) or (name, linkname) for a symlink."""
    with tarfile.open(path, "w:gz") as t:
        for m in members:
            if len(m) == 2:
                info = tarfile.TarInfo(m[0])
                info.type = tarfile.SYMTYPE
                info.linkname = m[1]
                t.addfile(info)
            else:
                info = tarfile.TarInfo(m[0])
                info.size = len(m[1])
                info.mode = m[2]
                t.addfile(info, io.BytesIO(m[1]))


def test_extract_tar_makes_server_executable(tmp_path):
    archive = tmp_path / "a.tar.gz"
    _tar(archive, [("llama-b11539/llama-server", b"bin", 0o644), ("llama-b11539/libx.so", b"so", 0o644)])
    dest = src.runtime_dir("vulkan")
    src.extract_archive(archive, dest)
    found = src.server_binary("vulkan")
    assert found == dest / "llama-b11539" / "llama-server"
    assert os.access(found, os.X_OK)


def test_extract_zip_windows_layout(tmp_path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("llama-server.exe", b"exe")
        z.writestr("ggml.dll", b"dll")
    dest = tmp_path / "out"
    src.extract_archive(archive, dest)
    assert (dest / "llama-server.exe").read_bytes() == b"exe"
    assert (dest / "ggml.dll").exists()
    assert (dest / ".done").exists()
    assert not archive.exists()


def test_extract_rejects_traversal_and_symlink_escape(tmp_path):
    dest = tmp_path / "out" / "inner"
    tar = tmp_path / "a.tar.gz"
    _tar(tar, [("../evil", b"x", 0o644), ("x", "/etc/passwd"), ("ok", b"ok", 0o644),
                ("llama-server", b"b", 0o755)])
    src.extract_archive(tar, dest)
    assert not (tmp_path / "out" / "evil").exists()
    assert not (dest / "x").is_symlink()
    assert (dest / "ok").exists()
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("/abs/evil", b"x")
        zf.writestr("../evil2", b"x")
        zf.writestr("fine", b"y")
        zf.writestr("llama-server.exe", b"b")
    src.extract_archive(z, dest)
    assert not (tmp_path / "out" / "evil2").exists()
    assert not (dest / "abs").exists()
    assert (dest / "fine").exists()


def test_extract_cancel_keeps_archive(tmp_path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("llama-server.exe", b"exe")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DownloadCancelled):
        src.extract_archive(archive, tmp_path / "out", cancel)
    assert archive.exists()
    assert not (tmp_path / "out" / ".done").exists()


def test_runtime_files_dedupes_macos():
    mac = src.runtime_files("macos", "metal")
    assert len(mac) == 1 and mac[0][0] == "metal"
    assert mac[0][1].url == cat.RELEASE_URL + cat.RUNTIME_ASSETS[("macos", "metal")].filename
    lin = src.runtime_files("linux", "vulkan")
    assert [b for b, _ in lin] == ["vulkan", "cpu"]
    assert lin[0][1].size == cat.RUNTIME_ASSETS[("linux", "vulkan")].size
    assert lin[1][1].dest.parent.name == "archives"


def test_server_binary_cpu_falls_back_to_metal(tmp_path):
    assert src.server_binary("cpu") is None
    fake = src.runtime_dir("metal") / "llama-b11539"
    fake.mkdir(parents=True)
    (fake / "llama-server").write_bytes(b"x")
    assert src.server_binary("cpu") is None  # no .done yet
    (src.runtime_dir("metal") / ".done").write_text("ok")
    assert src.server_binary("cpu") == fake / "llama-server"


def test_model_file():
    f = src.model_file("gemma-4-e4b")
    m = cat.MODELS["gemma-4-e4b"]
    assert m.revision in f.url and f.url.endswith(m.filename)
    assert f.dest.name == m.filename and f.dest.parent.name == "models"
    assert f.size == m.size and f.sha256 == m.sha256


def test_os_error_during_extract_keeps_archive_and_no_marker(tmp_path, monkeypatch):
    archive = tmp_path / "a.tar.gz"
    _tar(archive, [("llama-server", b"b", 0o755)])

    def boom(self, *a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(tarfile.TarFile, "extract", boom)
    with pytest.raises(OSError):
        src.extract_archive(archive, tmp_path / "out")
    assert archive.exists() and not (tmp_path / "out" / ".done").exists()


def test_archive_without_server_raises_and_keeps_archive(tmp_path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("ggml.dll", b"dll")
    with pytest.raises(RuntimeError):
        src.extract_archive(archive, tmp_path / "out")
    assert archive.exists() and not (tmp_path / "out" / ".done").exists()


def test_server_binary_requires_done_marker():
    d = src.runtime_dir("vulkan")
    d.mkdir(parents=True)
    (d / "llama-server").write_bytes(b"x")
    assert src.server_binary("vulkan") is None
