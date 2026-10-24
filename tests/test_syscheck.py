import subprocess

import pytest

from booktranscriber.syscheck import (GpuInfo, SystemInfo, choose_whisper_model, detect_system,
                                      find_existing_model, parse_nvidia_smi, source_checkout_dir)


def test_parse_nvidia_smi():
    assert parse_nvidia_smi("NVIDIA GeForce RTX 4050 Laptop GPU, 6141\n") == GpuInfo("NVIDIA GeForce RTX 4050 Laptop GPU", 6141)
    assert parse_nvidia_smi("") is None
    assert parse_nvidia_smi("garbage") is None


def test_detect_system_without_nvidia_smi(monkeypatch, tmp_path):
    def missing(*a, **k):
        raise FileNotFoundError()
    monkeypatch.setattr(subprocess, "run", missing)
    info = detect_system(tmp_path)
    assert info.gpu is None and info.free_bytes > 0 and info.os in ("linux", "windows", "macos")


def test_detect_system_nvidia_smi_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 9, "", "err"))
    assert detect_system(tmp_path).gpu is None


@pytest.mark.parametrize("gpu,expected", [(GpuInfo("x", 6141), "large-v3"), (GpuInfo("x", 2048), "large-v3-turbo"),
                                          (None, "large-v3-turbo")])
def test_choose_whisper_model(gpu, expected):
    assert choose_whisper_model(SystemInfo("linux", gpu, 10**11)) == expected


def test_find_existing_model_hf_layout(tmp_path):
    snap = tmp_path / "models--Systran--faster-whisper-large-v3" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(b"x")
    assert find_existing_model([tmp_path], "large-v3") == snap
    assert find_existing_model([tmp_path], "large-v3-turbo") is None


def test_find_existing_model_plain_dir_and_missing_dirs(tmp_path):
    d = tmp_path / "faster-whisper-large-v3-turbo"
    d.mkdir()
    (d / "model.bin").write_bytes(b"x")
    assert find_existing_model([tmp_path / "nope", tmp_path], "large-v3-turbo") == d


def test_source_checkout_dir_is_repo():
    assert (source_checkout_dir() / "transcribe.py").is_file()


def test_total_ram_bytes_positive():
    from booktranscriber.syscheck import total_ram_bytes
    assert total_ram_bytes() > 0
