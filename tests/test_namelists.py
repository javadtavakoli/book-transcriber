from pathlib import Path

from booktranscriber.namelists import (build_prompt, import_prompt_file, list_lists, load_list,
                                       parse_names, save_list)

REPO = Path(__file__).resolve().parent.parent


def test_build_prompt_fa():
    assert build_prompt(["هومر", "تعقیب هومر"], "fa") == "جلسهٔ کتاب‌خوانی به زبان فارسی. هومر، تعقیب هومر."
    assert build_prompt([], "fa") == "جلسهٔ کتاب‌خوانی به زبان فارسی."


def test_build_prompt_other_language():
    assert build_prompt([], "en") is None
    assert build_prompt(["Homer"], "en") == "Homer."


def test_parse_names():
    assert parse_names(" هومر \n\nکافکا\nهومر\n") == ["هومر", "کافکا"]


def test_import_example_prompt():
    names = import_prompt_file(REPO / "prompts" / "example-chasing-homer.txt")
    assert names[0] == "تعقیب هومر" and "کافکا" in names and "تانگوی شیطان" in names
    assert not any(n.startswith("جلسهٔ") for n in names)


def test_save_list_sanitises_name(tmp_path):
    save_list(tmp_path, "Chasing/Homer", ["هومر"])
    assert list_lists(tmp_path) == ["Chasing_Homer"]
    assert load_list(tmp_path, "Chasing_Homer") == ["هومر"]
