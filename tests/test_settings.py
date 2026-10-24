import json

from booktranscriber.settings import Settings, load_settings, save_settings


def test_missing_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.json") == Settings()


def test_corrupt_file_gives_defaults(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json", "utf-8")
    assert load_settings(p) == Settings()


def test_roundtrip_and_unknown_keys(tmp_path):
    p = tmp_path / "s.json"
    save_settings(Settings(ui_language="fa", setup_done=True), p)
    d = json.loads(p.read_text("utf-8"))
    d["future_key"] = 1
    p.write_text(json.dumps(d), "utf-8")
    assert load_settings(p) == Settings(ui_language="fa", setup_done=True)


def test_save_is_atomic(tmp_path):
    p = tmp_path / "s.json"
    save_settings(Settings(), p)
    assert [f.name for f in tmp_path.iterdir()] == ["s.json"]
