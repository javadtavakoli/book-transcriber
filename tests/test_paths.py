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
