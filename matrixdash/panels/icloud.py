"""iCloud photo download progress."""

from __future__ import annotations

import time

from ..fmt import fmt_rate, fmt_size, fmt_uptime
from ..models import Snapshot
from ..render.canvas import Canvas
from ..render.widgets import bar
from ..theme import AMBER, CYAN, G0, G1, G2, G3, G4, G5, G6, RED, SPINNER, TEXT
from .base import Panel


class ICloudPanel(Panel):
    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float, page: str = ""):
        ic = s.icloud or {}
        status = str(ic.get("status", "starting"))
        blink = int(t * 2) % 2 == 0
        spin = SPINNER[int(t * 10) % 4]
        label, style = {
            "downloading": (f"{spin} BAIXANDO", CYAN),
            "idle": ("● EM DIA", G5),
            "paused": ("● PAUSADO", AMBER),
            "login": ("● PRECISA LOGIN", RED if blink else G0),
            "authenticating": (f"{spin} ENTRANDO NO ICLOUD", AMBER),
        }.get(status, (f"{spin} INICIANDO", G4))
        ix, iw, bottom = self.frame(c, x, y, w, h, "▸ ICLOUD // FOTOS", page, t * 14 + 240, border=RED if status == "login" else G2)
        row = y + 1
        c.put(ix, row, label, style)
        route = "iCloud → /data/fotos/icloud"
        c.put(ix + iw - len(route), row, route, G2)
        row += 1
        total, items = int(ic.get("total") or 0), int(ic.get("items") or 0)
        pct = min(100.0, items / total * 100) if total else 0.0
        if row < bottom:
            bw = iw - 8
            bar(c, ix, row, bw, self.d.ease("icloud", pct), t, CYAN if status == "downloading" else G5)
            c.put(ix + bw + 1, row, f"{pct:5.1f}%", G6)
            row += 1
        if row < bottom:
            c.put(ix, row, f"{items} / {total or '?'} itens · {fmt_size(float(ic.get('bytes', 0)))}", TEXT)
            today = f"hoje {fmt_size(float(ic.get('today', 0)))}"
            c.put(ix + iw - len(today), row, today, G4)
            row += 1
        if row < bottom:
            speed = float(ic.get("speed") or 0)
            limit = str(ic.get("limit", "off"))
            c.put(ix, row, f"▼ {fmt_rate(speed)}", G5 if status == "downloading" else G3)
            c.put(ix + 14, row, "sem limite" if limit == "off" else f"limite {limit}", G2 if limit == "off" else AMBER)
            if status == "downloading" and speed > 64 * 1024 and total > items and items:
                avg = float(ic.get("bytes", 0)) / items
                eta = fmt_uptime((total - items) * avg / speed)
                c.put(ix + iw - len(eta) - 4, row, f"ETA {eta}", CYAN)
            row += 1
        if row < bottom:
            if status == "downloading" and ic.get("current"):
                name = str(ic["current"])
                room = iw - 2
                if len(name) > room:
                    name = "~" + name[-(room - 1):]
                c.put(ix, row, "»", G4)
                c.put(ix + 2, row, name, TEXT)
            elif status == "idle" and ic.get("next_check"):
                mins = max(0, int((float(ic["next_check"]) - time.time()) // 60))
                c.put(ix, row, f"próxima verificação em {mins} min", G4)
            elif status == "login":
                c.put(ix, row, "abra http://<servidor>:8090 e faça o login", AMBER)
            elif status == "paused":
                c.put(ix, row, "P retoma o download", G2)
            row += 1
        if row < bottom:
            c.put(ix, row, "P pausar/retomar · C → ICLOUD p/ limite", G1)
