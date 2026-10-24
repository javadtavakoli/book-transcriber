"""What this computer has: an NVIDIA GPU (and how much memory), free disk, models already present."""
import ctypes
import os
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
    ram_bytes: int = 0


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


def total_ram_bytes() -> int:
    """Installed RAM in bytes; 0 if it cannot be determined."""
    try:
        if sys.platform == "win32":
            class _MemStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                            ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                            ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                            ("avail_ext", ctypes.c_ulonglong)]
            status = _MemStatus()
            status.length = ctypes.sizeof(_MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return int(status.total_phys)
        if sys.platform == "darwin":
            r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            return int(r.stdout.strip()) if r.returncode == 0 else 0
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return 0


def detect_system(target_dir: Path) -> SystemInfo:
    os_name = current_os()
    gpu = None if os_name == "macos" else _query_nvidia()
    return SystemInfo(os_name, gpu, shutil.disk_usage(target_dir).free, total_ram_bytes())


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
