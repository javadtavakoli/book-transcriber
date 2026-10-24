"""Where the local AI helper's files come from and how the runtime archive is unpacked safely."""
import os
import tarfile
import threading
import zipfile
from pathlib import Path, PurePosixPath

from . import paths
from .llm_catalog import LLAMA_BUILD, MODELS, RELEASE_URL, RUNTIME_ASSETS
from .setup_sources import RemoteFile

DONE_MARKER = ".done"


def _llm_dir() -> Path:
    return paths.data_dir() / "llm"


def runtime_dir(backend: str) -> Path:
    return _llm_dir() / f"{LLAMA_BUILD}-{backend}"


def _find_server(root: Path) -> Path | None:
    """The server binary in a fully extracted runtime (one with its .done marker)."""
    if not (root / DONE_MARKER).is_file():
        return None
    for name in ("llama-server", "llama-server.exe"):
        for p in sorted(root.rglob(name)):
            if p.is_file():
                return p
    return None


def server_binary(backend: str) -> Path | None:
    found = _find_server(runtime_dir(backend))
    if found is None and backend == "cpu":
        # macOS has no separate CPU build: it runs the Metal one with -ngl 0.
        found = _find_server(runtime_dir("metal"))
    return found


def _runtime_file(os_name: str, backend: str) -> RemoteFile:
    a = RUNTIME_ASSETS[(os_name, backend)]
    return RemoteFile(RELEASE_URL + a.filename, a.size, a.sha256, _llm_dir() / "archives" / a.filename)


def runtime_files(os_name: str, backend: str) -> list[tuple[str, RemoteFile]]:
    """(backend, archive) pairs to download: the GPU build plus the CPU fallback; macOS has just Metal."""
    if os_name == "macos":
        return [("metal", _runtime_file("macos", "metal"))]
    return [(backend, _runtime_file(os_name, backend)), ("cpu", _runtime_file(os_name, "cpu"))]


def model_file(key: str) -> RemoteFile:
    from huggingface_hub import hf_hub_url
    m = MODELS[key]
    return RemoteFile(hf_hub_url(m.repo, m.filename, revision=m.revision), m.size, m.sha256,
                      _llm_dir() / "models" / m.filename)


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        from .downloader import DownloadCancelled
        raise DownloadCancelled()


def _extract_tar(archive: Path, dest: Path, cancel) -> None:
    with tarfile.open(archive, "r:gz") as t:
        for member in t:
            _check(cancel)
            try:
                t.extract(member, dest, filter="data")  # real I/O errors propagate
            except tarfile.FilterError:
                continue


def _extract_zip(archive: Path, dest: Path, cancel) -> None:
    root = dest.resolve()
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            _check(cancel)
            name = info.filename.replace("\\", "/")
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or (p.parts and ":" in p.parts[0]):
                continue
            target = (dest / Path(*p.parts)).resolve() if p.parts else root
            if target != root and root not in target.parents:
                continue
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as s, open(target, "wb") as d:
                while block := s.read(1024 * 1024):
                    _check(cancel)
                    d.write(block)


def extract_archive(archive: Path, dest: Path, cancel: threading.Event | None = None) -> None:
    """Unpack a .tar.gz or .zip into dest, skipping anything that would land outside it."""
    archive, dest = Path(archive), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        _extract_zip(archive, dest, cancel)
    else:
        _extract_tar(archive, dest, cancel)
    _check(cancel)
    if os.name == "posix":
        for p in dest.rglob("llama-server"):
            if p.is_file() and not p.is_symlink():
                p.chmod(p.stat().st_mode | 0o111)
    if not any(p.is_file() for n in ("llama-server", "llama-server.exe") for p in dest.rglob(n)):
        raise RuntimeError(f"{archive.name} contains no llama-server")
    (dest / DONE_MARKER).write_text("ok")
    archive.unlink()
