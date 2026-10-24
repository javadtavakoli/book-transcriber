"""Where first-run setup downloads things from: CUDA wheels on PyPI, Whisper models on Hugging Face."""
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import httpx

# The versions the CLI's requirements.txt installs today.
GPU_WHEELS = {
    "nvidia-cublas-cu12": "12.9.2.10",
    "nvidia-cudnn-cu12": "9.24.0.43",
    "nvidia-cuda-nvrtc-cu12": "12.9.86",
}


@dataclass
class RemoteFile:
    url: str
    size: int
    sha256: str | None
    dest: Path


def pick_wheel(pypi_json: dict, os_name: str) -> tuple[str, int, str, str]:
    """(url, size, sha256, filename) of the x86-64 wheel for this OS."""
    def fits(name: str) -> bool:
        if os_name == "linux":
            return "manylinux" in name and name.endswith("x86_64.whl")
        return os_name == "windows" and name.endswith("win_amd64.whl")
    for u in pypi_json.get("urls", []):
        if u.get("packagetype") == "bdist_wheel" and fits(u["filename"]):
            return u["url"], u["size"], u["digests"]["sha256"], u["filename"]
    raise LookupError(f"no wheel for {os_name}")


def gpu_wheel_files(os_name: str, gpu_dir: Path, client: httpx.Client) -> list[RemoteFile]:
    files = []
    for name, version in GPU_WHEELS.items():
        r = client.get(f"https://pypi.org/pypi/{name}/{version}/json")
        r.raise_for_status()
        url, size, sha, filename = pick_wheel(r.json(), os_name)
        files.append(RemoteFile(url, size, sha, Path(gpu_dir) / "wheels" / filename))
    return files


def extract_nvidia_libs(wheel: Path, gpu_dir: Path, windows: bool, cancel=None) -> list[Path]:
    """Unpack only nvidia/<pkg>/lib/* (or bin/* on Windows) into gpu_dir, then delete the wheel."""
    from .downloader import DownloadCancelled
    sub = "bin" if windows else "lib"
    out = []
    with zipfile.ZipFile(wheel) as z:
        for info in z.infolist():
            p = PurePosixPath(info.filename)
            if (info.is_dir() or len(p.parts) != 4 or p.parts[0] != "nvidia" or p.parts[2] != sub
                    or ".." in p.parts):
                continue
            target = Path(gpu_dir).joinpath(*p.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                while block := src.read(1024 * 1024):
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled()
                    dst.write(block)
            out.append(target)
    Path(wheel).unlink()
    return out


def model_files(repo_id: str, dest_dir: Path) -> list[RemoteFile]:
    from huggingface_hub import HfApi, hf_hub_url
    info = HfApi().model_info(repo_id, files_metadata=True)
    return [RemoteFile(hf_hub_url(repo_id, s.rfilename, revision=info.sha), s.size or 0,
                       s.lfs.sha256 if s.lfs else None, Path(dest_dir) / s.rfilename)
            for s in info.siblings if not s.rfilename.startswith(".")]
