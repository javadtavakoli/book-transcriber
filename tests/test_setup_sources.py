import json
import zipfile
from pathlib import Path

import pytest

from booktranscriber.gpu import nvidia_lib_dirs
from booktranscriber.setup_sources import extract_nvidia_libs, pick_wheel

FIXTURES = Path(__file__).parent / "fixtures"


def test_pick_wheel_linux_and_windows():
    j = json.loads((FIXTURES / "pypi_cublas.json").read_text())
    url, size, sha, name = pick_wheel(j, "linux")
    assert "manylinux" in name and name.endswith("x86_64.whl") and size > 0 and len(sha) == 64
    assert url.startswith("https://")
    assert pick_wheel(j, "windows")[3].endswith("win_amd64.whl")


def test_pick_wheel_none():
    with pytest.raises(LookupError):
        pick_wheel({"urls": []}, "linux")
    with pytest.raises(LookupError):
        pick_wheel(json.loads((FIXTURES / "pypi_cublas.json").read_text()), "macos")


def test_extract_only_libs(tmp_path):
    whl = tmp_path / "x.whl"
    with zipfile.ZipFile(whl, "w") as z:
        z.writestr("nvidia/cublas/lib/libcublas.so.12", b"so")
        z.writestr("nvidia/cublas/include/cublas.h", b"h")
        z.writestr("nvidia_cublas_cu12-12.9.dist-info/METADATA", b"m")
    out = extract_nvidia_libs(whl, tmp_path / "gpu", windows=False)
    assert out == [tmp_path / "gpu/nvidia/cublas/lib/libcublas.so.12"] and not whl.exists()
    assert (tmp_path / "gpu/nvidia/cublas/lib/libcublas.so.12").read_bytes() == b"so"
    assert nvidia_lib_dirs([str(tmp_path / "gpu/nvidia")], False) == [str(tmp_path / "gpu/nvidia/cublas/lib")]


def test_extract_windows_uses_bin(tmp_path):
    whl = tmp_path / "x.whl"
    with zipfile.ZipFile(whl, "w") as z:
        z.writestr("nvidia/cublas/bin/cublas64_12.dll", b"dll")
        z.writestr("nvidia/cublas/lib/x64/cublas.lib", b"lib")
    assert extract_nvidia_libs(whl, tmp_path / "gpu", windows=True) == [tmp_path / "gpu/nvidia/cublas/bin/cublas64_12.dll"]


def test_extract_rejects_path_traversal(tmp_path):
    whl = tmp_path / "x.whl"
    with zipfile.ZipFile(whl, "w") as z:
        z.writestr("nvidia/cublas/lib/../../../../evil.so", b"x")
    extract_nvidia_libs(whl, tmp_path / "gpu", windows=False)
    assert not (tmp_path / "evil.so").exists()


def test_extract_honours_cancel_and_keeps_wheel(tmp_path):
    import threading

    from booktranscriber.downloader import DownloadCancelled
    whl = tmp_path / "x.whl"
    with zipfile.ZipFile(whl, "w") as z:
        z.writestr("nvidia/cublas/lib/libcublas.so.12", b"so")
    ev = threading.Event()
    ev.set()
    with pytest.raises(DownloadCancelled):
        extract_nvidia_libs(whl, tmp_path / "gpu", windows=False, cancel=ev)
    assert whl.exists()
