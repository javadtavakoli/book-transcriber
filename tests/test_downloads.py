import json
import shutil
import threading
from collections import namedtuple
from pathlib import Path

import pytest

from booktranscriber import downloads, paths
from booktranscriber.downloads import MoveCancelled, MoveError, MoveProgress
from booktranscriber.settings import Settings, load_settings, save_settings

Usage = namedtuple("Usage", "total used free")
MIB = 1024 * 1024


def _write_settings(**values):
    paths.settings_file().write_text(json.dumps(values), "utf-8")


def test_default_downloads_is_app_folder():
    assert paths.downloads_dir_path() == paths.data_dir_path()
    assert paths.models_dir() == paths.data_dir_path() / "models"
    assert paths.llm_dir() == paths.data_dir_path() / "llm"


def test_downloads_dir_from_settings(tmp_path):
    root = tmp_path / "big"
    _write_settings(downloads_dir=str(root))
    assert paths.downloads_dir() == root and root.is_dir()
    assert paths.models_dir().parent == root and paths.llm_dir().parent == root
    assert paths.gpu_dir().parent == root
    assert paths.settings_file().parent == paths.data_dir_path() != root


def test_relative_downloads_dir_falls_back():
    _write_settings(downloads_dir="relative/folder")
    assert paths.downloads_dir_path() == paths.data_dir_path()


def test_broken_settings_falls_back():
    paths.settings_file().write_text("{not json", "utf-8")
    assert paths.downloads_dir_path() == paths.data_dir_path()
    paths.settings_file().write_text('["a list"]', "utf-8")
    assert paths.downloads_dir_path() == paths.data_dir_path()


def test_pid_file_stays_in_app_folder(tmp_path):
    from booktranscriber import llm_server
    _write_settings(downloads_dir=str(tmp_path / "big"))
    assert llm_server._pid_file() == paths.data_dir_path() / "llm" / "server.pid"


def test_choose_target_empty_folder_used_directly(tmp_path):
    (tmp_path / "e").mkdir()
    assert downloads.choose_target(tmp_path / "e") == tmp_path / "e"


def test_choose_target_nonempty_gets_subfolder(tmp_path):
    (tmp_path / "pics").mkdir()
    (tmp_path / "pics" / "photo.jpg").write_bytes(b"x")
    assert downloads.choose_target(tmp_path / "pics") == tmp_path / "pics" / "WritingParrot"


def test_choose_target_ours_reused(tmp_path):
    b = tmp_path / "b"
    b.mkdir()
    (b / ".writingparrot").write_text("")
    (b / "other.txt").write_text("")
    assert downloads.choose_target(b) == b


def test_choose_target_users_models_folder_not_ours(tmp_path):
    a = tmp_path / "a"
    (a / "models").mkdir(parents=True)
    assert downloads.choose_target(a) == a / "WritingParrot"


def test_choose_target_app_folder_returned():
    app = paths.data_dir()
    paths.models_dir()
    paths.settings_file().write_text("{}")
    assert downloads.choose_target(app) == app


def test_choose_target_drive_root_always_gets_subfolder(monkeypatch):
    # A whole drive is never ours, even an empty one: deleting "its" downloads would mean the drive's top level.
    monkeypatch.setattr(Path, "iterdir", lambda self: iter(()))
    root = Path(Path.cwd().anchor)
    assert downloads.choose_target(root) == root / "WritingParrot"


def test_delete_downloads_removes_only_the_download_files(tmp_path):
    root = paths.data_dir()
    files = [root / "models" / "m" / "model.bin", root / "gpu" / "cudnn.dll", root / "llm" / "helper.gguf"]
    for f in files:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    pid = root / "llm" / "server.pid"
    pid.write_text('{"pid": 1}')
    paths.settings_file().write_text("{}")
    (root / "namelists").mkdir()
    (root / "namelists" / "mine.json").write_text("[]")
    downloads.delete_downloads(root)
    assert not any(f.exists() for f in files)
    assert not (root / "models").exists() and not (root / "gpu").exists()
    assert pid.exists() and paths.settings_file().exists() and (root / "namelists" / "mine.json").exists()


def test_writable(tmp_path):
    assert downloads.writable(tmp_path / "new" / "deep")
    assert list((tmp_path / "new" / "deep").iterdir()) == []


