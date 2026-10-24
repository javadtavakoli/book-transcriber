"""What this computer has: an NVIDIA GPU (and how much memory), free disk, models already present."""
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

WHISPER_REPOS = {
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}
MIN_VRAM_LARGE_MB = 4000


@dataclass
class GpuInfo:
    name: str
    vram_mb: int


@dataclass
class SystemInfo:
    os: str
    gpu: GpuInfo | None
    free_bytes: int


def current_os() -> str:
    if sys.platform == "win32":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def parse_nvidia_smi(output: str) -> GpuInfo | None:
    for line in output.splitlines():
        if line.strip():
            name, _, mem = line.rpartition(",")
            try:
                return GpuInfo(name.strip(), int(mem.strip())) if name.strip() else None
            except ValueError:
                return None
    return None


def _query_nvidia() -> GpuInfo | None:
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5, **kw)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_nvidia_smi(r.stdout) if r.returncode == 0 else None


def detect_system(target_dir: Path) -> SystemInfo:
    os_name = current_os()
    gpu = None if os_name == "macos" else _query_nvidia()
    return SystemInfo(os_name, gpu, shutil.disk_usage(target_dir).free)


def choose_whisper_model(info: SystemInfo) -> str:
    return "large-v3" if info.gpu and info.gpu.vram_mb >= MIN_VRAM_LARGE_MB else "large-v3-turbo"


def find_existing_model(search_dirs: list[Path], model: str) -> Path | None:
    """A model already downloaded by the CLI (Hugging Face cache layout) or unpacked as a plain folder."""
    org, name = WHISPER_REPOS[model].split("/")
    for d in map(Path, search_dirs):
        for snap in sorted((d / f"models--{org}--{name}" / "snapshots").glob("*")):
            if (snap / "model.bin").is_file():
                return snap
        if (d / name / "model.bin").is_file():
            return d / name
    return None


def source_checkout_dir() -> Path | None:
    root = Path(__file__).resolve().parent.parent
    return root if (root / "transcribe.py").is_file() else None
