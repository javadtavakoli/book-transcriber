"""What this computer has: a graphics card (and how much memory), free disk, models already present."""
import ctypes
import os
import re
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
INTEGRATED_MAX_MB = 2048  # at or below this a graphics chip shares system memory; treat it as no graphics card
WINDOWS_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
PCI_VENDORS = {"10DE": "nvidia", "1002": "amd", "8086": "intel"}


@dataclass
class GpuInfo:
    name: str
    vram_mb: int
    vendor: str = "nvidia"  # "nvidia" | "amd" | "intel" | "other"


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


def is_nvidia(info: SystemInfo) -> bool:
    return info.gpu is not None and info.gpu.vendor == "nvidia"


def _vendor_of(name: str, device_id: str = "") -> str:
    m = re.search(r"VEN_([0-9A-F]{4})", device_id.upper())
    if m and m.group(1) in PCI_VENDORS:
        return PCI_VENDORS[m.group(1)]
    low = name.lower()
    if "nvidia" in low or "geforce" in low:
        return "nvidia"
    if "amd" in low or "radeon" in low:
        return "amd"
    if "intel" in low:
        return "intel"
    return "other"


def _adapter_mb(entry: dict) -> int:
    mem = entry.get("HardwareInformation.qwMemorySize")
    if mem is None:
        mem = entry.get("HardwareInformation.MemorySize")
    if isinstance(mem, (bytes, bytearray)):
        mem = int.from_bytes(mem, "little")
    return int(mem) // (1024 * 1024) if isinstance(mem, int) else 0


def parse_windows_adapters(entries: list[dict]) -> GpuInfo | None:
    """The adapter with the most dedicated memory; integrated chips (shared memory) count as none."""
    best = max(entries, key=_adapter_mb, default=None)
    if best is None or _adapter_mb(best) <= INTEGRATED_MAX_MB or not best.get("DriverDesc"):
        return None
    name = str(best["DriverDesc"])
    return GpuInfo(name, _adapter_mb(best), _vendor_of(name, str(best.get("MatchingDeviceId", ""))))


def parse_amdgpu_sysfs(cards: dict[str, int]) -> GpuInfo | None:
    """cards maps a card name to its mem_info_vram_total in bytes."""
    mb = max(cards.values(), default=0) // (1024 * 1024)
    return GpuInfo("AMD graphics card", mb, "amd") if mb > INTEGRATED_MAX_MB else None


def _query_windows_adapters() -> GpuInfo | None:
    if sys.platform != "win32":
        return None
    import winreg
    entries = []
    for i in range(32):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{WINDOWS_DISPLAY_CLASS}\\{i:04d}") as key:
                entry = {}
                for field in ("DriverDesc", "HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize",
                              "MatchingDeviceId"):
                    try:
                        entry[field] = winreg.QueryValueEx(key, field)[0]
                    except OSError:
                        pass
                entries.append(entry)
        except OSError:
            continue
    return parse_windows_adapters(entries)


def _query_amdgpu_sysfs() -> GpuInfo | None:
    cards = {}
    for f in Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"):
        try:
            cards[f.parent.parent.name] = int(f.read_text().strip())
        except (OSError, ValueError):
            pass
    return parse_amdgpu_sysfs(cards)


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
    gpu = None
    if os_name != "macos":
        gpu = _query_nvidia()
        if gpu is None and os_name == "windows":
            gpu = _query_windows_adapters()
        elif gpu is None and os_name == "linux":
            gpu = _query_amdgpu_sysfs()
    return SystemInfo(os_name, gpu, shutil.disk_usage(target_dir).free, total_ram_bytes())


def choose_whisper_model(info: SystemInfo) -> str:
    return "large-v3" if is_nvidia(info) and info.gpu.vram_mb >= MIN_VRAM_LARGE_MB else "large-v3-turbo"


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
