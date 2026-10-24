from booktranscriber.fixexport import (apply_answer, build_export_parts, corrected_lines, parse_answer,
                                       split_timestamp, word_diff)

LINES = ["[0:00:01] امروز درباره تعغیب حومر حرف زدیم", "[0:00:05] نویسنده اش کراسنا هورکای است", "", "[0:00:09] خب"]


def test_split_timestamp():
    assert split_timestamp("[0:01:05] سلام") == ("[0:01:05] ", "سلام")
    assert split_timestamp("سلام [0:01:05]") == ("", "سلام [0:01:05]")


def test_parts_number_and_strip_timestamps():
    parts = build_export_parts(LINES, ["تعقیب هومر"])
    assert len(parts) == 1
    text = parts[0].text
    assert "[1] امروز درباره تعغیب حومر حرف زدیم" in text and "[4] خب" in text
    assert "[0:00:01]" not in text and "[3]" not in text
    assert "تعقیب هومر" in text and "Part 1 of 1" in text
    assert (parts[0].first_line, parts[0].last_line) == (1, 4)


def test_parts_split_on_line_boundaries():
    lines = ["کلمه " * 50] * 10
    parts = build_export_parts(lines, [], max_chars=600)
    assert [(p.first_line, p.last_line) for p in parts] == [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10)]
    assert all(p.total == 5 for p in parts) and [p.index for p in parts] == [1, 2, 3, 4, 5]


def test_single_overlong_line_gets_its_own_part():
    parts = build_export_parts(["a" * 50, "b" * 1000, "c"], [], max_chars=100)
    assert [(p.first_line, p.last_line) for p in parts] == [(1, 1), (2, 2), (3, 3)]


def test_no_names_omits_names_line():
    assert "Correct spellings of names" not in build_export_parts(["a"], [])[0].text


def test_instructions_state_the_rules():
    t = build_export_parts(["a"], [])[0].text.lower()
    assert "misheard" in t and "meaning" in t and "same numbered lines" in t and "original language" in t


def test_empty_transcript_has_no_parts():
    assert build_export_parts(["", "  "], []) == []


def test_parse_answer_messy():
    text = ("Sure! Here you go:\n```\n[۱] امروز درباره تعقیب هومر حرف زدیم\n2. نویسنده‌اش کراسناهورکای است\n"
            "[٤] خب\n[1] duplicate\n```\nLet me know!")
    assert parse_answer(text) == {1: "امروز درباره تعقیب هومر حرف زدیم", 2: "نویسنده‌اش کراسناهورکای است", 4: "خب"}


def test_parse_answer_garbage():
    assert parse_answer("hello\nPart 1 of 2\n") == {}


def test_apply_answer_accepts_small_fixes_keeps_timestamps():
    fixes = apply_answer(LINES, {1: "امروز درباره تعقیب هومر حرف زدیم", 2: "نویسنده‌اش کراسناهورکای است", 4: "خب"})
    assert [f.reason for f in fixes if f.original] == ["fixed", "fixed", "same"]
    assert corrected_lines(LINES, fixes)[0] == "[0:00:01] امروز درباره تعقیب هومر حرف زدیم"
    assert corrected_lines(LINES, fixes)[2] == ""


def test_apply_answer_rejects_rewrite_and_missing():
    fixes = apply_answer(LINES, {1: "در این جلسه، اعضا به تحلیل مفصل رمان پرداختند و نکات زیادی گفتند"})
    assert fixes[0].reason == "too_different" and not fixes[0].accepted
    assert fixes[1].reason == "missing" and corrected_lines(LINES, fixes)[1] == LINES[1]
    assert corrected_lines(LINES, fixes)[0] == LINES[0]


def test_apply_answer_rejects_deleted_line():
    fixes = apply_answer(["یک دو سه چهار پنج شش"], {1: ""})
    assert fixes[0].reason == "too_different"


def test_word_diff():
    assert word_diff("تعغیب حومر حرف", "تعقیب هومر حرف") == [
        ("removed", "تعغیب حومر"), ("added", "تعقیب هومر"), ("same", "حرف")]
