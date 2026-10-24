import re

import pytest

from booktranscriber.llm_catalog import MODELS, RUNTIME_ASSETS, choose_backend, choose_llm
from booktranscriber.syscheck import GpuInfo, SystemInfo, choose_whisper_model

GB = 1_000_000_000


def test_runtime_assets_cover_every_os_backend():
    wanted = {("linux", "vulkan"), ("linux", "cpu"), ("windows", "vulkan"), ("windows", "cpu"), ("macos", "metal")}
    assert wanted <= set(RUNTIME_ASSETS)
    assert RUNTIME_ASSETS[("macos", "cpu")] == RUNTIME_ASSETS[("macos", "metal")]
    for asset in RUNTIME_ASSETS.values():
        assert re.fullmatch(r"[0-9a-f]{64}", asset.sha256)
        assert asset.size > 0


def test_models_have_pinned_hashes():
    for key, m in MODELS.items():
        assert m.key == key
        assert re.fullmatch(r"[0-9a-f]{64}", m.sha256)
        assert re.fullmatch(r"[0-9a-f]{40}", m.revision)


@pytest.mark.parametrize("os_name,gpu", [("macos", None), ("linux", None), ("linux", GpuInfo("x", 8000)),
                                         ("windows", None), ("windows", GpuInfo("x", 8000))])
def test_choose_backend(os_name, gpu):
    assert choose_backend(SystemInfo(os_name, gpu, 0)) == ("metal" if os_name == "macos" else "vulkan")


@pytest.mark.parametrize("info,expected", [
    (SystemInfo("linux", GpuInfo("RTX 4050", 6141), 0), ("gemma-4-e4b", True)),
    (SystemInfo("windows", GpuInfo("big", 12288), 0), ("gemma-4-12b", True)),
    (SystemInfo("macos", None, 0, 32 * GB), ("gemma-4-12b", True)),
    (SystemInfo("macos", None, 0, 16 * GB), ("gemma-4-e4b", True)),
    (SystemInfo("macos", None, 0, 8 * GB), ("gemma-4-e4b", False)),
    (SystemInfo("linux", None, 0, 64 * GB), ("gemma-4-e4b", False)),
])
def test_choose_llm_tiers(info, expected):
    assert choose_llm(info) == expected


def test_choose_llm_amd_8gb_gets_e4b_recommended():
    assert choose_llm(SystemInfo("windows", GpuInfo("AMD Radeon RX 7600", 8192, "amd"), 0)) == ("gemma-4-e4b", True)


def test_nvidia_unchanged():
    assert choose_llm(SystemInfo("linux", GpuInfo("RTX 4050", 6141), 0)) == ("gemma-4-e4b", True)
    assert choose_whisper_model(SystemInfo("linux", GpuInfo("RTX 4050", 6141), 0)) == "large-v3"
