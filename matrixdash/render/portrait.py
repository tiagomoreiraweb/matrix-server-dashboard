"""ASCII portrait."""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from ..theme import (
    CYAN,
    G0,
    G1,
    G2,
    G3,
    G4,
    G5,
    G6,
    GLITCH_CHARS,
    NONE,
    SCRAMBLE_CHARS,
    WHITE,
)
from .canvas import Canvas


class Portrait:
    """ASCII portrait shaded by density, with decode, scan, shimmer and glitch."""

    SHADE = {" ": 0, ".": 1, "`": 1, "'": 1, ",": 1, ":": 2, ";": 2, "-": 2, "~": 3, "=": 3,
             "+": 4, "*": 4, "x": 4, "#": 5, "%": 6, "@": 6, "&": 6, "$": 6}
    SHADE_STYLE = (NONE, G1, G2, G3, G4, G5, G6, WHITE, WHITE)

    def __init__(self, path: Path, fallback_text: str = ""):
        self.path = path
        # Shown (as big shaded letters) when there is no image file.
        self.fallback_text = fallback_text
        self.cache_key: tuple[int, int] | None = None
        self.lines: list[str] = []
        self.rows: list[dict[str, Any]] = []
        self.art_w = 0
        self.reveal_at: list[list[float]] = []

    def natural_size(self) -> tuple[int, int]:
        if self.path.suffix.lower() in {".txt", ".asc"} and self.path.exists():
            raw = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
            return (max((len(r) for r in raw), default=0), len(raw))
        return (100, 40)

    def _banner_image(self) -> Image.Image:
        """Server name in big letters with a soft glow, used when no portrait is configured."""
        from PIL import ImageDraw, ImageFilter, ImageFont
        words = [w for w in re.split(r"[\s._-]+", self.fallback_text.upper()) if w][:3] or ["MATRIX"]
        try:
            font = ImageFont.load_default(size=96)
        except TypeError:  # Pillow < 10.1 has only a tiny bitmap font
            font = ImageFont.load_default()
        probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        boxes = [probe.textbbox((0, 0), w, font=font) for w in words]
        tw = max(b[2] - b[0] for b in boxes) + 40
        line_h = max(b[3] - b[1] for b in boxes) + 30
        img = Image.new("L", (tw, line_h * len(words) + 20), 0)
        draw = ImageDraw.Draw(img)
        for i, (w, b) in enumerate(zip(words, boxes)):
            draw.text(((tw - (b[2] - b[0])) // 2 - b[0], 10 + i * line_h - b[1]), w, fill=255, font=font)
        glow = img.filter(ImageFilter.GaussianBlur(6)).point(lambda v: v // 2)
        return Image.composite(img, glow, img)

    def _render_image(self, max_w: int, max_h: int) -> list[str]:
        if max_w < 4 or max_h < 2:
            return ["IMAGE NOT FOUND"]
        if not self.path.exists() and not self.fallback_text:
            return ["IMAGE NOT FOUND"]

        if self.path.suffix.lower() in {".txt", ".asc"} and self.path.exists():
            raw = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
            if not raw:
                return ["ASCII FILE EMPTY"]
            source_w = max(len(line) for line in raw)
            step_x = max(1, (source_w + max_w - 1) // max_w)
            step_y = max(1, (len(raw) + max_h - 1) // max_h)
            return [row[::step_x][:max_w] for row in raw[::step_y][:max_h]]

        if self.path.exists():
            image = Image.open(self.path)
            image = ImageOps.exif_transpose(image).convert("L")
        else:
            image = self._banner_image()
        extrema = image.getextrema()
        if extrema[1] - extrema[0] > 20:
            image = ImageOps.autocontrast(image)
        # Terminal characters are roughly twice as tall as they are wide.
        aspect = image.width / max(1, image.height)
        target_w = max_w
        target_h = max(1, int((target_w / aspect) * 0.48))
        if target_h > max_h:
            target_h = max_h
            target_w = max(1, int(target_h * aspect / 0.48))
        target_w = min(target_w, max_w)
        image = image.resize((target_w, target_h))
        ramp = " .:-=+*#%@"
        pixels = image.tobytes()
        lines = []
        for y in range(target_h):
            row = []
            for x in range(target_w):
                value = pixels[y * target_w + x]
                row.append(" " if value < 16 else ramp[int((value / 255) * (len(ramp) - 1))])
            lines.append("".join(row).rstrip())
        return lines

    def _prepare(self, max_w: int, max_h: int):
        key = (max_w, max_h)
        if key == self.cache_key:
            return
        try:
            self.lines = self._render_image(max_w, max_h)
        except Exception as exc:
            self.lines = [f"IMAGE ERROR: {exc}"[:max_w]]
        self.cache_key = key
        self.art_w = max((len(l) for l in self.lines), default=0)
        self.rows = []
        n = max(1, len(self.lines))
        self.reveal_at = []
        for i, line in enumerate(self.lines):
            shades = [self.SHADE.get(ch, 4 if ch != " " else 0) for ch in line]
            runs = []
            start = None
            for j, ch in enumerate(line + " "):
                if ch != " " and start is None:
                    start = j
                elif ch == " " and start is not None:
                    runs.append((start, j))
                    start = None
            styles = [
                [self.SHADE_STYLE[min(len(self.SHADE_STYLE) - 1, s + boost)] if s else NONE for s in shades]
                for boost in range(3)
            ]
            self.rows.append({"chars": list(line), "shades": shades, "runs": runs, "styles": styles})
            self.reveal_at.append([0.2 + (i / n) * 1.6 + random.random() * 1.0 for _ in line])

    REVEAL_END = 3.2

    def draw(self, c: Canvas, x: int, y: int, w: int, h: int, t: float,
             glitch_rows: dict[int, int] | None = None) -> float:
        """Draws the portrait and returns the scan progress (0..1)."""
        self._prepare(max(1, w), max(1, h))
        ah = len(self.rows)
        ox = x + max(0, (w - self.art_w) // 2)
        oy = y + max(0, (h - ah) // 2)

        if t < self.REVEAL_END:
            for i, row in enumerate(self.rows):
                yy = oy + i
                if not (0 <= yy < c.h):
                    continue
                rc, rs = c.chars[yy], c.styles[yy]
                times = self.reveal_at[i]
                base = row["styles"][0]
                for j, ch in enumerate(row["chars"]):
                    if ch == " ":
                        continue
                    xx = ox + j
                    if not (0 <= xx < c.w):
                        continue
                    rt = times[j]
                    if t < rt - 0.55:
                        continue
                    if t < rt:
                        rc[xx] = random.choice(SCRAMBLE_CHARS)
                        rs[xx] = G4
                    elif t < rt + 0.14:
                        rc[xx] = ch
                        rs[xx] = WHITE
                    else:
                        rc[xx] = ch
                        rs[xx] = base[j]
            return 0.0

        period = ah + 14
        scan = (t * 7.0) % period - 7
        shimmer_period = self.art_w + 90
        for i, row in enumerate(self.rows):
            yy = oy + i
            if not (0 <= yy < c.h):
                continue
            d = abs(i - scan)
            boost = 2 if d < 0.6 else 1 if d < 2.6 else 0
            chars, styles = row["chars"], row["styles"][boost]
            rc, rs = c.chars[yy], c.styles[yy]
            shift = 0
            if glitch_rows and i in glitch_rows:
                shift = glitch_rows[i]
            if boost == 2:
                for xx in range(x, min(c.w, x + w)):
                    if rc[xx] == " " or rs[xx] in (G0, G1):
                        rc[xx] = "·"
                        rs[xx] = G2
            for a, b in row["runs"]:
                xa, xb = ox + a + shift, ox + b + shift
                ca, cb = max(xa, x), min(xb, x + w, c.w)
                if cb <= ca:
                    continue
                rc[ca:cb] = chars[a + (ca - xa):b - (xb - cb)]
                rs[ca:cb] = styles[a + (ca - xa):b - (xb - cb)]
            if shift:
                # Chromatic ghost of the torn row plus random noise.
                for a, b in row["runs"]:
                    for j in range(a, b):
                        if random.random() < 0.18:
                            xx = ox + j
                            if x <= xx < min(c.w, x + w):
                                rc[xx] = random.choice(GLITCH_CHARS)
                                rs[xx] = CYAN if random.random() < 0.6 else WHITE
            else:
                # Diagonal shimmer band sweeping across the face.
                cx = int((t * 26 - i * 1.3) % shimmer_period) - 40
                if 0 <= cx + 4 and cx - 4 < self.art_w and boost < 2:
                    brighter = row["styles"][boost + 1]
                    for j in range(max(0, cx - 4), min(len(chars), cx + 5)):
                        if chars[j] != " ":
                            xx = ox + j
                            if x <= xx < min(c.w, x + w):
                                rs[xx] = brighter[j]
        return max(0.0, min(1.0, scan / max(1, ah)))
