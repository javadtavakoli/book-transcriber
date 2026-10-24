from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from booktranscriber import paths
from booktranscriber.fixexport import apply_answer, build_export_parts
from booktranscriber.gui.export_view import ExportView
from booktranscriber.gui.review_view import ReviewView
from booktranscriber.i18n import I18n
from booktranscriber.recents import RecentItem, add_recent, load_recents


@pytest.fixture
def raw_file(tmp_path):
    raw = tmp_path / "s12 - متن خام.txt"
    lines = [f"[0:00:{i:02d}] " + ("کلمه " * 80).strip() for i in range(30)]
    raw.write_text("\n".join(lines) + "\n", "utf-8")
    return raw


def test_export_parts_listed_and_copy(qtbot, raw_file):
    v = ExportView(I18n("en"))
    qtbot.addWidget(v)
    v.load(str(raw_file), ["هومر"], "fa")
    expected = build_export_parts(raw_file.read_text("utf-8").splitlines(), ["هومر"])
    assert len(v.parts) == len(expected) >= 2
    qtbot.mouseClick(v.copy_buttons[0], Qt.LeftButton)
    assert QGuiApplication.clipboard().text() == expected[0].text
    assert v.copy_buttons[0].text() == "Copied ✓"


def test_editing_names_rebuilds_parts(qtbot, raw_file):
    v = ExportView(I18n("en"))
    qtbot.addWidget(v)
    v.load(str(raw_file), [], "fa")
    v.names_edit.setPlainText("کافکا")
    assert "کافکا" in v.parts[0].text


def test_save_all_parts(qtbot, raw_file, tmp_path, monkeypatch):
    v = ExportView(I18n("en"))
    qtbot.addWidget(v)
    v.load(str(raw_file), [], "fa")
    out = tmp_path / "parts"
    out.mkdir()
    monkeypatch.setattr(v, "ask_folder", lambda: str(out))
    qtbot.mouseClick(v.save_all_button, Qt.LeftButton)
    files = sorted(p.name for p in out.iterdir())
    assert len(files) == len(v.parts) and files[0] == f"s12 - part 1 of {len(v.parts)}.txt"


def test_paste_back_messy_answer_goes_to_review(qtbot, raw_file):
    v = ExportView(I18n("en"))
    qtbot.addWidget(v)
    v.load(str(raw_file), [], "fa")
    fixed = ("کلمه " * 79).strip() + " کلمات"
    v.paste_edit.setPlainText(f"Here you go\n```\n[۱] {fixed}\n```")
    with qtbot.waitSignal(v.review_ready) as blocker:
        qtbot.mouseClick(v.check_button, Qt.LeftButton)
    fixes = blocker.args[0]
    assert fixes[0].reason == "fixed" and fixes[1].reason == "missing"


def test_paste_garbage_stays(qtbot, raw_file):
    v = ExportView(I18n("en"))
    qtbot.addWidget(v)
    v.load(str(raw_file), [], "fa")
    got = []
    v.review_ready.connect(got.append)
    v.paste_edit.setPlainText("hello")
    qtbot.mouseClick(v.check_button, Qt.LeftButton)
    assert got == [] and not v.nothing_label.isHidden()


def review_with(qtbot, tmp_path, lang="en"):
    lines = ["[0:00:01] تعغیب حومر", "[0:00:03] کراسنا هورکای", "[0:00:05] خب"]
    raw = tmp_path / "a - متن خام.txt"
    raw.write_text("\n".join(lines) + "\n", "utf-8")
    fixes = apply_answer(lines, {1: "تعقیب هومر", 2: "کراسناهورکای", 3: "خب"})
    v = ReviewView(I18n(lang))
    qtbot.addWidget(v)
    v.load(str(raw), lines, fixes, "fa")
    return v, raw


def test_review_save_respects_unticked(qtbot, tmp_path):
    v, raw = review_with(qtbot, tmp_path)
    v.set_use_fix(2, False)
    v.save()
    assert (tmp_path / "a - متن اصلاح‌شده.txt").read_text("utf-8") == \
        "[0:00:01] تعقیب هومر\n[0:00:03] کراسنا هورکای\n[0:00:05] خب\n"
    assert "a - متن اصلاح‌شده.txt" in v.saved_label.text()


def test_review_save_updates_recents(qtbot, tmp_path):
    lines_raw = tmp_path / "a - متن خام.txt"
    lines_raw.write_text("x\n", "utf-8")
    add_recent(paths.recents_file(), RecentItem(str(tmp_path / "a.m4a"), str(lines_raw), None, "t"))
    v, raw = review_with(qtbot, tmp_path)
    v.save()
    item = load_recents(paths.recents_file())[0]
    assert item.corrected_path == str(tmp_path / "a - متن اصلاح‌شده.txt") and item.audio == str(tmp_path / "a.m4a")


def test_review_too_different_unticked(qtbot, tmp_path):
    lines = ["[0:00:01] یک دو سه چهار پنج"]
    raw = tmp_path / "b - متن خام.txt"
    raw.write_text(lines[0] + "\n", "utf-8")
    fixes = apply_answer(lines, {1: "در این جلسه درباره موضوعات بسیار متفاوتی صحبت شد"})
    v = ReviewView(I18n("en"))
    qtbot.addWidget(v)
    v.load(str(raw), lines, fixes, "fa")
    assert not v.use_fix(1)
    v.set_use_fix(1, True)
    v.save()
    assert "متفاوتی" in (tmp_path / "b - متن اصلاح‌شده.txt").read_text("utf-8")


def test_review_summary_counts(qtbot, tmp_path):
    v, _ = review_with(qtbot, tmp_path)
    assert v.summary_label.text().startswith("2 lines fixed · 1 kept")
    v2, _ = review_with(qtbot, tmp_path / ".." / tmp_path.name, lang="fa")
    assert "۲" in v2.summary_label.text()


def test_review_only_changed_filter(qtbot, tmp_path):
    v, _ = review_with(qtbot, tmp_path)
    assert v.table.isRowHidden(2) and not v.table.isRowHidden(0)
    v.only_changed_box.setChecked(False)
    assert not v.table.isRowHidden(2)


def test_copied_label_reset_survives_view_deletion(qtbot, raw_file):
    v = ExportView(I18n("en"))
    v.load(str(raw_file), [], "fa")
    v.copy(0)
    v.deleteLater()
    qtbot.wait(2700)    # the reset timer must not touch the deleted button
