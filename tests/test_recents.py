from booktranscriber.recents import RecentItem, add_recent, load_recents


def test_dedupe_limit_and_missing(tmp_path):
    raws = [tmp_path / f"{i}.txt" for i in range(3)]
    for r in raws:
        r.write_text("x")
    f = tmp_path / "recents.json"
    for r in raws + [raws[0]]:
        add_recent(f, RecentItem("a.m4a", str(r), None, "2026-10-24T10:00:00"), limit=2)
    assert [i.raw_path for i in load_recents(f)] == [str(raws[0]), str(raws[2])]
    raws[0].unlink()
    assert [i.raw_path for i in load_recents(f)] == [str(raws[2])]


def test_update_corrected_path_replaces_entry(tmp_path):
    raw = tmp_path / "a - متن خام.txt"
    raw.write_text("x", "utf-8")
    f = tmp_path / "recents.json"
    add_recent(f, RecentItem("a.m4a", str(raw), None, "t1"))
    add_recent(f, RecentItem("a.m4a", str(raw), "c.txt", "t1"))
    assert [(i.raw_path, i.corrected_path) for i in load_recents(f)] == [(str(raw), "c.txt")]


def test_corrupt_recents(tmp_path):
    f = tmp_path / "recents.json"
    f.write_text("[{bad", "utf-8")
    assert load_recents(f) == []
