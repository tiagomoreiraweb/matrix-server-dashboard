"""Containers, host services and probes."""

from __future__ import annotations

import math

from ..models import Container, Snapshot
from ..render.canvas import Canvas
from ..render.widgets import section
from ..theme import AMBER, G0, G1, G2, G3, G4, G5, G6, RED, TEXT
from .base import Panel


class ServiceRows:
    """Cursor and column layout of the services panel, shared with the sections that integrations add."""

    def __init__(self, c: Canvas, ix: int, iw: int, row: int, bottom: int, wide: bool, name_w: int,
                 col_state: int, col_up: int):
        self.c, self.ix, self.iw, self.row, self.bottom = c, ix, iw, row, bottom
        self.wide, self.name_w, self.col_state, self.col_up = wide, name_w, col_state, col_up

    def heading(self, label: str, right: str = "", style: int = G4):
        if self.row < self.bottom:
            section(self.c, self.ix, self.row, self.iw, label, right, style)
            self.row += 1


class ServicesSection:
    """Extra block at the end of the services panel (e.g. the Claude Code agent)."""

    def reserve(self, s: Snapshot) -> int:
        """Rows to keep free for this section when the container list is long."""
        return 0

    def draw(self, rows: ServiceRows, s: Snapshot, t: float):
        raise NotImplementedError


