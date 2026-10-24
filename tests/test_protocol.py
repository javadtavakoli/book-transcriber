import pytest

from booktranscriber.protocol import decode, encode


def test_roundtrip_persian():
    ev = {"type": "segment", "start": 1.0, "end": 2.0, "text": "تعقیب هومر"}
    line = encode(ev)
    assert "\n" not in line and "تعقیب" in line
    assert decode(line) == ev


def test_encode_escapes_newlines_in_text():
    line = encode({"type": "error", "kind": "unknown", "message": "a\nb"})
    assert "\n" not in line and decode(line)["message"] == "a\nb"


@pytest.mark.parametrize("junk", ["", "   ", "warning: something", "[1,2]", '{"no_type": 1}', "{broken"])
def test_decode_ignores_junk(junk):
    assert decode(junk) is None
