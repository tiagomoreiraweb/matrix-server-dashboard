"""Claude Code agent block of the services panel."""

from __future__ import annotations

import math
import time

from ..fmt import fmt_size, fmt_tokens, fmt_uptime
from ..models import Snapshot
from ..render.charts import heat_strip
from ..render.widgets import bar
from ..theme import CYAN, G0, G2, G3, G4, G5, RED, SPINNER, TEXT, WHITE
from .services import ServiceRows, ServicesSection
from .usage import limit_style, reset_label


class AgentSection(ServicesSection):
    def reserve(self, s: Snapshot) -> int:
        return 5

    def draw(self, rows: ServiceRows, s: Snapshot, t: float):
        c, ix, iw, bottom = rows.c, rows.ix, rows.iw, rows.bottom
        col_state, col_up, wide = rows.col_state, rows.col_up, rows.wide
        blink = int(t * 2) % 2 == 0
        rows.row += 1 if bottom - rows.row > 4 else 0
        cl = s.claude
        rows.heading("AI AGENT // CLAUDE CODE", f"v{cl.version}" if cl.version else "", CYAN)
        row = rows.row
        if row < bottom:
            if cl.running:
                pulse = (math.sin(t * 3.0) + 1) / 2
                c.put(ix, row, "●", CYAN if pulse > 0.4 else G4)
                c.put(ix + 2, row, "CLAUDE CODE", WHITE)
                c.put(col_state, row, "ONLINE", CYAN)
                sess = f"{cl.sessions} session{'s' if cl.sessions != 1 else ''}"
                c.put(col_up, row, sess, TEXT)
                if cl.remote and wide:
                    c.put(col_up + len(sess) + 3, row, f"remote ◂ {cl.remote} ▸", G4)
            else:
                c.put(ix, row, "●", RED if blink else G0)
                c.put(ix + 2, row, "CLAUDE CODE", G3)
                c.put(col_state, row, "OFFLINE", RED)
                c.put(col_up, row, "no claude process found", G2)
            row += 1
        if cl.running and row < bottom:
            state = "WORKING" if cl.working else "IDLE"
            spin = SPINNER[int(t * 10) % 4] if cl.working else "·"
            c.put(ix + 2, row, "└", G2)
            c.put(ix + 4, row, f"{spin} {state}", CYAN if cl.working else G4)
            info = f"cpu {cl.cpu:4.1f}%  mem {fmt_size(cl.rss)}  up {fmt_uptime(time.time() - cl.since)}"
            c.put(col_state + 2, row, info, TEXT)
            hx = col_state + 2 + len(info) + 2
            hw = ix + iw - hx
            if hw >= 8:
                c.put(hx, row, heat_strip(s.claude_hist, hw, max(10.0, max(s.claude_hist[-hw:], default=0))), CYAN)
            row += 1
        if s.plan and s.plan["windows"] and row < bottom:
            c.put(ix + 2, row, "└", G2)
            c.put(ix + 4, row, "plano", G3)
            xx = col_state + 2
            for key, label in (("five_hour", "5h"), ("seven_day", "sem")):
                w = s.plan["windows"].get(key)
                if not w:
                    continue
                style = limit_style(w["pct"])
                c.put(xx, row, label, G3)
                bar(c, xx + len(label) + 1, row, 8, w["pct"], t, style)
                txt = f"{w['pct']:3.0f}% {reset_label(w['resets'], key)}"
                c.put(xx + len(label) + 10, row, txt, style if style != G5 else TEXT)
                xx += len(label) + 11 + len(txt) + 2
            row += 1
        if s.usage and row < bottom:
            u = s.usage
            c.put(ix + 2, row, "└", G2)
            c.put(ix + 4, row, "uso", G3)
            line = (f"hoje {fmt_tokens(u['today']['tokens'])} ${u['today']['cost']:.2f}  ·  "
                    f"semana ${u['week']['cost']:.2f}  ·  5h ${u['last5h']['cost']:.2f}")
            c.put(col_state + 2, row, line[: ix + iw - col_state - 2], CYAN)
            row += 1
        rows.row = row
