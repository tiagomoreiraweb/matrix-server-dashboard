"""ASCII portrait with its HUD."""

from __future__ import annotations

import time

from ..models import Snapshot
from ..render.canvas import Canvas
from ..render.portrait import Portrait
from ..render.widgets import bar
from ..theme import AMBER, G4, G6, RED
from .base import Panel


class PortraitPanel(Panel):
    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        self.frame(c, x, y, w, h, "▸ IDENTITY // OPERATOR", f"◈ {self.d.operator}", t * 18, clear=False)
        rows = self.d.glitch_rows if time.monotonic() < self.d.glitch_until else None
        progress = self.d.portrait.draw(c, x + 1, y + 1, w - 2, h - 2, t, rows)

        # HUD overlays on the bottom border.
        if t < Portrait.REVEAL_END:
            pct = min(100.0, t / Portrait.REVEAL_END * 100)
            label = f" DECODING {pct:5.1f}% "
            c.put(x + 2, y + h - 1, label, G6)
            right = " IDENTITY MATRIX LOADING "
            c.put(x + w - len(right) - 2, y + h - 1, right, AMBER if int(t * 4) % 2 else G4)
        else:
            sw = 16
            c.put(x + 2, y + h - 1, " SCAN ", G4)
            bar(c, x + 8, y + h - 1, sw, progress * 100, t, G4)
            c.put(x + 9 + sw, y + h - 1, f" {progress * 100:3.0f}% ", G4)
            verified = int(t * 1.5) % 3 != 0
            label = f" ID {self.d.operator} · MATCH 99.7% · "
            c.put(x + w - len(label) - 12, y + h - 1, label, G4)
            c.put(x + w - 12, y + h - 1, "[VERIFIED]" if verified else "[        ]", G6)
        if rows:
            c.put(x + w // 2 - 9, y, " SIGNAL INTERFERENCE ", RED)
