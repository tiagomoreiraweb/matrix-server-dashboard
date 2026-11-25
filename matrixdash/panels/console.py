"""Event console with typing effect."""

from __future__ import annotations

import time

from ..models import Snapshot
from ..render.canvas import Canvas
from ..theme import G2, G3, G4, G5, TEXT
from .base import Panel


class ConsolePanel(Panel):
    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        events = list(self.d.collector.events)
        ix, iw, _ = self.frame(c, x, y, w, h, f"▸ CONSOLE // {self.d.user}@{self.d.collector.hostname}", f"{len(events)} events", t * 14 + 90)
        lines = h - 3
        visible = events[-lines:] if lines > 0 else []
        now = time.monotonic()
        row = y + 1
        tag_w = 8
        for idx, ev in enumerate(visible):
            stamp = time.strftime("%H:%M:%S", time.localtime(ev.wall))
            text = ev.text
            is_last = idx == len(visible) - 1
            if is_last:
                text = text[: max(0, int((now - ev.mono) * 70))]
            age_style = G2 if idx < len(visible) - 3 else G3
            c.put(ix, row, stamp, age_style)
            c.put(ix + 9, row, f"{ev.tag:<{tag_w}}"[:tag_w], ev.style)
            c.put(ix + 10 + tag_w, row, text[: iw - 10 - tag_w], TEXT if ev.style in (G3, G4) else ev.style)
            row += 1
        prompt = f"{self.d.user}@{self.d.collector.hostname}:~$ "
        py = y + h - 2
        c.put(ix, py, prompt, G5)
        if int(t * 2.5) % 2 == 0:
            c.put(ix + len(prompt), py, "█", G5)
