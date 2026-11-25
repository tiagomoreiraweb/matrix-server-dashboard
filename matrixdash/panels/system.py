"""CPU, memory, temperature, load and disks."""

from __future__ import annotations

from ..fmt import fmt_size, fmt_uptime
from ..models import Snapshot
from ..render.canvas import Canvas
from ..render.widgets import bar
from ..theme import G0, G1, G2, G3, G4, G5, G6, TEXT
from .base import Panel


class SystemPanel(Panel):
    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        ix, iw, bottom = self.frame(c, x, y, w, h, "▸ SYSTEM // TELEMETRY", f"{s.cores} CORES", t * 14 + 30)
        bw = max(8, iw - 30)
        row = y + 1

        def line(label: str, pct: float, metric: str, extra: str = "", phase: float = 0.0):
            nonlocal row
            if row >= bottom:
                return
            val = self.d.ease(label, pct)
            style = self.d.level_style(metric, pct)
            c.put(ix, row, label, G3)
            bar(c, ix + 7, row, bw, val, t, style, phase)
            c.put(ix + 8 + bw, row, f"{val:5.1f}%", style if style != G5 else G6)
            if extra:
                c.put(ix + 15 + bw, row, extra[: max(0, iw - bw - 15)], TEXT)
            row += 1

        line("CPU", s.cpu, "cpu", f"load {s.load[0]:.2f}")
        if row < bottom and s.per_core:
            per_w = max(18, iw // max(1, min(len(s.per_core), 4)))
            core_bw = max(4, per_w - 13)
            for idx, pct in enumerate(s.per_core[:4]):
                cx = ix + idx * per_w
                if cx + per_w > ix + iw + 1:
                    break
                val = self.d.ease(f"core{idx}", pct)
                c.put(cx, row, f"c{idx}", G2)
                bar(c, cx + 3, row, core_bw, val, t, self.d.level_style("cpu", pct), idx * 7)
                c.put(cx + 4 + core_bw, row, f"{val:3.0f}%", G4)
            row += 1

        graph_h = 3 if h >= 15 else 2 if h >= 12 else 0
        if graph_h and row + graph_h < bottom:
            rows = self.d.graph("cpu", s.cpu_hist, iw, graph_h, 100.0)
            c.put(ix, row + graph_h - 1, "·" * iw, G0)
            for r, text in enumerate(rows):
                c.put_sparse(ix, row + r, text, G5 if r == 0 else G4 if r < graph_h - 1 else G3)
            label = f" cpu · last {iw}s "
            c.put(ix + iw - len(label), row, label, G2)
            row += graph_h

        line("RAM", s.ram, "ram", f"{fmt_size(s.ram_used)} / {fmt_size(s.ram_total)}", 9)
        if s.swap_total:
            line("SWAP", s.swap, "ram", f"{fmt_size(s.swap_used)} / {fmt_size(s.swap_total)}", 17)
        if s.temperature is not None:
            if row < bottom:
                temp = self.d.ease("temp", s.temperature)
                style = self.d.level_style("temperature", s.temperature)
                c.put(ix, row, "TEMP", G3)
                bar(c, ix + 7, row, bw, temp, t, style, 23)
                c.put(ix + 8 + bw, row, f"{temp:5.1f}°C", style if style != G5 else G6)
                row += 1
        if row < bottom:
            c.put(ix, row, "LOAD", G3)
            c.put(ix + 7, row, f"{s.load[0]:.2f}  {s.load[1]:.2f}  {s.load[2]:.2f}", TEXT)
            c.put(ix + 30, row, "PROCS", G3)
            c.put(ix + 36, row, str(s.procs), TEXT)
            if iw > 60:
                c.put(ix + 44, row, "UP", G3)
                c.put(ix + 47, row, fmt_uptime(s.uptime_s), TEXT)
            row += 1
        if row < bottom - len(s.disks):
            c.put(ix, row, "┄" * iw, G1)
            row += 1
        for mount, pct, used, total in s.disks:
            if row >= bottom:
                break
            label = mount if len(mount) <= 6 else "~" + mount[-5:]
            val = self.d.ease(f"disk{mount}", pct)
            style = self.d.level_style("disk", pct)
            c.put(ix, row, label, G3)
            bar(c, ix + 7, row, bw, val, t, style, 31)
            c.put(ix + 8 + bw, row, f"{val:5.1f}%", style if style != G5 else G6)
            c.put(ix + 15 + bw, row, f"{fmt_size(used)} / {fmt_size(total)}"[: max(0, iw - bw - 15)], TEXT)
            row += 1