class ServicesPanel(Panel):
    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        running = sum(1 for ct in s.containers if ct.state == "running")
        active = sum(1 for _, _, st in s.units if st == "active")
        right = f"{running}/{len(s.containers)} UP"
        sources = " · ".join(label for _, label, _ in s.runtimes) or "DOCKER"
        ix, iw, bottom = self.frame(c, x, y, w, h, f"▸ SERVICES // {sources} · HOST · AI", right, t * 14 + 140)
        row = y + 1
        blink = int(t * 2) % 2 == 0
        wide = iw >= 70

        def heading(label: str, right_label: str = "", style: int = G4):
            nonlocal row
            if row < bottom:
                section(c, ix, row, iw, label, right_label, style)
                row += 1

        # Column layout: dot name state up health cpu mem endpoint
        name_w = 17 if wide else 15
        col_state = ix + 2 + name_w + 1
        col_up = col_state + 9
        col_health = col_up + 6
        col_cpu = col_health + 10
        col_mem = col_cpu + 7
        col_probe = col_mem + 7

        heading("CONTAINERS", f"{running}/{len(s.containers)} running")
        down = [name for name, _, ok in s.runtimes if not ok]
        if not s.docker_ok or (down and row < bottom - 1):
            c.put(ix + 2, row, f"{' · '.join(down) or 'docker'} unavailable", RED)
            row += 1
        if s.docker_ok:
            if row < bottom:
                c.put(ix + 2, row, "NAME", G2)
                c.put(col_state, row, "STATE", G2)
                c.put(col_up, row, "AGE", G2)
                c.put(col_health, row, "HEALTH", G2)
                if wide:
                    c.put(col_cpu, row, "CPU", G2)
                    c.put(col_mem, row, "MEM", G2)
                    c.put(col_probe, row, "ENDPOINT", G2)
                row += 1

            def order(ct: Container):
                bad = ct.state != "running" or ct.health == "unhealthy"
                return (0 if ct.name in s.flagged else 1 if bad and ct.state != "exited" else 2 if ct.state == "running" else 3, ct.name)

            containers = sorted(s.containers, key=order)
            reserve = 3 + len(s.units) + sum(sec.reserve(s) for sec in self.d.service_sections())
            room = max(1, bottom - row - reserve)
            shown = containers
            scroll = None
            if len(containers) > room and room > 2:
                # Not everything fits: keep problem containers pinned on top and
                # let the others scroll one row every few seconds, wrapping around.
                slots = room - 1
                pinned = [ct for ct in containers if order(ct)[0] < 2][: max(0, slots - 2)]
                rest = [ct for ct in containers if ct not in pinned]
                visible = slots - len(pinned)
                start = int(t / 2.5) % len(rest)
                shown = pinned + [rest[(start + i) % len(rest)] for i in range(min(visible, len(rest)))]
                scroll = (start, visible, len(rest), len(pinned))
            for idx, ct in enumerate(shown):
                if row >= bottom:
                    break
                flagged = ct.name in s.flagged
                if ct.state == "running" and ct.health in ("", "healthy"):
                    pulse = (math.sin(t * 2.2 + idx * 0.9) + 1) / 2
                    dot_style, state_style, state = (G6 if pulse > 0.7 else G5 if pulse > 0.3 else G4), G5, "RUNNING"
                elif ct.state == "running":
                    dot_style, state_style = AMBER if ct.health == "starting" else RED, AMBER if ct.health == "starting" else RED
                    state = "RUNNING"
                elif ct.state in ("restarting", "dead") or flagged or ct.health == "unhealthy":
                    dot_style = RED if blink else G0
                    state_style, state = RED, ct.state.upper()[:8]
                elif ct.state == "exited":
                    dot_style, state_style, state = AMBER, AMBER, "STOPPED"
                else:
                    dot_style, state_style, state = G2, G2, ct.state.upper()[:8]
                c.put(ix, row, "●", dot_style)
                c.put(ix + 2, row, ct.short[:name_w], TEXT if ct.state == "running" else G3)
                c.put(col_state, row, state, state_style)
                c.put(col_up, row, ct.age, G4 if ct.state == "running" else G2)
                if ct.state == "exited":
                    c.put(col_health, row, f"exit {ct.exit_code}"[:9], AMBER if ct.exit_code not in ("", "0") else G2)
                elif ct.health:
                    hs = G5 if ct.health == "healthy" else AMBER if ct.health == "starting" else RED
                    c.put(col_health, row, ct.health[:9], hs)
                else:
                    c.put(col_health, row, "-", G1)
                if wide:
                    if ct.cpu is not None:
                        c.put(col_cpu, row, f"{ct.cpu:4.1f}%", AMBER if ct.cpu > 50 else G4)
                    else:
                        c.put(col_cpu, row, "-", G1)
                    c.put(col_mem, row, ct.mem or "-", G4 if ct.mem else G1)
                    probe = s.probes.get(ct.name)
                    if probe and ct.state == "running":
                        ok, code, ms, _ = probe
                        if ok:
                            label = f"{code} {ms:.0f}ms" if code else f"tcp {ms:.0f}ms"
                            c.put(col_probe, row, label[: ix + iw - col_probe], G5)
                        else:
                            c.put(col_probe, row, "NO REPLY", RED if blink else AMBER)
                    else:
                        c.put(col_probe, row, ct.ports[: ix + iw - col_probe], G2)
                row += 1
            if scroll and row < bottom:
                start, visible, total, pinned_n = scroll
                first, last = start + 1, (start + visible - 1) % total + 1
                label = f"↓ rolando · {first}-{last} de {total}"
                if pinned_n:
                    label += f" · {pinned_n} com problema fixo{'s' if pinned_n > 1 else ''} no topo"
                c.put(ix + 2, row, label[: iw - 4], G2)
                # Position marker of the scroll window.
                bar_w = 12
                pos = int(start / max(1, total) * bar_w)
                c.put(ix + iw - bar_w, row, "·" * bar_w, G1)
                c.put(ix + iw - bar_w + pos, row, "█", G4)
                row += 1

        if s.units and row < bottom - 1:
            row += 1 if bottom - row > len(s.units) + 6 else 0
            heading("HOST", f"{active}/{len(s.units)} active")
            for label, unit, state in s.units:
                if row >= bottom:
                    break
                ok = state == "active"
                state_label, state_style = state.upper()[:8], G5 if ok else RED
                detail, detail_style = unit, G2
                if ok:
                    # An integration can tell more about its own unit (tailscaled, wg-quick@wg0...).
                    for integ in self.d.integrations:
                        view = integ.unit_view(unit, s)
                        if view:
                            ok, state_label, state_style, detail, detail_style = view
                            break
                c.put(ix, row, "●", (G5 if (math.sin(t * 2 + row) > -0.3) else G4) if ok else (RED if blink else G0))
                c.put(ix + 2, row, label[:name_w], TEXT)
                c.put(col_state, row, state_label, state_style)
                c.put(col_up + (2 if len(state_label) > 8 else 0), row, detail[: iw - (col_up - ix) - 2], detail_style)
                row += 1
            for key, (ok, code, ms, name) in s.probes.items():
                if row >= bottom or any(ct.name == key for ct in s.containers):
                    continue
                c.put(ix, row, "●", G5 if ok else RED)
                c.put(ix + 2, row, name[:name_w], TEXT)
                c.put(col_state, row, "UP" if ok else "DOWN", G5 if ok else RED)
                if ms is not None:
                    c.put(col_up, row, f"{code or 'tcp'} {ms:.0f}ms", G4)
                row += 1

        rows = ServiceRows(c, ix, iw, row, bottom, wide, name_w, col_state, col_up)
        for sec in self.d.service_sections():
            if rows.row >= bottom - 1:
                break
            sec.draw(rows, s, t)
