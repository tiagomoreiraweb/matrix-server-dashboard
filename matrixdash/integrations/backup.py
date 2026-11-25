"""Status of an external backup script (rclone, restic...) that writes a JSON state file.

The folder of that file is also the control folder: PAUSE, RUN_NOW and TURBO
files created by the hotkeys B, S and V. See docs/INTEGRACOES.md.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .. import validators
from ..models import Snapshot
from ..storage import write_json
from ..theme import AMBER, CYAN, G4, G5, RED
from .base import Integration

EVENTS = {
    "running": ("backup started", CYAN), "done": ("backup complete, drive in sync", G5),
    "paused": ("backup paused", AMBER), "limit": ("daily upload limit reached", AMBER),
    "error": ("backup finished with errors", RED), "stalled": ("backup process stopped responding", RED),
    "idle": ("backup waiting", G4),
}


class BackupIntegration(Integration):
    key = "backup"
    hotkeys = ("B", "S", "V")

    def __init__(self, collector):
        super().__init__(collector)
        state = str(self.config.get("backup_state") or "")
        self.path = Path(os.path.expanduser(state)) if state else None
        self.dir = self.path.parent if self.path else None
        self.data: dict[str, Any] | None = None
        self.prev_status: str | None = None

    def enabled(self) -> bool:
        return self.dir is not None

    # --- collection

    def prime(self):
        self.read()

    def collect_fast(self, tick: int):
        if tick % 2 == 0:
            self.read()

    def read(self):
        if not self.path:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.data = {"status": "not_started"}
            return
        except (OSError, ValueError):
            return
        # The wrapper writes every 5 s while running; a stale file means it died.
        if data.get("status") == "running" and time.time() - float(data.get("updated", 0)) > 90:
            data["status"] = "stalled"
        self.data = data

    def fill(self, s: Snapshot):
        s.backup = self.data

    def detect_events(self, s: Snapshot):
        if s.backup is None:
            return
        status = str(s.backup.get("status", ""))
        if self.prev_status is not None and status != self.prev_status:
            text, style = EVENTS.get(status, (f"backup {status}", G4))
            self.emit("BACKUP", text, style)
        self.prev_status = status

    # --- screen

    def turbo_on(self) -> bool:
        return bool(self.dir and (self.dir / "TURBO").exists())

    def ticker(self, s: Snapshot) -> list[str]:
        b = s.backup
        if not b or b.get("status") == "not_started":
            return []
        if b.get("initial_complete") and b.get("status") != "running":
            return ["GOOGLE DRIVE BACKUP IN SYNC"]
        total = float(b.get("source_bytes") or 0)
        pct = min(100.0, float(b.get("uploaded_bytes") or 0) / total * 100) if total else 0.0
        turbo = " · TURBO" if self.turbo_on() else ""
        return [f"BACKUP {pct:.1f}% · {str(b.get('status', '')).upper()}{turbo}"]

    def key_label(self, key: str, s: Snapshot, dash) -> str | None:
        if key == "B":
            return "retomar backup" if str((s.backup or {}).get("status", "")) == "paused" else "pausar backup"
        if key == "V":
            return "limitar rede" if self.turbo_on() else "liberar rede"
        return None

    # --- hotkeys

    def handle_key(self, key: str, dash) -> bool:
        actions = {"b": self.toggle_pause, "s": self.run_now, "v": self.toggle_turbo}
        if key not in actions:
            return False
        if not self.dir or not self.dir.exists():
            dash.notify("backup não configurado", AMBER)
        else:
            actions[key](dash)
        return True

    def toggle_pause(self, dash):
        pause = self.dir / "PAUSE"
        try:
            if pause.exists():
                pause.unlink()
                (self.dir / "RUN_NOW").touch()
                dash.notify("backup retomado · inicia em até 1 min", G5)
                self.emit("BACKUP", "retomado pelo teclado", G5)
            else:
                pause.touch()
                dash.notify("backup pausado · B de novo para retomar", AMBER)
                self.emit("BACKUP", "pausado pelo teclado", AMBER)
        except OSError as exc:
            dash.notify(f"erro: {exc}"[:60], RED)

    def toggle_turbo(self, dash):
        turbo = self.dir / "TURBO"
        try:
            if turbo.exists():
                turbo.unlink()
                dash.notify("rede LIMITADA · backup volta aos horários (3M dia / 8M noite)", G5, 5)
                self.emit("BACKUP", "banda limitada pelo teclado", G5)
            else:
                turbo.touch()
                dash.notify("rede LIBERADA · backup sem limite · V de novo para limitar", AMBER, 5)
                self.emit("BACKUP", "turbo: banda liberada pelo teclado", AMBER)
        except OSError as exc:
            dash.notify(f"erro: {exc}"[:60], RED)

    def run_now(self, dash):
        status = str((self.collector.snap.backup or {}).get("status", ""))
        if status == "running":
            dash.notify("backup já está rodando", G4)
            return
        try:
            (self.dir / "PAUSE").unlink(missing_ok=True)
            (self.dir / "RUN_NOW").touch()
        except OSError as exc:
            dash.notify(f"erro: {exc}"[:60], RED)
            return
        dash.notify("sincronização solicitada · inicia em até 1 min", G5)
        self.emit("BACKUP", "sincronização manual solicitada", CYAN)

    # --- settings menu

    def settings_path(self) -> Path | None:
        return self.dir / "backup.json" if self.dir else None

    def menu_load(self, values: dict[str, str]):
        path = self.settings_path()
        bcfg = {}
        if path and path.exists():
            try:
                bcfg = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                bcfg = {}
        slots = []
        for part in str(bcfg.get("bwlimit", "08:00,3M 23:00,8M")).split():
            if "," in part:
                slots.append(part.split(",", 1))
        if len(slots) >= 2:
            (values["bk_day_from"], values["bk_day_rate"]), (values["bk_night_from"], values["bk_night_rate"]) = \
                slots[0], slots[1]
        else:
            values.update(bk_day_from="08:00", bk_day_rate="3M", bk_night_from="23:00", bk_night_rate="8M")
        values["bk_daily"] = str(bcfg.get("daily_sync_at", "02:00"))

    def menu(self, m):
        path = self.settings_path()
        if not (path and path.exists()):
            return
        save = lambda: self.save_settings(m.menu)  # noqa: E731
        m.header("BACKUP GOOGLE DRIVE", "vale na hora, sem reiniciar o backup")
        m.field("bk_day_rate", "Limite de dia", "ex.: 3M (MB/s) · off = sem limite", validators.rate, save)
        m.field("bk_day_from", "Dia começa às", "HH:MM", validators.clock, save)
        m.field("bk_night_rate", "Limite de noite", "ex.: 8M (MB/s) · off = sem limite", validators.rate, save)
        m.field("bk_night_from", "Noite começa às", "HH:MM", validators.clock, save)
        m.field("bk_daily", "Sincronização diária às", "HH:MM · depois da cópia inicial", validators.clock, save)

    def save_settings(self, menu):
        path = self.settings_path()
        if not path:
            return
        v = menu.values
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            cfg["bwlimit"] = (f"{v['bk_day_from']},{v['bk_day_rate'].upper().replace('OFF', 'off')} "
                              f"{v['bk_night_from']},{v['bk_night_rate'].upper().replace('OFF', 'off')}")
            cfg["daily_sync_at"] = v["bk_daily"]
            write_json(path, cfg, indent=2)
            menu.message = ("backup salvo · limite novo vale em segundos", G5)
            self.emit("CONFIG", f"backup: {cfg['bwlimit']} · diário {cfg['daily_sync_at']}", CYAN)
        except (OSError, ValueError) as exc:
            menu.message = (f"erro ao salvar: {exc}"[:70], RED)
