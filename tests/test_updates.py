import httpx
import pytest

from booktranscriber import __version__, updates
from booktranscriber.updates import check_latest   # the real one: conftest replaces updates.check_latest
from booktranscriber.settings import Settings


@pytest.mark.parametrize("tag,expected", [("v0.1.10", (0, 1, 10)), ("0.2.0", (0, 2, 0)),
                                          ("garbage", None), ("v1.x", None), ("", None), ("v0.2.0-beta", None)])
def test_parse_version(tag, expected):
    assert updates.parse_version(tag) == expected


def test_newer_version():
    assert updates.newer_version("0.1.0", "v0.2.0") == "v0.2.0"
    assert updates.newer_version("0.1.9", "v0.1.10") == "v0.1.10"
    assert updates.newer_version("0.1.0", "v0.1.0") is None
    assert updates.newer_version("0.2.0", "v0.1.0") is None
    assert updates.newer_version("0.1.0", "garbage") is None


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_check_latest_returns_tag_and_identifies_the_app():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"tag_name": "v0.2.0"})
    assert check_latest(client_for(handler)) == "v0.2.0"
    assert str(seen[0].url) == updates.RELEASES_API
    assert seen[0].headers["User-Agent"] == f"WritingParrot/{__version__}"


def test_check_latest_404_is_none():
    assert check_latest(client_for(lambda r: httpx.Response(404))) is None


def test_check_latest_offline_is_none():
    def handler(request):
        raise httpx.ConnectError("offline")
    assert check_latest(client_for(handler)) is None


def test_check_latest_odd_bodies_are_none():
    assert check_latest(client_for(lambda r: httpx.Response(200, text="<html>"))) is None
    assert check_latest(client_for(lambda r: httpx.Response(200, json=["x"]))) is None
    assert check_latest(client_for(lambda r: httpx.Response(200, json={"tag_name": 3}))) is None


def test_check_latest_uses_the_environment_proxy(monkeypatch):
    seen = {}
    real = httpx.Client

    def spy(*a, **k):
        seen.update(k)
        return real(*a, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"tag_name": "v1.0.0"})))
    monkeypatch.setattr(updates.httpx, "Client", spy)
    assert check_latest() == "v1.0.0"
    assert seen["trust_env"] is True and seen["timeout"] == 5


def test_due_boundaries():
    day = 24 * 3600
    assert updates.due(Settings(), 1000.0)
    assert not updates.due(Settings(last_update_check=1000.0), 1000.0 + day - 1)
    assert updates.due(Settings(last_update_check=1000.0), 1000.0 + day)
    assert updates.due(Settings(last_update_check=5000.0), 1000.0)     # the clock went backwards
