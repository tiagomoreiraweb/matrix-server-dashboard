"""Claude Code: running agent processes, token usage and plan limits."""

from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

import psutil

from ..claude_usage import UsageTracker
from ..fmt import fmt_size
from ..models import ClaudeInfo, Snapshot
from ..theme import CYAN, G5
from .base import Integration


def claude_version_fallback() -> str:
    base = Path.home() / ".local/share/claude/versions"
    try:
        names = [p.name for p in base.iterdir() if re.fullmatch(r"[\d.]+", p.name)]
        names.sort(key=lambda v: tuple(int(x) for x in v.split(".")))
        return names[-1] if names else ""
    except OSError:
        return ""


class ClaudeIntegration(Integration):
    key = "claude"
    hotkeys = ("U",)

    def __init__(self, collector):
        super().__init__(collector)
        self.info = ClaudeInfo()
        self.procs: dict[int, psutil.Process] = {}
        self.idle_since = time.monotonic()
        self.hist: deque[float] = deque(maxlen=120)
        self.usage_tracker = UsageTracker()
        self.usage: dict[str, Any] | None = None
        self.usage_at = 0.0
        self.plan: dict[str, Any] | None = None
        self.prev_sessions: int | None = None

    def enabled(self) -> bool:
        return bool(self.config.get("claude"))

    # --- collection

    def prime(self):
        self.read_processes()
        self.read_usage()

    def collect_fast(self, tick: int):
        if tick % 2 == 0:
            self.read_processes()
        if tick % 5 == 0 or self.plan is None:
            self.read_plan_limits()

    def collect_slow(self):
        if self.enabled() and time.time() - self.usage_at > 55:
            self.read_usage()

    def read_processes(self):
        if not self.enabled():
            return
        info = ClaudeInfo()
        seen: set[int] = set()
        version = ""
        for proc in psutil.process_iter(["pid", "cmdline", "create_time"]):
            try:
                cmd = proc.info.get("cmdline") or []
                if not cmd:
                    continue
                exe = cmd[0]
                if os.path.basename(exe) != "claude" and "/claude/versions/" not in exe:
                    continue
                pid = proc.info["pid"]
                seen.add(pid)
                cached = self.procs.get(pid)
                if cached is None:
                    cached = proc
                    self.procs[pid] = proc
                    cached.cpu_percent(None)
                cpu = cached.cpu_percent(None)
                rss = cached.memory_info().rss
                info.procs += 1
                info.cpu += cpu
                info.rss += rss
                created = proc.info.get("create_time") or 0.0
                if not info.since or created < info.since:
                    info.since = created
                vm = re.search(r"/versions/([\d.]+)", exe)
                if vm:
                    version = vm.group(1)
                if "remote-control" in cmd:
                    if "--name" in cmd and cmd.index("--name") + 1 < len(cmd):
                        info.remote = cmd[cmd.index("--name") + 1]
                    else:
                        info.remote = "on"
                else:
                    info.sessions += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        for pid in list(self.procs):
            if pid not in seen:
                del self.procs[pid]
        info.running = info.procs > 0
        info.version = version or claude_version_fallback()
        info.working = info.running and info.cpu >= 4.0
        self.info = info

    def read_usage(self):
        if not self.enabled():
            return
        tracker = self.usage_tracker
        tracker.refresh()
        summary = tracker.summary()
        summary["hourly"] = tracker.hourly(24)
        summary["daily"] = tracker.daily(14)
        today = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
        week_start = today - time.localtime().tm_wday * 86400
        summary["weeks"] = [(week_start - i * 7 * 86400,
                             tracker.window(week_start - i * 7 * 86400, week_start - (i - 1) * 7 * 86400))
                            for i in range(4)]
        self.usage = summary
        self.usage_at = time.time()

    def read_plan_limits(self):
        """Plan usage windows saved by the Claude Code statusline script."""
        if not self.enabled():
            return
        path = Path(os.path.expanduser(str(self.config.get("claude_limits_file") or "")))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            mtime = path.stat().st_mtime
        except (OSError, ValueError):
            self.plan = None
            return
        limits = data.get("rate_limits") or {}
        windows = {}
        for key in ("five_hour", "seven_day"):
            w = limits.get(key) or {}
            pct = w.get("used_percentage", w.get("utilization"))
            if pct is not None:
                windows[key] = {"pct": float(pct), "resets": float(w.get("resets_at") or 0)}
        self.plan = {"windows": windows, "updated": mtime, "plan": str(self.config.get("claude_plan") or "")}

    def fill(self, s: Snapshot):
        s.claude = self.info
        s.usage = self.usage
        s.plan = self.plan
        self.hist.append(s.claude.cpu if s.claude.running else 0.0)
        s.claude_hist = list(self.hist)

    def detect_events(self, s: Snapshot):
        c = s.claude
        if self.prev_sessions is not None and c.sessions != self.prev_sessions:
            if c.sessions > self.prev_sessions:
                self.emit("CLAUDE", f"session started ({c.sessions} active)", CYAN)
            else:
                self.emit("CLAUDE", f"session ended ({c.sessions} active)", CYAN)
        self.prev_sessions = c.sessions
        now = time.monotonic()
        if c.working:
            if now - self.idle_since > 30:
                self.emit("CLAUDE", "agent is working", CYAN)
            self.idle_since = now

    def probe_lines(self, s: Snapshot) -> list[str]:
        if s.claude.running:
            state = "working" if s.claude.working else "idle"
            return [f"claude code {state}  sessions {s.claude.sessions}  mem {fmt_size(s.claude.rss)}"]
        if self.enabled():
            return ["claude code not running"]
        return []

    # --- screen

    def status_items(self, s: Snapshot) -> list[str]:
        if not self.enabled():
            return []
        if s.claude.running:
            return [f"CLAUDE CODE ONLINE · {s.claude.sessions} SESSION{'S' if s.claude.sessions != 1 else ''}"]
        return ["CLAUDE CODE OFFLINE"]

    def ticker(self, s: Snapshot) -> list[str]:
        windows = (s.plan or {}).get("windows") or {}
        if not windows:
            return []
        parts = [f"{lbl} {windows[k]['pct']:.0f}%" for k, lbl in (("five_hour", "5H"), ("seven_day", "SEMANA"))
                 if k in windows]
        return ["CLAUDE " + " · ".join(parts)]

    def alerts(self, s: Snapshot) -> list[str]:
        five = ((s.plan or {}).get("windows") or {}).get("five_hour")
        if five and five["pct"] >= 100 and five["resets"] > time.time():
            return [f"CLAUDE: LIMITE DE 5H ESGOTADO - RENOVA ÀS {time.strftime('%H:%M', time.localtime(five['resets']))}"]
        return []

    def boot_lines(self, s: Snapshot) -> list[tuple[str, str]]:
        if s.claude.running:
            return [("OK", f"claude code agent v{s.claude.version}  //  online")]
        if self.enabled():
            return [("WARN", "claude code agent  //  not running")]
        return []

    USAGE_MODES = ("auto", "retrato", "relatório")

    def handle_key(self, key: str, dash) -> bool:
        if key != "u":
            return False
        idx = (self.USAGE_MODES.index(dash.usage_mode) + 1) % len(self.USAGE_MODES)
        dash.usage_mode = self.USAGE_MODES[idx]
        dash.notify({"auto": "retrato e relatório de uso alternando", "retrato": "retrato fixo",
                     "relatório": "relatório de uso do Claude fixo"}[dash.usage_mode], G5, 2.5)
        return True