def test_suggest_default_app_drive_has_room(monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10**12, 0, 10**10))
    assert downloads.suggest_default(10**9, drives=[]) == (paths.data_dir_path(), None)


def test_suggest_default_c_full_picks_other_fixed_drive(monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10**12, 0, 10**6))
    drives = [(Path(paths.data_dir_path().anchor), 10**11, False),     # the full system drive itself
              (Path("/mnt/usb"), 10**11, True),
              (Path("/mnt/small"), 10**7, False),
              (Path("/mnt/d"), 10**11, False),
              (Path("/mnt/e"), 10**11, False)]
    assert downloads.suggest_default(10**9, drives) == (Path("/mnt/d") / "WritingParrot", "c_full")


def test_suggest_default_nothing_has_room(monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10**12, 0, 10**6))
    drives = [(Path("/mnt/usb"), 10**11, True), (Path("/mnt/small"), 10**7, False)]
    assert downloads.suggest_default(10**9, drives) == (paths.data_dir_path(), None)


def _fake_downloads():
    """models/x/model.bin (3 MiB) and llm/models/a.gguf (2 MiB) in the current downloads root."""
    root = paths.downloads_dir()
    (root / "models" / "x").mkdir(parents=True)
    (root / "models" / "x" / "model.bin").write_bytes(b"m" * 3 * MIB)
    (root / "llm" / "models").mkdir(parents=True)
    (root / "llm" / "models" / "a.gguf").write_bytes(b"g" * 2 * MIB)
    return root


def _settings():
    s = Settings(setup_done=True)
    save_settings(s, paths.settings_file())
    return s


def test_move_copies_verifies_switches_deletes(tmp_path, registry_calls):
    old = _fake_downloads()
    s = _settings()
    new = tmp_path / "new"
    seen = []
    downloads.move_downloads(s, new, seen.append, threading.Event())
    assert (new / "models" / "x" / "model.bin").stat().st_size == 3 * MIB
    assert (new / "llm" / "models" / "a.gguf").read_bytes() == b"g" * 2 * MIB
    assert not (old / "models").exists() and not (old / "llm").exists()
    assert s.downloads_dir == str(new)
    assert load_settings(paths.settings_file()).downloads_dir == str(new)
    assert paths.downloads_dir_path() == new
    assert (new / ".writingparrot").is_file()
    assert registry_calls == [new]
    assert seen[-1] == MoveProgress(5 * MIB, 5 * MIB)
    assert [p.done for p in seen] == sorted(p.done for p in seen)


def test_move_rewrites_model_paths(tmp_path):
    old = _fake_downloads()
    s = _settings()
    s.whisper_model_path = str(old / "models" / "x")
    s.llm_model_path = str(Path("/checkout/models/a.gguf"))
    new = tmp_path / "new"
    downloads.move_downloads(s, new, lambda p: None, threading.Event())
    assert s.whisper_model_path == str(new / "models" / "x")
    assert s.llm_model_path == str(Path("/checkout/models/a.gguf"))
    assert load_settings(paths.settings_file()).whisper_model_path == str(new / "models" / "x")


def _assert_untouched(old, new, before):
    assert (old / "models" / "x" / "model.bin").stat().st_size == 3 * MIB
    assert (old / "llm" / "models" / "a.gguf").stat().st_size == 2 * MIB
    assert not (new / "models").exists() and not (new / "llm").exists()
    assert load_settings(paths.settings_file()) == before
    assert paths.downloads_dir_path() == old


def test_move_cancel_keeps_old(tmp_path, registry_calls):
    old = _fake_downloads()
    s = _settings()
    before = load_settings(paths.settings_file())
    cancel = threading.Event()
    new = tmp_path / "new"
    with pytest.raises(MoveCancelled):
        downloads.move_downloads(s, new, lambda p: cancel.set(), cancel)
    _assert_untouched(old, new, before)
    assert s == before and registry_calls == []


def test_move_copy_error_keeps_old(tmp_path, monkeypatch, registry_calls):
    old = _fake_downloads()
    s = _settings()
    before = load_settings(paths.settings_file())
    real, calls = downloads._write_chunk, []

    def flaky(f, data):
        calls.append(1)
        if len(calls) == 3:
            raise OSError(28, "No space")
        real(f, data)
    monkeypatch.setattr(downloads, "_write_chunk", flaky)
    new = tmp_path / "new"
    with pytest.raises(MoveError) as e:
        downloads.move_downloads(s, new, lambda p: None, threading.Event())
    assert e.value.kind == "copy"
    _assert_untouched(old, new, before)
    assert s == before and registry_calls == []


