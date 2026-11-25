"""Boot sequence shown while the first data arrives."""

from __future__ import annotations

from .. import VERSION
from ..fmt import fmt_size
from ..models import Snapshot
from ..render.canvas import Canvas
from ..render.widgets import bar
from ..theme import AMBER, G2, G4, G5, G6, RED, SPINNER, TEXT
from .base import Panel


class BootScreen(Panel):
    """Status lines typed one by one, then a progress bar; lasts duration() seconds."""

    def __init__(self, dash):
        super().__init__(dash)
        self.lines: list[tuple[str, str]] = []

    def build_lines(self, s: Snapshot):
        running = sum(1 for ct in s.containers if ct.state == "running")
        lines = [
            ("SYS", f"{self.d.config.get('brand') or 'MATRIX SECURE TERMINAL'} v{VERSION}  ::  node {s.hostname}"),
            ("OK", f"kernel {s.kernel}"),
            ("OK", f"cpu {s.cores} cores  //  memory {fmt_size(s.ram_total)}"),
        ]
        for mount, _, _, total in s.disks:
            lines.append(("OK", f"mount {mount:<8} {fmt_size(total)}"))
        runtimes = s.runtimes or [("docker", "DOCKER", s.docker_ok)]
        if len(runtimes) == 1:
            label = {rt.name: rt.boot_label for rt in self.d.collector.runtimes}.get(runtimes[0][0], "docker engine")
            lines.append(("OK" if runtimes[0][2] else "FAIL",
                          f"{label}  //  {running}/{len(s.containers)} containers running"))
        else:
            info = {rt.name: rt for rt in self.d.collector.runtimes}
            for name, _, ok in runtimes:
                mine = [ct for ct in s.containers if ct.runtime == name]
                up = sum(1 for ct in mine if ct.state == "running")
                rt = info.get(name)
                lines.append(("OK" if ok else "FAIL", f"{rt.boot_label if rt else name}  //  "
                              f"{up}/{len(mine)} {rt.boot_unit if rt else 'containers'} running"))
        active = sum(1 for _, _, st in s.units if st == "active")
        if s.units:
            lines.append(("OK" if active == len(s.units) else "WARN", f"host services  //  {active}/{len(s.units)} active"))
        lines.append(("OK", f"network {s.iface}  //  {s.ip}"))
        lines.append((
            "OK" if s.net4 and s.net6 is not False else "WARN" if s.internet else "FAIL",
            "uplink  //  " + "   ".join(f"{fam} " + (f"{lat:.0f} ms" if up and lat is not None else "down")
                                       for fam, up, lat in (("IPv4", s.net4, s.lat4), ("IPv6", s.net6, s.lat6))
                                       if up is not None),
        ))
        for integ in self.d.integrations:
            lines += integ.boot_lines(s)
        lines.append(("OK", "decrypting identity matrix"))
        lines.append(("SYS", f"LINK ESTABLISHED. WELCOME, {self.d.operator}."))
        self.lines = lines

    def duration(self) -> float:
        return 0.28 * len(self.lines) + 0.9

    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        bw = min(80, c.w - 4)
        bh = len(self.lines) + 7
        bx = (c.w - bw) // 2
        by = max(0, (c.h - bh) // 2)
        c.box(bx, by, bw, bh, "BOOT // INITIALIZING", "", G2, G5)
        c.pulse(bx, by, bw, bh, t * 40, 10)
        for i, (status, text) in enumerate(self.lines):
            started = i * 0.28
            if t < started:
                break
            visible = text[: int((t - started) * 110)]
            yy = by + 2 + i
            if status == "SYS":
                c.put(bx + 3, yy, visible, G6 if i else G5)
            else:
                tag_style = {"OK": G5, "WARN": AMBER, "FAIL": RED}[status]
                done = len(visible) == len(text)
                c.put(bx + 3, yy, "[      ]", G2)
                if done:
                    c.put(bx + 5, yy, f"{status:^4}", tag_style)
                else:
                    c.put(bx + 5, yy, SPINNER[int(t * 12) % 4], G4)
                c.put(bx + 12, yy, visible, TEXT if done else G4)
        progress = min(1.0, t / max(0.1, self.duration() - 0.5))
        pw = bw - 18
        bar(c, bx + 3, by + bh - 3, pw, progress * 100, t)
        c.put(bx + pw + 5, by + bh - 3, f"{progress * 100:5.1f}%", G5)
        if int(t * 3) % 2 == 0:
            c.put(bx + 3, by + bh - 2, "_", G5)
