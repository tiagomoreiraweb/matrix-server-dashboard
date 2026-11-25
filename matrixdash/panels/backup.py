"""External backup progress."""

from __future__ import annotations

import time

from ..fmt import fmt_rate, fmt_size, fmt_uptime
from ..integrations import BackupIntegration
from ..models import Snapshot
from ..render.canvas import Canvas
from ..render.widgets import bar
from ..theme import AMBER, CYAN, G0, G2, G3, G4, G5, G6, RED, SPINNER, TEXT
from .base import Panel


class BackupPanel(Panel):
    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float, page: str = ""):
        b = s.backup or {"status": "not_started"}
        status = str(b.get("status", "not_started"))
        phase = str(b.get("phase", ""))
        run = b.get("run") or {}
        blink = int(t * 2) % 2 == 0
        spin = SPINNER[int(t * 10) % 4]
        if status == "running":
            label, style = {
                "scanning": (f"{spin} SCANNING", AMBER),
                "comparing": (f"{spin} COMPARING", CYAN),
            }.get(phase, (f"{spin} UPLOADING", G5))
        else:
            label, style = {
                "done": ("● IN SYNC", G5),
                "idle": ("● WAITING", G4),
                "paused": ("● PAUSED", AMBER),
                "limit": ("● DAILY LIMIT", AMBER),
                "error": ("● ERROR", RED),
                "stalled": ("● STOPPED", RED if blink else G0),
                "not_started": ("● NOT STARTED", G2),
            }.get(status, (f"● {status.upper()}", G3))
        ix, iw, bottom = self.frame(c, x, y, w, h, "▸ BACKUP // GOOGLE DRIVE", page, t * 14 + 200, border=RED if status in ("error", "stalled") else G2)
        row = y + 1
        dest = str(b.get("dest", "")).split(":", 1)[-1] or "Google Drive"
        c.put(ix, row, label, style)
        route = f"{b.get('source', '/data')} → {dest}"
        c.put(ix + iw - len(route), row, route[: max(0, iw - len(label) - 2)], G2)
        row += 1

        total = float(b.get("source_bytes") or 0)
        done = float(b.get("uploaded_bytes") or 0)
        if b.get("initial_complete"):
            done = total
        pct = min(100.0, done / total * 100) if total else 0.0
        if row < bottom:
            bw = iw - 8
            bar(c, ix, row, bw, self.d.ease("backup", pct), t, G5 if status != "error" else RED)
            c.put(ix + bw + 1, row, f"{pct:5.1f}%", G6)
            row += 1
        if row < bottom:
            c.put(ix, row, f"{fmt_size(done)} / {fmt_size(total)}" if total else "scanning source", TEXT)
            today = (b.get("today") or {})
            if today.get("date") == time.strftime("%Y-%m-%d"):
                label_today = f"today {fmt_size(float(today.get('bytes', 0)))}"
                c.put(ix + iw - len(label_today), row, label_today, G4)
            row += 1
        if row < bottom:
            if status == "running":
                speed = float(run.get("speed") or 0)
                limit = str(run.get("bwlimit") or "")
                c.put(ix, row, f"▲ {fmt_rate(speed)}", G5)
                if self.d.integration(BackupIntegration).turbo_on():
                    c.put(ix + 14, row, "TURBO" if blink else "     ", AMBER)
                    c.put(ix + 20, row, "sem limite", AMBER)
                elif limit:
                    c.put(ix + 14, row, ("sem limite" if limit == "off" else f"limite {limit}")[:18], G2)
                if total > done:
                    # Average speed is meaningless while Drive is still creating folders.
                    secs = (total - done) / speed if speed >= 64 * 1024 else None
                    eta = fmt_uptime(secs) if secs is not None and secs < 90 * 86400 else "--"
                    c.put(ix + iw - len(eta) - 4, row, f"ETA {eta}", CYAN)
            else:
                last = b.get("last_run") or {}
                if last:
                    when = time.strftime("%d/%m %H:%M", time.localtime(float(last.get("ended", 0))))
                    c.put(ix, row, f"last run {when} · {last.get('result', '?')}"[:iw], G3)
                else:
                    c.put(ix, row, "waiting for first run", G2)
            row += 1
        if row < bottom:
            files = run.get("transferring") or []
            if status == "running" and files:
                cur = files[int(t / 3) % len(files)]
                name = str(cur.get("name", ""))
                tail = f" {int(cur.get('percentage', 0)):3d}%"
                room = iw - 2 - len(tail)
                if len(name) > room:
                    name = "~" + name[-(room - 1):]
                c.put(ix, row, "»", G4)
                c.put(ix + 2, row, name, TEXT)
                c.put(ix + iw - len(tail), row, tail, G4)
            elif status == "running":
                c.put(ix, row, f"checked {run.get('checks', 0)} files · copied {run.get('transfers', 0)}"[:iw], G3)
            elif status == "paused":
                c.put(ix, row, "resume: rm ~/backup-gdrive/PAUSE"[:iw], G2)
            elif status == "done" and b.get("last_success"):
                when = time.strftime("%d/%m %H:%M", time.localtime(float(b["last_success"])))
                c.put(ix, row, f"in sync since {when}"[:iw], G4)
            row += 1
        if row < bottom:
            errors = int(run.get("errors", 0)) if run else int((b.get("last_run") or {}).get("errors", 0))
            if status == "running":
                info = f"copied {run.get('transfers', 0)} · checked {run.get('checks', 0)}"
            else:
                info = f"{b.get('source_files', 0)} files tracked" if b.get("source_files") else ""
            c.put(ix, row, info[: iw - 12], G2)
            err = f"errors {errors}"
            c.put(ix + iw - len(err), row, err, RED if errors else G2)
