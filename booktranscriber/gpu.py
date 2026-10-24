"""Locate the NVIDIA CUDA libraries shipped as pip wheels and expose them to a child process.

Nothing here runs at import time. Linux reads LD_LIBRARY_PATH only at process start,
so the libraries are injected into the environment of a *child* (the worker, or the
CLI's one-time re-exec) instead of the running process.
"""
import importlib.util
import os
import sys
from typing import Mapping

CUDA_PACKAGES = ("cudnn", "cublas", "cuda_nvrtc", "cuda_runtime")


def site_nvidia_roots() -> list[str]:
    spec = importlib.util.find_spec("nvidia")
    return list(spec.submodule_search_locations) if spec else []


def nvidia_lib_dirs(roots: list[str], windows: bool) -> list[str]:
    sub = "bin" if windows else "lib"   # wheels put DLLs in bin/, .so files in lib/
    return [os.path.join(r, pkg, sub) for r in roots for pkg in CUDA_PACKAGES
            if os.path.isdir(os.path.join(r, pkg, sub))]


def default_lib_dirs(include_site: bool = True) -> list[str]:
    """Libraries downloaded by the app's setup first, then any in the current venv."""
    from . import paths
    windows = sys.platform == "win32"
    try:
        app_roots = [str(paths.data_dir_path() / "gpu" / "nvidia")]
    except ImportError:     # CLI on a venv made before the desktop app existed
        app_roots = []
    return nvidia_lib_dirs(app_roots + (site_nvidia_roots() if include_site else []), windows)


def gpu_env(lib_dirs: list[str], base: Mapping[str, str], windows: bool) -> dict[str, str]:
    env = dict(base)
    if windows:
        env["PATH"] = ";".join(lib_dirs + ([base["PATH"]] if base.get("PATH") else []))
        env["BT_DLL_DIRS"] = ";".join(lib_dirs)
    else:
        cur = base.get("LD_LIBRARY_PATH")
        env["LD_LIBRARY_PATH"] = ":".join(lib_dirs + ([cur] if cur else []))
    return env


def register_dll_dirs_from_env() -> None:
    """Windows: make the DLL dirs passed in BT_DLL_DIRS loadable in this process."""
    if sys.platform != "win32":
        return
    for d in filter(None, os.environ.get("BT_DLL_DIRS", "").split(";")):
        if os.path.isdir(d):
            os.add_dll_directory(d)
