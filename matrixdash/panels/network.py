"""Throughput graphs and internet latency."""

from __future__ import annotations

from ..fmt import fmt_rate
from ..models import Snapshot
from ..render.canvas import Canvas
from ..render.charts import heat_strip
from ..theme import AMBER, G0, G1, G2, G3, G4, G5, G6, RED, TEXT
from .base import Panel


class NetworkPanel(Panel):
    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        lan = (s.netmap or {}).get("lan") or {}
        n_on = sum(1 for d in lan.get("devices", []) if d["online"])
        ix, iw, bottom = self.frame(c, x, y, w, h, "▸ NETWORK // LIVE", f"{s.iface} · {n_on} disp · W mapa" if lan else s.iface, t * 14 + 60)
        row = y + 1
        down_hist, up_hist = s.down_hist[-iw:], s.up_hist[-iw:]
        down_peak = max(down_hist, default=0.0)
        up_peak = max(up_hist, default=0.0)
        if iw >= 70:
            c.put(ix, row, "▼ DOWN", G5)
            c.put(ix + 7, row, f"{fmt_rate(s.down):>11}", G6)
            c.put(ix + 20, row, f"peak {fmt_rate(down_peak)}", G2)
            half = ix + iw // 2 + 2
            c.put(half, row, "▲ UP", G3)
            c.put(half + 5, row, f"{fmt_rate(s.up):>11}", G5)
            c.put(half + 18, row, f"peak {fmt_rate(up_peak)}"[: max(0, ix + iw - half - 18)], G2)
        else:
            c.put(ix, row, "▼", G5)
            c.put(ix + 2, row, fmt_rate(s.down), G6)
            half = ix + iw // 2
            c.put(half, row, "▲", G3)
            c.put(half + 2, row, fmt_rate(s.up), G5)
            c.put(ix + iw - 8, row, f"last {iw}s"[:8], G1)
        row += 1
        graph_h = max(1, (h - 5) // 2)
        for name, hist, peak, styles in (("down", down_hist, down_peak, (G5, G4)), ("up", up_hist, up_peak, (G3, G2))):
            rows = self.d.graph(name, hist, iw, graph_h, max(peak, 1024.0))
            c.put(ix, row + graph_h - 1, "·" * iw, G0)
            for r, text in enumerate(rows):
                c.put_sparse(ix, row + r, text, styles[0] if r == 0 else styles[1])
            row += graph_h
        if row < bottom:
            blink = int(t * 2) % 2
            all_ok = s.net4 and s.net6 is not False
            dot = G5 if all_ok else AMBER if s.internet else (RED if blink else G0)
            c.put(ix, row, "●", dot)
            xx = ix + 2
            for fam, up, lat in (("v4", s.net4, s.lat4), ("v6", s.net6, s.lat6)):
                if up is None:
                    continue
                c.put(xx, row, fam, G3)
                label = f"{lat:.0f}ms" if up and lat is not None else "DOWN"
                c.put(xx + 3, row, label, TEXT if up else RED)
                xx += 4 + max(len(label), 5) + 1
            sx = ix + 26
            sw = ix + iw - sx
            if sw > 6:
                c.put(sx, row, heat_strip(s.lat_hist, sw, max(50.0, max(s.lat_hist[-sw:], default=0))), G3)
