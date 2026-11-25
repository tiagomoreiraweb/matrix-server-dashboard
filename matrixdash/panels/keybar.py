"""Hotkey strip over the bottom border."""

from __future__ import annotations

from ..models import Snapshot
from ..render.canvas import Canvas
from ..theme import AMBER, G4, KEYCAP, KEYCAP_RED, NONE
from .base import Panel


class KeyBar(Panel):
    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        """Hotkey strip drawn over the bottom border of the last row of panels."""
        items = []
        for key, label in self.d.available_hotkeys():
            if key == "E" and self.d.eco:
                label = "economia ON"
            for integ in self.d.integrations:
                label = integ.key_label(key, s, self.d) or label
            items.append((key, label))
        total = sum(len(lbl) + 5 for _, lbl in items) - 2
        while total > c.w - 4 and len(items) > 3:
            items.pop(-3)
            total = sum(len(lbl) + 5 for _, lbl in items) - 2
        x = max(1, (c.w - total) // 2)
        y = c.h - 1
        c.put(x - 1, y, " ", NONE)
        for key, label in items:
            danger = key in ("D", "R")
            c.put(x, y, f" {key} ", KEYCAP_RED if danger else KEYCAP)
            c.put(x + 3, y, f" {label} ", G4 if not danger else AMBER)
            x += len(label) + 5
