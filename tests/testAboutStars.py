# About stars move. The green title is a separate still layer.
# Run from the repo root: python tests/testAboutStars.py

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ui.uiAbout import aboutStarState, splitAboutArt, stepAboutStars


def fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def pixel(r, g, b, a=255):
    return bytes((r, g, b, a))


def main():
    errors = 0
    # 2x2: green title, white star, black field, transparent
    raw = pixel(0, 180, 0) + pixel(240, 240, 240) + pixel(0, 0, 0) + pixel(0, 0, 0, 0)
    text, stars, vanish = splitAboutArt(raw, 2, 2)
    if text[1] != 180:
        errors += fail("title green", text[1])
    if text[4] != 0 or text[7] != 0:
        errors += fail("star not in title", text[4:8])
    if len(stars) != 1:
        errors += fail("star count", stars)
    else:
        x, y, bright = stars[0]
        if abs(x - 0.5) > 0.01 or abs(y - 0.0) > 0.01:
            errors += fail("star pos", (x, y))
        if bright < 200:
            errors += fail("star bright", bright)
    if vanish[0] > 0.2:
        errors += fail("vanish", vanish)

    state = aboutStarState([(0.8, 0.2, 255)], (0.5, 0.5))
    before = state[0][1]
    stepAboutStars(state)
    if state[0][1] <= before:
        errors += fail("step", (before, state[0][1]))
    state[0][1] = 2.0
    stepAboutStars(state, limit=1.25)
    if state[0][1] > 0.05:
        errors += fail("wrap", state[0][1])

    poster = os.path.join(ROOT, "ui", "DataDoctor.png")
    if os.path.isfile(poster):
        from PyQt6.QtGui import QImage
        image = QImage(poster).convertToFormat(QImage.Format.Format_RGBA8888)
        ptr = image.bits()
        ptr.setsize(image.sizeInBytes())
        raw = bytes(ptr)
        bpl = image.bytesPerLine()
        width, height = image.width(), image.height()
        rowBytes = width * 4
        if bpl != rowBytes:
            packed = bytearray()
            for y in range(height):
                start = y * bpl
                packed.extend(raw[start:start + rowBytes])
            raw = bytes(packed)
        text, stars, vanish = splitAboutArt(raw, width, height)
        green = sum(1 for i in range(1, len(text), 4) if text[i] > 50)
        if green < 1000:
            errors += fail("poster title", green)
        if len(stars) < 100:
            errors += fail("poster stars", len(stars))
        textImage = QImage(text, width, height, QImage.Format.Format_RGBA8888)
        if textImage.isNull():
            errors += fail("text image", "null")

    if errors:
        print(f"{errors} failed")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
