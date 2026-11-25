"""Character grid every frame is drawn on."""

from __future__ import annotations

from ..theme import BORDER_CHARS, G2, G3, G4, G5, G6, NONE


class Canvas:
    __slots__ = ("w", "h", "chars", "styles")

    def __init__(self, width: int, height: int):
        self.w = max(1, width)
        self.h = max(1, height)
        self.chars = [[" "] * self.w for _ in range(self.h)]
        self.styles = [[NONE] * self.w for _ in range(self.h)]

    def put(self, x: int, y: int, text: str, style: int = G3):
        if y < 0 or y >= self.h or not text:
            return
        if x < 0:
            text = text[-x:]
            x = 0
        if x >= self.w:
            return
        text = text[: self.w - x]
        n = len(text)
        self.chars[y][x:x + n] = text
        self.styles[y][x:x + n] = [style] * n

    def put_sparse(self, x: int, y: int, text: str, style: int = G3):
        if y < 0 or y >= self.h:
            return
        row_c, row_s = self.chars[y], self.styles[y]
        for i, ch in enumerate(text):
            xx = x + i
            if ch != " " and 0 <= xx < self.w:
                row_c[xx] = ch
                row_s[xx] = style

    def style_at(self, x: int, y: int, style: int):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.styles[y][x] = style

    def fill(self, x: int, y: int, w: int, h: int):
        x0, x1 = max(0, x), min(self.w, x + w)
        if x1 <= x0:
            return
        for yy in range(max(0, y), min(self.h, y + h)):
            self.chars[yy][x0:x1] = [" "] * (x1 - x0)
            self.styles[yy][x0:x1] = [NONE] * (x1 - x0)


    def box(self, x: int, y: int, w: int, h: int, title: str = "", right: str = "",
            style: int = G2, title_style: int = G5, clear: bool = True, double: bool = False):
        if w < 4 or h < 2:
            return
        if clear:
            self.fill(x + 1, y + 1, w - 2, h - 2)
        if double:
            tl, tr, bl, br, hz, vt = "╔", "╗", "╚", "╝", "═", "║"
        else:
            tl, tr, bl, br, hz, vt = "╭", "╮", "╰", "╯", "─", "│"
        self.put(x, y, tl + hz * (w - 2) + tr, style)
        self.put(x, y + h - 1, bl + hz * (w - 2) + br, style)
        right_x = x + w - 1
        for yy in range(max(0, y + 1), min(self.h, y + h - 1)):
            rc, rs = self.chars[yy], self.styles[yy]
            if 0 <= x < self.w:
                rc[x], rs[x] = vt, style
            if 0 <= right_x < self.w:
                rc[right_x], rs[right_x] = vt, style
        if title:
            label = f" {title} "[: max(0, w - 6)]
            self.put(x + 2, y, label, title_style)
        if right:
            label = f" {right} "
            if len(label) < w - 8 - len(title):
                self.put(x + w - len(label) - 2, y, label, G3)

    def pulse(self, x: int, y: int, w: int, h: int, pos: float, length: int = 7):
        """Light segment travelling around a box border."""
        per = 2 * (w - 1) + 2 * (h - 1)
        if per <= 0:
            return
        for k in range(length):
            p = int(pos - k) % per
            if p < w - 1:
                px, py = x + p, y
            elif p < (w - 1) + (h - 1):
                px, py = x + w - 1, y + p - (w - 1)
            elif p < 2 * (w - 1) + (h - 1):
                px, py = x + w - 1 - (p - (w - 1) - (h - 1)), y + h - 1
            else:
                px, py = x, y + h - 1 - (p - 2 * (w - 1) - (h - 1))
            if 0 <= px < self.w and 0 <= py < self.h and self.chars[py][px] in BORDER_CHARS:
                self.styles[py][px] = G6 if k == 0 else G5 if k < 3 else G4
