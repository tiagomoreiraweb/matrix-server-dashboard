"""Photos downloaded from iCloud by an icloudpd container: progress, speed, login state and bandwidth limit."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from .. import ROOT
from ..config import save_user_config
from ..models import Snapshot
from ..theme import AMBER, CYAN, G4, G5, RED
from .base import Integration

DAY_FILE = ROOT / ".icloud_day.json"
LIMITS = ["off", "1M", "2M", "3M", "5M"]
EVENTS = {
    "downloading": ("icloud: baixando fotos", CYAN),
    "idle": ("icloud: tudo baixado, aguardando novidades", G5),
    "paused": ("icloud: download pausado", AMBER),
    "login": ("icloud: precisa de novo login (porta 8090)", RED),
}
AUTH_ERROR_RE = re.compile(r"(?i)(invalid email|password|authenticat|two-factor|2fa|mfa).*(fail|invalid|required|expired|error)")


def limit_label(limit: str) -> str:
    return "sem limite" if limit == "off" else limit + "B/s"


class ICloudIntegration(Integration):
    key = "icloud"
    hotkeys = ("P",)

    def __init__(self, collector):
        super().__init__(collector)
        self.data: dict[str, Any] | None = None
        self.prev: tuple[float, int] | None = None
        self.speed = 0.0
        self.day = ("", 0)
        # (container start time, limit) last applied, so a restarted container gets the limit again
        self.applied: tuple[str, str] | None = None
        self.prev_status: str | None = None

    def cfg(self) -> dict[str, Any]:
        return self.config.get("icloud") or {}

    def container(self) -> str:
        return str(self.cfg().get("container") or "")

    def enabled(self) -> bool:
        return bool(self.container())

    # --- collection

    def collect_slow(self):
        self.read()

    def apply_limit(self, name: str, limit: str) -> bool:
        """Shape the download of the iCloud container inside its own network namespace."""
        script = "tc qdisc del dev eth0 ingress 2>/dev/null; "
        if limit.lower() != "off":
            mbytes = float(limit.rstrip("Mm"))
            script += ("tc qdisc add dev eth0 handle ffff: ingress && "
                       f"tc filter add dev eth0 parent ffff: protocol all u32 match u32 0 0 "
                       f"police rate {int(mbytes * 8)}mbit burst 1m drop flowid :1")
        else:
            script += "true"
        rt = self.collector.runtime_for(name)
        return bool(rt and rt.run_sidecar(name, "matrix-tc", script, timeout=30.0))

    def folder_size(self, folder: str) -> tuple[int, int]:
        items = total_bytes = 0
        for root, _, files in os.walk(folder):
            for fname in files:
                try:
                    total_bytes += os.lstat(os.path.join(root, fname)).st_size
                except OSError:
                    continue
                # Live Photos are saved as photo + "_HEVC.MOV"; count them once.
                if not fname.upper().endswith("_HEVC.MOV"):
                    items += 1
        return items, total_bytes

    def day_start(self, total_bytes: int) -> int:
        """Folder size at the start of today, persisted so "today" survives dashboard restarts."""
        today = time.strftime("%Y-%m-%d")
        if self.day[0] != today:
            try:
                saved = json.loads(DAY_FILE.read_text())
            except (OSError, ValueError):
                saved = {}
            if saved.get("date") == today:
                self.day = (today, int(saved.get("bytes", total_bytes)))
            else:
                self.day = (today, total_bytes)
                try:
                    DAY_FILE.write_text(json.dumps({"date": today, "bytes": total_bytes}))
                except OSError:
                    pass
        return self.day[1]

    def read(self):
        cfg = self.cfg()
        name = self.container()
        if not name:
            return
        items, total_bytes = self.folder_size(str(cfg.get("folder") or "/data/fotos/icloud"))
        now = time.monotonic()
        if self.prev is not None and now > self.prev[0]:
            inst = max(0.0, (total_bytes - self.prev[1]) / (now - self.prev[0]))
            self.speed = inst if not self.speed else self.speed * 0.5 + inst * 0.5
        self.prev = (now, total_bytes)
        start = self.day_start(total_bytes)

        rt = self.collector.runtime_for(name)
        state, started = rt.state(name) if rt else ("missing", "")
        prev = self.data or {}
        info: dict[str, Any] = {
            "container": name, "state": state, "items": items, "bytes": total_bytes,
            "total": prev.get("total", 0), "speed": self.speed if state == "running" else 0.0,
            "today": total_bytes - start, "current": prev.get("current", ""),
            "limit": str(cfg.get("limit", "off")), "status": "paused" if state != "running" else "starting",
            "next_check": None,
        }
        if state == "running":
            info["status"] = self.parse_logs(rt.logs(name, since="3h", tail=4000, timeout=8) if rt else [], info)
            if not info["total"]:
                # The "Downloading N" line may be older than the window above.
                found = re.findall(r"Downloading (\d+) original", "\n".join(rt.logs(name, timeout=30)) if rt else "")
                if found:
                    info["total"] = int(found[-1])
            desired = info["limit"]
            if self.applied != (started, desired):
                if self.apply_limit(name, desired):
                    self.applied = (started, desired)
        self.data = info

    @staticmethod
    def parse_logs(lines: list[str], info: dict[str, Any]) -> str:
        """Status from the icloudpd log; also fills total, current file and next check in `info`."""
        status, last_ts, auth_error = "starting", "", False
        for line in lines:
            if "DEBUG" in line[:30]:
                if "Authenticating" in line:
                    last_ts = line[:19]
                    status = "authenticating"
                continue
            m = re.search(r"Downloading (\d+) original", line)
            if m:
                info["total"] = int(m.group(1))
                status, auth_error = "downloading", False
            m = re.search(r"Downloaded /data/(.+)$", line)
            if m:
                info["current"] = m.group(1).strip()
                status, auth_error = "downloading", False
            m = re.search(r"Waiting for (\d+) sec", line)
            if m:
                status = "idle"
                try:
                    ts = time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S"))
                    info["next_check"] = ts + int(m.group(1))
                except ValueError:
                    pass
            if AUTH_ERROR_RE.search(line):
                auth_error = True
        if status == "authenticating" and last_ts:
            try:
                waited = time.time() - time.mktime(time.strptime(last_ts, "%Y-%m-%d %H:%M:%S"))
                if waited > 180:
                    auth_error = True
            except ValueError:
                pass
        return "login" if auth_error and status != "downloading" else status

    def fill(self, s: Snapshot):
        s.icloud = self.data

    def detect_events(self, s: Snapshot):
        if s.icloud is None:
            return
        status = str(s.icloud.get("status", ""))
        if self.prev_status is not None and status != self.prev_status:
            text, style = EVENTS.get(status, (f"icloud: {status}", G4))
            self.emit("ICLOUD", text, style)
        self.prev_status = status

    # --- screen

    def ticker(self, s: Snapshot) -> list[str]:
        ic = s.icloud or {}
        if not ic.get("total"):
            return []
        pct = min(100.0, ic.get("items", 0) / ic["total"] * 100)
        return [f"ICLOUD {pct:.1f}% · {ic.get('items', 0)}/{ic['total']} ITENS"]

    def alerts(self, s: Snapshot) -> list[str]:
        if (s.icloud or {}).get("status") == "login":
            return ["ICLOUD PRECISA DE LOGIN - ABRA A PORTA 8090"]
        return []

    def key_label(self, key: str, s: Snapshot, dash) -> str | None:
        if key == "P":
            return "retomar icloud" if str((s.icloud or {}).get("state", "running")) != "running" else "pausar icloud"
        return None

    # --- actions

    def handle_key(self, key: str, dash) -> bool:
        if key != "p":
            return False
        self.toggle(dash)
        return True

    def toggle(self, dash):
        name = self.container()
        if not name:
            dash.notify("download do iCloud não configurado", AMBER)
            return
        running = str((self.collector.snap.icloud or {}).get("state", "")) == "running"
        verb, cmd = ("pausado", "stop") if running else ("retomado", "start")

        def run():
            rt = self.collector.runtime_for(name)
            if rt and rt.action(name, cmd, timeout=60):
                dash.notify(f"download do iCloud {verb}", AMBER if cmd == "stop" else G5)
                self.emit("ICLOUD", f"download {verb} pelo teclado", AMBER if cmd == "stop" else G5)
                self.read()
            else:
                dash.notify(f"falha ao {cmd} {name}", RED)

        dash.notify("pausando o download do iCloud..." if running else "retomando o download do iCloud...", CYAN, 3)
        threading.Thread(target=run, daemon=True).start()

    def set_limit(self, config_path: Path, limit: str) -> str | None:
        """Save a new download limit and apply it now; returns an error text."""
        cfg = self.config.setdefault("icloud", {})
        cfg["limit"] = limit
        try:
            save_user_config(config_path, lambda raw: raw.setdefault("icloud", {}).update({"limit": limit}),
                             create=False)
        except (OSError, ValueError) as exc:
            return f"erro ao salvar: {exc}"
        name = str(cfg.get("container") or "")

        def run():
            if self.apply_limit(name, limit):
                self.applied = None  # re-checked by the collector with the new value
                self.emit("ICLOUD", f"limite de download: {limit_label(limit)}", CYAN)
        threading.Thread(target=run, daemon=True).start()
        return None

    # --- settings menu

    def menu_load(self, values: dict[str, str]):
        values["ic_limit"] = str(self.cfg().get("limit", "off"))

    def menu(self, m):
        if not self.enabled():
            return
        menu = m.menu
        ic = self.collector.snap.icloud or {}
        m.header("ICLOUD → SERVIDOR", f"{ic.get('items', 0)}/{ic.get('total', 0) or '?'} itens · {ic.get('status', '-')}")

        def save():
            limit = menu.values["ic_limit"]
            err = self.set_limit(menu.d.config_path, limit)
            menu.message = (err, RED) if err else (f"limite do iCloud: {limit_label(limit)}", G5)

        def toggle():
            self.toggle(menu.d)
            menu.message = ("aguarde alguns segundos...", CYAN)

        m.field("ic_limit", "Limite de download", "a Apple entrega ~5 MB/s · limite vale na hora",
                None, save, "choice", LIMITS)
        running = ic.get("state") == "running"
        m.action("Retomar download" if not running else "Pausar download",
                 "para/liga o container do iCloud (mesmo que a tecla P)", toggle, AMBER)
