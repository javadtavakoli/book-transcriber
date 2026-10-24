from booktranscriber.gpu import gpu_env, nvidia_lib_dirs


def test_nvidia_lib_dirs_linux(tmp_path):
    (tmp_path / "cublas" / "lib").mkdir(parents=True)
    (tmp_path / "cudnn" / "lib").mkdir(parents=True)
    assert nvidia_lib_dirs([str(tmp_path)], windows=False) == [
        str(tmp_path / "cudnn" / "lib"), str(tmp_path / "cublas" / "lib")]


def test_nvidia_lib_dirs_windows_uses_bin(tmp_path):
    (tmp_path / "cublas" / "bin").mkdir(parents=True)
    (tmp_path / "cudnn" / "lib").mkdir(parents=True)
    assert nvidia_lib_dirs([str(tmp_path)], windows=True) == [str(tmp_path / "cublas" / "bin")]


def test_gpu_env_linux_prepends():
    env = gpu_env(["/a", "/b"], {"LD_LIBRARY_PATH": "/old"}, windows=False)
    assert env["LD_LIBRARY_PATH"] == "/a:/b:/old"


def test_gpu_env_linux_no_existing():
    assert gpu_env(["/a"], {}, windows=False)["LD_LIBRARY_PATH"] == "/a"


def test_gpu_env_windows():
    env = gpu_env(["C:\\a"], {"PATH": "C:\\w"}, windows=True)
    assert env["PATH"] == "C:\\a;C:\\w" and env["BT_DLL_DIRS"] == "C:\\a"


def test_gpu_env_does_not_mutate_base():
    base = {"LD_LIBRARY_PATH": "/old"}
    gpu_env(["/a"], base, windows=False)
    assert base == {"LD_LIBRARY_PATH": "/old"}


def test_default_lib_dirs_does_not_create_app_folders(tmp_path, monkeypatch):
    from booktranscriber.gpu import default_lib_dirs
    monkeypatch.setenv("BT_DATA_DIR", str(tmp_path / "never-made"))
    default_lib_dirs()
    assert not (tmp_path / "never-made").exists()


def test_default_lib_dirs_without_platformdirs(monkeypatch):
    import builtins

    from booktranscriber.gpu import default_lib_dirs
    monkeypatch.delenv("BT_DATA_DIR")
    real_import = builtins.__import__

    def no_platformdirs(name, *a, **k):
        if name == "platformdirs":
            raise ImportError(name)
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_platformdirs)
    assert isinstance(default_lib_dirs(), list)     # CLI keeps working on an old venv
