"""Active problems of the server: one list for the red header ticker and for the notifications."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import health
from .models import Snapshot

if TYPE_CHECKING:
    from .integrations import Integration


@dataclass(frozen=True)
class Alert:
    #: stable id while the problem lasts (numbers in the text may change, the key does not)
    key: str
    text: str


def _key(prefix: str, text: str) -> str:
    return f"{prefix}:{re.sub(r'[0-9.]+', '#', text)}"


def active(s: Snapshot, thresholds: dict[str, Any], integrations: list[Integration]) -> list[Alert]:
    out = [Alert(f"limit:{b.key}", b.alert) for b in health.thresholds(s, thresholds) if b.active]
    if not s.internet:
        out.append(Alert("net:internet", "INTERNET OFFLINE"))
    elif not s.net4:
        out.append(Alert("net:ipv4", "IPV4 OFFLINE (IPV6 OK) - CONTAINERS SEM INTERNET"))
    elif s.net6 is False:
        out.append(Alert("net:ipv6", "IPV6 OFFLINE (IPV4 OK)"))
    for ct in s.containers:
        if ct.state in ("restarting", "dead") or ct.health == "unhealthy" or ct.name in s.flagged:
            # k3s keeps the pod's error reason (ImagePullBackOff...) in exit_code
            if ct.runtime == "k3s" and ct.exit_code:
                problem = ct.exit_code
            elif ct.health == "unhealthy":
                problem = ct.health
            else:
                problem = ct.state
            out.append(Alert(f"container:{ct.name}", f"{ct.short.upper()} {problem.upper()}"))
    for label, _, state in s.units:
        if state != "active":
            out.append(Alert(f"unit:{label}", f"{label} {state.upper()}"))
    for integ in integrations:
        out += [Alert(_key(integ.key, text), text) for text in integ.alerts(s)]
    return out
