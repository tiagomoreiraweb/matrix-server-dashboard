"""
Claude Code usage tracker for the Matrix dashboard.

Reads the local Claude Code transcripts (~/.claude/projects/**/*.jsonl)
incrementally and aggregates token usage per hour and per model, with an
estimated API-equivalent cost. On a subscription plan nothing is billed per
token; the cost is only a way to weigh the usage. Plan limits (5-hour and
weekly windows) are not stored locally, so they are not shown.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

# USD per million tokens: (input, output, cache read). Cache writes are billed
# at 1.25x input (5-minute TTL) and 2x input (1-hour TTL).
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-opus-4-7": (5.0, 25.0, 0.50),
    "claude-opus-4-6": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
DEFAULT_PRICE = PRICES["claude-opus-5-5"]
FIELDS = ("input", "output", "cache_write", "cache_read", "cost", "messages")


def price_for(model: str) -> tuple[float, float, float]:
    base = re.sub(r"-\d{8}$", "", model or "")
    if base in PRICES:
        return PRICES[base]
    for key, value in PRICES.items():
        if base.startswith(key):
            return value
    return DEFAULT_PRICE


def short_model(model: str) -> str:
    m = re.match(r"claude-([a-z]+)-(\d+)(?:-(\d+))?", model or "")
    if not m:
        return model or "?"
    name, major, minor = m.groups()
    return f"{name.capitalize()} {major}.{minor}" if minor and len(minor) == 1 else f"{name.capitalize()} {major}"


class UsageTracker:
    def __init__(self, root: Path | None = None):
        self.root = root or Path.home() / ".claude" / "projects"
        self.offsets: dict[Path, int] = {}
        self.seen: set[tuple[str, str]] = set()
        # hour epoch -> stats; model -> stats
        self.hours: dict[int, dict[str, float]] = defaultdict(lambda: dict.fromkeys(FIELDS, 0.0))
        self.models: dict[str, dict[str, float]] = defaultdict(lambda: dict.fromkeys(FIELDS, 0.0))
        self.sessions: dict[str, float] = {}  # session id -> last activity
        self.first_ts: float | None = None
        self.lock = threading.Lock()
        self.updated = 0.0

    def refresh(self):
        if not self.root.exists():
            return
        for path in self.root.rglob("*.jsonl"):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            offset = self.offsets.get(path, 0)
            if size < offset:
                offset = 0  # file was rewritten
            if size == offset:
                continue
            try:
                with open(path, "rb") as f:
                    f.seek(offset)
                    chunk = f.read()
            except OSError:
                continue
            # Only consume complete lines; a partial last line is read next time.
            end = chunk.rfind(b"\n")
            if end < 0:
                continue
            self.offsets[path] = offset + end + 1
            for raw in chunk[: end + 1].splitlines():
                if b'"usage"' in raw:
                    self._ingest(raw)
        self.updated = time.time()

    def _ingest(self, raw: bytes):
        try:
            rec = json.loads(raw)
        except ValueError:
            return
        msg = rec.get("message") or {}
        usage = msg.get("usage")
        if rec.get("type") != "assistant" or not isinstance(usage, dict):
            return
        # Each content block of a response is logged as its own line with the
        # same usage; count every response once.
        key = (str(msg.get("id", "")), str(rec.get("requestId", "")))
        if key in self.seen:
            return
        self.seen.add(key)
        try:
            ts = time.mktime(time.strptime(rec["timestamp"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
        except (KeyError, ValueError):
            return
        model = str(msg.get("model") or rec.get("requestedModel") or "")
        if model.startswith("<") or not model:
            return
        p_in, p_out, p_read = price_for(model)
        inp = int(usage.get("input_tokens") or 0)
        out = int(usage.get("output_tokens") or 0)
        read = int(usage.get("cache_read_input_tokens") or 0)
        creation = usage.get("cache_creation") or {}
        w1h = int(creation.get("ephemeral_1h_input_tokens") or 0)
        w5m = int(creation.get("ephemeral_5m_input_tokens") or 0)
        if not (w1h or w5m):
            w5m = int(usage.get("cache_creation_input_tokens") or 0)
        cost = (inp * p_in + out * p_out + read * p_read + w5m * p_in * 1.25 + w1h * p_in * 2.0) / 1e6
        if usage.get("speed") == "fast":
            cost *= 2
        stats = {"input": inp, "output": out, "cache_write": w5m + w1h, "cache_read": read,
                 "cost": cost, "messages": 1}
        hour = int(ts // 3600 * 3600)
        with self.lock:
            for bucket in (self.hours[hour], self.models[model]):
                for k, v in stats.items():
                    bucket[k] += v
            sid = str(rec.get("sessionId") or "")
            if sid:
                self.sessions[sid] = max(self.sessions.get(sid, 0.0), ts)
            if self.first_ts is None or ts < self.first_ts:
                self.first_ts = ts

    # --- aggregates

    def window(self, start: float, end: float | None = None) -> dict[str, float]:
        end = end or time.time() + 3600
        total = dict.fromkeys(FIELDS, 0.0)
        with self.lock:
            for hour, stats in self.hours.items():
                if start <= hour < end:
                    for k in FIELDS:
                        total[k] += stats[k]
        total["tokens"] = total["input"] + total["output"] + total["cache_write"] + total["cache_read"]
        return total

    def hourly(self, hours: int = 24) -> list[tuple[int, dict[str, float]]]:
        now_hour = int(time.time() // 3600 * 3600)
        with self.lock:
            return [(h, dict(self.hours.get(h, dict.fromkeys(FIELDS, 0.0))))
                    for h in range(now_hour - (hours - 1) * 3600, now_hour + 1, 3600)]

    def daily(self, days: int = 14) -> list[tuple[float, dict[str, float]]]:
        today = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
        result = []
        for i in range(days - 1, -1, -1):
            start = today - i * 86400
            result.append((start, self.window(start, start + 86400)))
        return result

    def summary(self) -> dict[str, Any]:
        now = time.time()
        today = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
        week_start = today - time.localtime(now).tm_wday * 86400
        with self.lock:
            models = sorted(((m, dict(s)) for m, s in self.models.items()), key=lambda x: -x[1]["cost"])
            active = sum(1 for t in self.sessions.values() if now - t < 3600)
            sessions = len(self.sessions)
        return {
            "today": self.window(today),
            "last5h": self.window(now - 5 * 3600 - 3600),
            "week": self.window(week_start),
            "last7d": self.window(today - 6 * 86400),
            "last30d": self.window(today - 29 * 86400),
            "total": self.window(0),
            "models": models,
            "sessions": sessions,
            "active_sessions": active,
            "since": self.first_ts,
            "updated": self.updated,
        }
