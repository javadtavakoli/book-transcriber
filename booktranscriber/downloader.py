"""Resumable, verified HTTP downloads (models and GPU libraries are gigabytes on flaky connections)."""
import hashlib
import os
import threading
from pathlib import Path
from typing import Callable

import httpx

CHUNK = 1024 * 1024


class DownloadCancelled(Exception):
    pass


class ChecksumError(Exception):
    pass


class NetworkError(Exception):
    pass


def download_file(url: str, dest: Path, size: int | None, sha256: str | None,
                  on_progress: Callable[[int], None], cancel: threading.Event,
                  client: httpx.Client | None = None) -> None:
    """Download url to dest via dest.part, resuming a previous .part when the server allows it.

    on_progress gets the bytes done so far for this file (resets to 0 if the server restarts).
    """
    dest = Path(dest)
    if dest.exists() and (size is None or dest.stat().st_size == size):
        on_progress(dest.stat().st_size)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    own_client = client is None
    # A short read timeout bounds how long a stalled connection can delay Pause or closing the app.
    client = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=15.0))
    try:
        _fetch(client, url, part, on_progress, cancel)
    except httpx.HTTPError as e:
        raise NetworkError(str(e)) from e
    except OSError as e:
        if isinstance(e, (PermissionError, FileNotFoundError)) or getattr(e, "errno", None) == 28:
            raise
        raise NetworkError(str(e)) from e
    finally:
        if own_client:
            client.close()

    if (size is not None and part.stat().st_size != size) or (sha256 and _sha256(part, cancel) != sha256.lower()):
        part.unlink()
        raise ChecksumError(f"{dest.name} arrived damaged")
    os.replace(part, dest)


def _fetch(client, url, part: Path, on_progress, cancel) -> None:
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with client.stream("GET", url, headers=headers) as r:
        if r.status_code == 416 and have:       # .part already complete
            on_progress(have)
            return
        r.raise_for_status()
        if r.status_code != 206:                # server ignored Range: start over
            have = 0
        on_progress(have)
        with open(part, "ab" if have else "wb") as f:
            for chunk in r.iter_bytes():         # as received, so a drop keeps what arrived
                if cancel.is_set():
                    raise DownloadCancelled()
                f.write(chunk)
                have += len(chunk)
                on_progress(have)


def _sha256(path: Path, cancel: threading.Event | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            if cancel is not None and cancel.is_set():
                raise DownloadCancelled()
            h.update(block)
    return h.hexdigest()
