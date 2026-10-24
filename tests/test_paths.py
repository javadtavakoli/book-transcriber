from booktranscriber import paths


def test_data_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("BT_DATA_DIR", str(tmp_path / "d"))
    assert paths.models_dir() == tmp_path / "d" / "models"
    assert paths.models_dir().is_dir()


def test_files_live_in_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BT_DATA_DIR", str(tmp_path / "d"))
    assert paths.settings_file() == tmp_path / "d" / "settings.json"
    assert paths.recents_file() == tmp_path / "d" / "recents.json"
    assert paths.gpu_dir().parent == paths.namelists_dir().parent == paths.logs_dir().parent == tmp_path / "d"


def _fake_platform(tmp_path, monkeypatch):
    monkeypatch.delenv("BT_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "_platform_data_dir", lambda name: tmp_path / name)
    return tmp_path / paths.OLD_APP_NAME, tmp_path / paths.APP_NAME


def test_migrate_renames_old_folder(tmp_path, monkeypatch):
    old, new = _fake_platform(tmp_path, monkeypatch)
    old.mkdir()
    (old / "settings.json").write_text("{}")
    assert paths.migrate_old_data_dir() is True
    assert (new / "settings.json").is_file()
    assert not old.exists()


def test_migrate_skips_when_new_exists(tmp_path, monkeypatch):
    old, new = _fake_platform(tmp_path, monkeypatch)
    old.mkdir()
    new.mkdir()
    (old / "a").write_text("1")
    (new / "b").write_text("2")
    assert paths.migrate_old_data_dir() is False
    assert (old / "a").is_file() and (new / "b").is_file()


def test_migrate_skips_with_bt_data_dir(tmp_path, monkeypatch):
    old, new = _fake_platform(tmp_path, monkeypatch)
    old.mkdir()
    monkeypatch.setenv("BT_DATA_DIR", str(tmp_path / "x"))
    assert paths.migrate_old_data_dir() is False
    assert old.is_dir() and not new.exists()


def test_asset_exists():
    assert paths.asset("icon.ico").is_file()
    assert paths.asset("icon.png").is_file()
