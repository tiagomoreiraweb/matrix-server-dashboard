"""Threshold checks shared by the header alerts and the console events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Snapshot


@dataclass
class Breach:
    key: str
    active: bool
    alert: str       # header alert while active
    event_on: str    # console event when it starts
    event_off: str   # console event when it ends


def thresholds(s: Snapshot, th: dict[str, Any]) -> list[Breach]:
    """CPU sustained for 5 s, memory, temperature and every disk against config["thresholds"]."""
    recent = s.cpu_hist[-5:]
    out = [
        Breach("cpu", len(recent) == 5 and min(recent) >= float(th.get("cpu", 85)), f"CPU {s.cpu:.0f}%",
               f"cpu sustained above {th.get('cpu', 85)}%", "cpu back to normal"),
        Breach("ram", s.ram >= float(th.get("ram", 85)), f"RAM {s.ram:.0f}%",
               f"memory at {s.ram:.0f}%", "memory back to normal"),
    ]
    if s.temperature is not None:
        out.append(Breach("temp", s.temperature >= float(th.get("temperature", 80)), f"TEMP {s.temperature:.0f}°C",
                          f"temperature at {s.temperature:.0f}°C", "temperature back to normal"))
    for mount, pct, _, _ in s.disks:
        out.append(Breach(f"disk{mount}", pct >= float(th.get("disk", 90)), f"DISK {mount} {pct:.0f}%",
                          f"disk {mount} at {pct:.0f}%", f"disk {mount} back to normal"))
    return out
