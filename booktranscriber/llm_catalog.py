"""What the local AI helper downloads: a pinned llama.cpp build, two Gemma models, and which one fits this computer."""
from dataclasses import dataclass

from booktranscriber.syscheck import SystemInfo

LLAMA_BUILD = "b11539"
RELEASE_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/"


@dataclass(frozen=True)
class Asset:
    filename: str
    size: int
    sha256: str


_MAC_METAL = Asset("llama-b11539-bin-macos-arm64.tar.gz", 12078910,
                   "449f111de594ff5dfec7ac27d5b1233dd8a10a3e37ac1ceab9ce7d39d436ad32")

# Keyed by (os, backend). The macOS build is Metal; it runs on the CPU with -ngl 0, so it serves both keys.
RUNTIME_ASSETS: dict[tuple[str, str], Asset] = {
    ("linux", "vulkan"): Asset("llama-b11539-bin-ubuntu-vulkan-x64.tar.gz", 31771698,
                               "c94e4cf093d38054e4b3384491b0948a659474a207149e65a12b9e5993498182"),
    ("linux", "cpu"): Asset("llama-b11539-bin-ubuntu-x64.tar.gz", 17809488,
                            "f2476a4337d2ab2efc4d845f40d362518b74442a4c9833a5e02d219f4c2086fb"),
    ("windows", "vulkan"): Asset("llama-b11539-bin-win-vulkan-x64.zip", 33464670,
                                 "6f668beec2d159bb4cbb3b4407522c48e868571a9baf939ddcde46a548965bd7"),
    ("windows", "cpu"): Asset("llama-b11539-bin-win-cpu-x64.zip", 19519169,
                              "9895735aeef579aa46c356047f1e095ee6fcfe5558bd6b37ae83a7b4397d898e"),
    ("macos", "metal"): _MAC_METAL,
    ("macos", "cpu"): _MAC_METAL,
}


@dataclass(frozen=True)
class LlmModel:
    key: str
    repo: str
    revision: str
    filename: str
    size: int
    sha256: str
    min_vram_mb: int      # NVIDIA/Vulkan GPU memory needed (MiB, as nvidia-smi reports it)
    min_mac_ram_mb: int   # unified memory needed on macOS (MB = 1 000 000 bytes)


# Largest first: choose_llm takes the first tier the machine meets.
MODELS: dict[str, LlmModel] = {
    "gemma-4-12b": LlmModel(
        "gemma-4-12b", "unsloth/gemma-4-12b-it-GGUF", "fc034cfff751157913579611efad8462ac1be606",
        "gemma-4-12b-it-IQ4_XS.gguf", 6375734080,
        "b0037d0e0de0290177045ca214b2a0fb1079d18bde57842b3ca32f5b0cd76774", 10000, 24000),
    "gemma-4-e4b": LlmModel(
        "gemma-4-e4b", "unsloth/gemma-4-E4B-it-GGUF", "bfc15c382204943c3a8fff0c750b94ae2364d7a3",
        "gemma-4-E4B-it-IQ4_XS.gguf", 4715416704,
        "0847f7300471e9a61abaeb46b45b3d61e393af8fa6d6aa70c563623773670dd9", 5000, 12000),
}


def choose_backend(info: SystemInfo) -> str:
    """Metal on macOS, Vulkan elsewhere. The CPU build is only a runtime fallback."""
    return "metal" if info.os == "macos" else "vulkan"


def _meets_tier(model: LlmModel, info: SystemInfo) -> bool:
    if info.os == "macos":
        return info.ram_bytes / 1_000_000 >= model.min_mac_ram_mb
    return info.gpu is not None and info.gpu.vram_mb >= model.min_vram_mb


def choose_llm(info: SystemInfo) -> tuple[str | None, bool]:
    """(model key, recommended). A machine under every tier still gets the small model, but unrecommended."""
    for model in MODELS.values():
        if _meets_tier(model, info):
            return model.key, True
    return "gemma-4-e4b", False
