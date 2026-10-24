import subprocess

import pytest

from booktranscriber import syscheck
from booktranscriber.syscheck import (GpuInfo, SystemInfo, choose_whisper_model, detect_system,
                                      find_existing_model, is_nvidia, parse_amdgpu_sysfs, parse_nvidia_smi,
                                      parse_windows_adapters, source_checkout_dir)


def test_parse_nvidia_smi():
    assert parse_nvidia_smi("NVIDIA GeForce RTX 4050 Laptop GPU, 6141\n") == GpuInfo("NVIDIA GeForce RTX 4050 Laptop GPU", 6141)
    assert parse_nvidia_smi("") is None
    assert parse_nvidia_smi("garbage") is None


def test_detect_system_without_nvidia_smi(monkeypatch, tmp_path):
    def missing(*a, **k):
        raise FileNotFoundError()
    monkeypatch.setattr(subprocess, "run", missing)
    monkeypatch.setattr(syscheck, "_query_amdgpu_sysfs", lambda: None)
    info = detect_system(tmp_path)
    assert info.gpu is None and info.free_bytes > 0 and info.os in ("linux", "windows", "macos")


def test_detect_system_nvidia_smi_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 9, "", "err"))
    monkeypatch.setattr(syscheck, "_query_amdgpu_sysfs", lambda: None)
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


GIB = 1024 ** 3


def test_parse_windows_adapters_picks_dedicated():
    entries = [
        {"DriverDesc": "Intel(R) UHD Graphics", "HardwareInformation.qwMemorySize": 128 * 1024 ** 2,
         "MatchingDeviceId": "PCI\\VEN_8086&DEV_9A49"},
        {"DriverDesc": "AMD Radeon RX 7600", "HardwareInformation.qwMemorySize": 8 * GIB,
         "MatchingDeviceId": "PCI\\VEN_1002&DEV_7480"},
    ]
    assert parse_windows_adapters(entries) == GpuInfo("AMD Radeon RX 7600", 8192, "amd")


def test_integrated_only_is_none():
    entries = [{"DriverDesc": "Intel(R) Iris(R) Xe Graphics", "HardwareInformation.qwMemorySize": 128 * 1024 ** 2,
                "MatchingDeviceId": "PCI\\VEN_8086&DEV_9A49"}]
    assert parse_windows_adapters(entries) is None


def test_memorysize_fallback_bytes():
    entries = [{"DriverDesc": "Some Card", "HardwareInformation.MemorySize": (4 * GIB - 1).to_bytes(4, "little")}]
    assert parse_windows_adapters(entries).vram_mb == 4095


def test_memorysize_fallback_int_and_vendor_from_name():
    entries = [{"DriverDesc": "NVIDIA GeForce GTX 1650", "HardwareInformation.MemorySize": 4 * GIB - 1}]
    assert parse_windows_adapters(entries) == GpuInfo("NVIDIA GeForce GTX 1650", 4095, "nvidia")
    assert parse_windows_adapters([{"DriverDesc": "Weird", "HardwareInformation.qwMemorySize": 4 * GIB}]).vendor == "other"
    assert parse_windows_adapters([]) is None


def test_parse_amdgpu_sysfs():
    cards = {"card0": 256 * 1024 ** 2, "card1": 8 * GIB}
    assert parse_amdgpu_sysfs(cards) == GpuInfo("AMD graphics card", 8192, "amd")
    assert parse_amdgpu_sysfs({"card0": 256 * 1024 ** 2}) is None
    assert parse_amdgpu_sysfs({}) is None


def test_is_nvidia():
    assert is_nvidia(SystemInfo("linux", GpuInfo("x", 6000), 0))
    assert not is_nvidia(SystemInfo("linux", GpuInfo("x", 6000, "amd"), 0))
    assert not is_nvidia(SystemInfo("linux", None, 0))


def test_choose_whisper_model_amd_never_large():
    assert choose_whisper_model(SystemInfo("linux", GpuInfo("x", 16000, "amd"), 0)) == "large-v3-turbo"


def test_detect_system_falls_back_to_amdgpu_sysfs(monkeypatch, tmp_path):
    monkeypatch.setattr(syscheck, "current_os", lambda: "linux")
    monkeypatch.setattr(syscheck, "_query_nvidia", lambda: None)
    monkeypatch.setattr(syscheck, "_query_amdgpu_sysfs", lambda: GpuInfo("AMD graphics card", 8192, "amd"))
    assert detect_system(tmp_path).gpu == GpuInfo("AMD graphics card", 8192, "amd")
