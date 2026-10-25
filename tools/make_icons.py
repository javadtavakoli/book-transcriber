"""Render booktranscriber/assets/icon.svg to icon.png (256), a multi-size icon.ico and icon.icns (macOS).

Run: ./venv/bin/python tools/make_icons.py
"""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parent.parent / "booktranscriber" / "assets"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# PNG-compressed ICNS entry types and their pixel sizes (the @2x ones double the point size).
ICNS_TYPES = {"icp4": 16, "icp5": 32, "ic11": 32, "ic12": 64, "ic07": 128, "ic13": 256,
              "ic08": 256, "ic14": 512, "ic09": 512, "ic10": 1024}


def render(renderer: QSvgRenderer, size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    renderer.render(p)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def write_ico(path: Path, images: dict[int, bytes]) -> None:
    """An ICO container with PNG-compressed entries."""
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for size, png in images.items():
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    path.write_bytes(head + entries + data)


def write_icns(path: Path, images: dict[str, bytes]) -> None:
    """An ICNS container with PNG entries: each is type, big-endian length (header included), data."""
    body = b"".join(t.encode() + struct.pack(">I", 8 + len(png)) + png for t, png in images.items())
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)


def main() -> int:
    app = QGuiApplication(sys.argv)   # noqa: F841  (Qt needs it alive to paint)
    renderer = QSvgRenderer(str(ASSETS / "icon.svg"))
    if not renderer.isValid():
        print("icon.svg is not valid", file=sys.stderr)
        return 1
    (ASSETS / "icon.png").write_bytes(png_bytes(render(renderer, 256)))
    write_ico(ASSETS / "icon.ico", {s: png_bytes(render(renderer, s)) for s in ICO_SIZES})
    write_icns(ASSETS / "icon.icns", {t: png_bytes(render(renderer, s)) for t, s in ICNS_TYPES.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