def test_move_persian_path(tmp_path):
    _fake_downloads()
    s = _settings()
    new = tmp_path / "کتاب ها" / "Writing Parrot"
    downloads.move_downloads(s, new, lambda p: None, threading.Event())
    assert (new / "models" / "x" / "model.bin").is_file()
    assert load_settings(paths.settings_file()).downloads_dir == str(new)


def test_move_space_check(tmp_path, monkeypatch):
    old = _fake_downloads()
    s = _settings()
    before = load_settings(paths.settings_file())
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10**12, 0, 1000))
    new = tmp_path / "new"
    with pytest.raises(MoveError) as e:
        downloads.move_downloads(s, new, lambda p: None, threading.Event())
    assert e.value.kind == "space" and e.value.free == 1000
    assert e.value.needed >= 5 * MIB
    _assert_untouched(old, new, before)


def test_move_leaves_pid_file_in_app_folder(tmp_path):
    old = _fake_downloads()
    pid = paths.data_dir() / "llm" / "server.pid"
    pid.write_text('{"pid": 1}')
    (old / "models" / "notes.txt").write_text("mine")
    s = _settings()
    new = tmp_path / "new"
    downloads.move_downloads(s, new, lambda p: None, threading.Event())
    assert pid.read_text() == '{"pid": 1}' and not (new / "llm" / "server.pid").exists()
    assert not (old / "llm" / "models").exists()
    assert (new / "models" / "notes.txt").is_file()
    assert not (old / "models").exists()


def test_move_same_root_is_noop(registry_calls):
    old = _fake_downloads()
    s = _settings()
    downloads.move_downloads(s, old, lambda p: None, threading.Event())
    assert (old / "models" / "x" / "model.bin").is_file() and registry_calls == []


def test_move_nested_refused(tmp_path):
    old = _fake_downloads()
    s = _settings()
    with pytest.raises(MoveError) as e:
        downloads.move_downloads(s, old / "models" / "inner", lambda p: None, threading.Event())
    assert e.value.kind == "nested"
    assert not (old / "models" / "inner").exists()


def test_move_nested_refused_other_direction(tmp_path):
    outer = tmp_path / "r"
    _write_settings(downloads_dir=str(outer / "models" / "inner"))     # old root inside new/models
    old = _fake_downloads()
    s = _settings()
    s.downloads_dir = str(old)
    save_settings(s, paths.settings_file())
    with pytest.raises(MoveError) as e:
        downloads.move_downloads(s, outer, lambda p: None, threading.Event())
    assert e.value.kind == "nested"
    assert (old / "models" / "x" / "model.bin").stat().st_size == 3 * MIB


def test_move_refuses_existing_files_in_target(tmp_path, registry_calls):
    old = _fake_downloads()
    s = _settings()
    before = load_settings(paths.settings_file())
    new = tmp_path / "new"
    (new / "llm" / "models").mkdir(parents=True)
    (new / "llm" / "models" / "a.gguf").write_bytes(b"users own")
    with pytest.raises(MoveError) as e:
        downloads.move_downloads(s, new, lambda p: None, threading.Event())
    assert e.value.kind == "exists"
    assert (new / "llm" / "models" / "a.gguf").read_bytes() == b"users own"
    assert not (new / "models").exists()
    assert (old / "models" / "x" / "model.bin").stat().st_size == 3 * MIB
    assert load_settings(paths.settings_file()) == before and registry_calls == []


def test_move_target_unreadable_is_move_error(tmp_path, monkeypatch):
    _fake_downloads()
    s = _settings()

    def boom(p):
        raise PermissionError(13, "denied")
    monkeypatch.setattr(shutil, "disk_usage", boom)
    with pytest.raises(MoveError) as e:
        downloads.move_downloads(s, tmp_path / "new", lambda p: None, threading.Event())
    assert e.value.kind == "target"


def test_move_progress_exception_leaves_no_copy(tmp_path):
    old = _fake_downloads()
    s = _settings()
    before = load_settings(paths.settings_file())
    new = tmp_path / "new"

    def bad(p):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        downloads.move_downloads(s, new, bad, threading.Event())
    _assert_untouched(old, new, before)
