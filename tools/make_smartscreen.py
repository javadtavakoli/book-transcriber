"""Render packaging/smartscreen.png: a simple drawing of the two clicks past the SmartScreen warning.

It is an illustration (two labelled boxes), not a copy of Windows' own window.
Run: ./venv/bin/python tools/make_smartscreen.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPolygonF

OUT = Path(__file__).resolve().parent.parent / "packaging" / "smartscreen.png"
W, H = 760, 300
BLUE, INK, MUTED = QColor("#1f6feb"), QColor("#1f2328"), QColor("#57606a")


def step(p: QPainter, rect: QRectF, number: str, label: str, filled: bool) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, 12, 12)
    p.setPen(QPen(BLUE, 3))
    p.setBrush(BLUE if filled else QColor("#ffffff"))
    p.drawPath(path)
    p.setPen(QColor("#ffffff") if filled else BLUE)
    p.setFont(QFont("Sans", 22, QFont.Bold))
    p.drawText(rect, Qt.AlignCenter, label)
    badge = QRectF(rect.left() - 18, rect.top() - 18, 40, 40)
    p.setBrush(INK)
    p.setPen(Qt.NoPen)
    p.drawEllipse(badge)
    p.setPen(QColor("#ffffff"))
    p.setFont(QFont("Sans", 16, QFont.Bold))
    p.drawText(badge, Qt.AlignCenter, number)


def arrow(p: QPainter, x1: float, x2: float, y: float) -> None:
    p.setPen(QPen(MUTED, 4, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(x1, y), QPointF(x2 - 14, y))
    p.setBrush(MUTED)
    p.setPen(Qt.NoPen)
    p.drawPolygon(QPolygonF([QPointF(x2, y), QPointF(x2 - 18, y - 11), QPointF(x2 - 18, y + 11)]))


def main() -> int:
    app = QGuiApplication(sys.argv)   # noqa: F841  (Qt needs it alive to paint)
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor("#f6f8fa"))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

    p.setPen(INK)
    p.setFont(QFont("Sans", 17, QFont.Bold))
    p.drawText(QRectF(0, 22, W, 34), Qt.AlignCenter, "If Windows says “Windows protected your PC”:")

    box_w, box_h, y = 250, 74, 112
    left, right = QRectF(70, y, box_w, box_h), QRectF(W - 70 - box_w, y, box_w, box_h)
    step(p, left, "1", "More info", filled=False)
    step(p, right, "2", "Run anyway", filled=True)
    arrow(p, left.right() + 16, right.left() - 26, y + box_h / 2)

    p.setPen(MUTED)
    p.setFont(QFont("Sans", 14))
    p.drawText(QRectF(40, 222, W - 80, 60), Qt.AlignCenter | Qt.TextWordWrap,
               "Click the “More info” link first. The “Run anyway” button appears after it.\n"
               "The warning shows because the app isn't signed yet.")
    p.end()
    if not img.save(str(OUT), "PNG"):
        print(f"could not write {OUT}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
