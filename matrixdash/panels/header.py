"""Title, clock, host facts and the scrolling status / alert ticker."""

from __future__ import annotations

import time

from ..config import DEFAULT_CONFIG
from ..fmt import fmt_uptime
from ..models import Snapshot
from ..render.canvas import Canvas
from ..theme import BIG_DIGITS, DAYS_PT, G1, G2, G4, G5, G6, MONTHS_PT, RED, TEXT, WHITE
from .base import Panel


class HeaderPanel(Panel):
    HEIGHT = 5

    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        alerts = self.d.alerts(s)
        c.box(0, 0, w, h, "", "", RED if alerts and int(t * 2) % 2 else G2, G5, double=True)

        title = f"◈ {self.d.config.get('title', DEFAULT_CONFIG['title'])}"
        hi = int(t * 16) % (len(title) + 40)
        for i, ch in enumerate(title):
            style = WHITE if abs(i - hi) <= 1 else G6 if abs(i - hi) <= 3 else G5
            c.put(3 + i, 1, ch, style)

        now = time.localtime()
        clock = time.strftime("%H%M%S", now)
        glyphs = [clock[0], clock[1], ":", clock[2], clock[3], ":", clock[4], clock[5]]
        clock_w = sum(2 if g == ":" else 4 for g in glyphs) - 1
        cx = w - clock_w - 3
        colon_on = (time.time() % 1.0) < 0.5
        gx = cx
        for idx, g in enumerate(glyphs):
            if g == ":":
                if colon_on:
                    c.put(gx, 1, "•", G4)
                    c.put(gx, 3, "•", G4)
                gx += 2
                continue
            style = G4 if idx >= 6 else G6
            for r in range(3):
                c.put_sparse(gx, 1 + r, BIG_DIGITS[g][r], style)
            gx += 4

        date = f"{DAYS_PT[now.tm_wday]} {now.tm_mday:02d} {MONTHS_PT[now.tm_mon - 1]} {now.tm_year}"
        c.put(cx - len(date) - 4, 1, date, G4)

        info = [
            ("HOST", s.hostname), ("IP", f"{s.ip} ({s.iface})"), ("KERNEL", s.kernel.split("-generic")[0]),
            ("UPTIME", fmt_uptime(s.uptime_s)), ("OPERATOR", self.d.operator),
        ]
        xx = 3
        limit = cx - 4
        for idx, (label, value) in enumerate(info):
            seg = len(label) + len(value) + 5
            if xx + seg > limit:
                break
            if idx:
                c.put(xx - 3, 2, " ▸ ", G1)
            c.put(xx, 2, label, G2)
            c.put(xx + len(label) + 1, 2, value, TEXT)
            xx += seg

        tick_w = max(10, limit - 3)
        if alerts:
            items = [f"ALERT: {a}" for a in alerts]
            style = RED
        else:
            running = sum(1 for ct in s.containers if ct.state == "running")
            active = sum(1 for _, _, st in s.units if st == "active")
            items = [
                "ALL SYSTEMS NOMINAL",
                f"{running}/{len(s.containers)} CONTAINERS RUNNING",
                f"{active}/{len(s.units)} HOST SERVICES ACTIVE",
            ] + [item for integ in self.d.integrations for item in integ.status_items(s)] + [
                f"LINK {s.latency:.0f} MS" if s.latency is not None else "LINK TIMEOUT",
            ] + [item for integ in self.d.integrations for item in integ.ticker(s)] + [
                f"{m} {p:.0f}% USED" for m, p, _, _ in s.disks]
            style = G4
        text = "   ▸   ".join(items) + "   ▸   "
        offset = int(t * 9) % len(text)
        loop = (text * (tick_w // len(text) + 2))[offset:offset + tick_w]
        c.put(3, 3, loop, style)
