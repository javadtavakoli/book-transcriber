import re

from booktranscriber.i18n import STRINGS, I18n, fmt_bytes, fmt_duration, fmt_number, initial_language


def test_keys_match():
    assert set(STRINGS["en"]) == set(STRINGS["fa"])


def test_placeholders_match():
    for k in STRINGS["en"]:
        assert set(re.findall(r"{(\w+)}", STRINGS["en"][k])) == set(re.findall(r"{(\w+)}", STRINGS["fa"][k])), k


def test_no_empty_strings():
    assert all(v.strip() for lang in STRINGS.values() for v in lang.values())


def test_initial_language():
    assert initial_language(None, "fa_IR") == "fa"
    assert initial_language(None, "en_US") == "en"
    assert initial_language("en", "fa_IR") == "en"
    assert initial_language("xx", "fa_IR") == "fa"


def test_number_formatting():
    assert fmt_number(58, "fa") == "۵۸" and fmt_number(58, "en") == "58"
    assert fmt_bytes(2_100_000_000, "fa") == "۲٫۱ گیگابایت" and fmt_bytes(2_100_000_000, "en") == "2.1 GB"
    assert fmt_bytes(612_000_000, "en") == "612 MB"


def test_duration_formatting():
    assert fmt_duration(370, "en") == "about 6 min"
    assert fmt_duration(30, "fa") == "کمتر از یک دقیقه"
    assert fmt_duration(30, "en") == "less than a minute"
    assert fmt_duration(370, "fa") == "حدود ۶ دقیقه"
    assert fmt_duration(5400, "en") == "about 1 h 30 min"


def test_tr_and_switch(qtbot):
    i = I18n("en")
    got = []
    i.language_changed.connect(got.append)
    i.set_language("fa")
    assert got == ["fa"] and i.is_rtl()
    assert i.tr("setup.welcome.title") == STRINGS["fa"]["setup.welcome.title"]


def test_tr_formats_and_missing_key(qtbot):
    i = I18n("en")
    assert i.tr("no.such.key") == "no.such.key"
    assert "RTX" in i.tr("setup.check.gpu_ok", gpu="RTX")
