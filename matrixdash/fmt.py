"""Number and size formatting."""

from __future__ import annotations

import re
import time


def parse_size(text: str) -> float:
    match = re.match(r"([\d.]+)\s*([KMGT]?i?B)", text.strip())
    if not match:
        return 0.0
    mult = {"B": 1, "KB": 1e3, "KiB": 1024, "MB": 1e6, "MiB": 1024**2, "GB": 1e9, "GiB": 1024**3, "TB": 1e12, "TiB": 1024**4}
    return float(match.group(1)) * mult.get(match.group(2), 1)


def fmt_size(value: float) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if value < 1024 or unit == "T":
            if unit in ("B", "K", "M"):
                return f"{value:.0f}{unit}"
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}T"


def fmt_tokens(value: float) -> str:
    value = float(value or 0)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if value >= div:
            return f"{value / div:.1f}{unit}"
    return f"{value:.0f}"


def fmt_rate(value: float) -> str:
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    val = max(0.0, float(value))
    for unit in units:
        if val < 1024 or unit == units[-1]:
            return f"{val:.0f} {unit}" if unit == "B/s" else f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} GB/s"


def fmt_uptime(seconds: float) -> str:
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}h {mins:02d}m"
    if hours:
        return f"{hours}h {mins:02d}m"
    return f"{mins}m"


def rate_short(v: float) -> str:
    """Compact bytes/s for tight columns: 0, 512B, 12K, 1.5M."""
    if v < 1:
        return "0"
    for unit in ("B", "K", "M", "G"):
        if v < 1024 or unit == "G":
            return f"{v:.0f}{unit}" if unit in ("B", "K") or v >= 100 else f"{v:.1f}{unit}"
        v /= 1024
    return "?"


def ago(ts: float) -> str:
    """'agora', '12min', '3h' or '5d' since an epoch timestamp."""
    if not ts:
        return "-"
    sec = max(0, time.time() - ts)
    if sec < 90:
        return "agora"
    if sec < 3600:
        return f"{sec / 60:.0f}min"
    if sec < 86400:
        return f"{sec / 3600:.0f}h"
    return f"{sec / 86400:.0f}d"
