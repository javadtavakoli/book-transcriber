"""Is a newer release published on GitHub? Asked at most once a day, and any failure just means "don't know"."""
import re

import httpx

from . import __version__

RELEASES_API = "https://api.github.com/repos/javadtavakoli/book-transcriber/releases/latest"
RELEASES_PAGE = "https://github.com/javadtavakoli/book-transcriber/releases/latest"
CHECK_EVERY = 24 * 3600

_VERSION = re.compile(r"v?(\d+(?:\.\d+)*)")


def parse_version(tag: str) -> tuple[int, ...] | None:
    m = _VERSION.fullmatch(tag.strip()) if isinstance(tag, str) else None
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def newer_version(current: str, latest_tag: str) -> str | None:
    """latest_tag if it is a higher version than current, else None (also when either can't be read)."""
    cur, latest = parse_version(current), parse_version(latest_tag)
    return latest_tag if cur is not None and latest is not None and latest > cur else None


def check_latest(client: httpx.Client | None = None, timeout=5) -> str | None:
    """The latest published release's tag, or None on any error."""
    own = client is None
    # trust_env: unlike the localhost client, a proxy the user has set up is wanted here.
    client = client or httpx.Client(trust_env=True, timeout=timeout, follow_redirects=True)
    try:
        r = client.get(RELEASES_API, headers={"User-Agent": f"WritingParrot/{__version__}",
                                              "Accept": "application/vnd.github+json"})
        r.raise_for_status()
        tag = r.json().get("tag_name")
        return tag if isinstance(tag, str) else None
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    finally:
        if own:
            client.close()


def due(settings, now: float) -> bool:
    last = settings.last_update_check
    return last is None or now < last or now - last >= CHECK_EVERY
