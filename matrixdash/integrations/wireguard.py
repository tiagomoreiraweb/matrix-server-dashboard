"""WireGuard: interfaces of this server and their peers (handshake, endpoint, traffic).

Interface address and traffic come from `ip` and /sys without root. Peers need `wg show`,
which is root-only: system/wireguard-sudo.sh allows the dashboard user to run only the
`wg show all <field>` reads below, none of which prints a private key.
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Any

from ..models import Snapshot
from ..shell import run_cmd
from ..theme import AMBER, G2, G4, G5, RED
from .base import Integration

WG = "/usr/bin/wg"
FIELDS = ("allowed-ips", "endpoints", "latest-handshakes", "transfer", "persistent-keepalive")
# WireGuard re-handshakes every 2 min while there is traffic; 3 min without one = gone.
ONLINE_FOR = 180


def interfaces() -> list[str]:
    code, out = run_cmd(["ip", "-o", "link", "show", "type", "wireguard"], timeout=3.0)
    if code != 0:
        return []
    return [m.group(1) for m in re.finditer(r"^\d+:\s+([^:@\s]+)", out, re.M)]


def counters(iface: str) -> tuple[int, int]:
    base = Path(f"/sys/class/net/{iface}/statistics")
    try:
        return int((base / "rx_bytes").read_text()), int((base / "tx_bytes").read_text())
    except (OSError, ValueError):
        return 0, 0


def address(iface: str) -> str:
    _, out = run_cmd(["ip", "-o", "-4", "addr", "show", "dev", iface], timeout=3.0)
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+/\d+)", out)
    return m.group(1) if m else ""


def read_peers() -> dict[str, dict[str, dict[str, Any]]] | None:
    """iface -> public key -> fields, or None when `sudo -n wg show` is not allowed."""
    peers: dict[str, dict[str, dict[str, Any]]] = {}
    for fld in FIELDS:
        code, out = run_cmd(["sudo", "-n", WG, "show", "all", fld], timeout=4.0)
        if code != 0:
            return None
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            peer = peers.setdefault(parts[0], {}).setdefault(parts[1], {})
            value = parts[2:]
            if fld == "allowed-ips":
                peer["allowed"] = [ip for ip in value[0].split() if ip != "(none)"]
            elif fld == "endpoints":
                peer["endpoint"] = "" if value[0] == "(none)" else value[0]
            elif fld == "latest-handshakes":
                peer["handshake"] = float(value[0] or 0)
            elif fld == "transfer" and len(value) >= 2:
                peer["rx"], peer["tx"] = int(value[0]), int(value[1])
            elif fld == "persistent-keepalive":
                peer["keepalive"] = 0 if value[0] == "off" else int(value[0])
    return peers


class WireGuardIntegration(Integration):
    key = "wireguard"

    def __init__(self, collector):
        super().__init__(collector)
        self.data: dict[str, Any] | None = None
        self.prev_counters: dict[str, tuple[float, int, int]] = {}
        self.prev_online: dict[str, bool] = {}
        self.prev_ifaces: set[str] | None = None
        # Peers need sudo; read them less often than the interface counters (default every 60 s).
        self.peers_cache: dict[str, dict[str, dict[str, Any]]] | None = None
        self.peers_at = float("-inf")
        cfg = self.config.get("wireguard")
        self.names = {str(k): str(v) for k, v in ((cfg if isinstance(cfg, dict) else {}).get("names") or {}).items()}

    def enabled(self) -> bool:
        # Decided by the reads in the collector threads: never runs a command from the render loop.
        return self.config.get("wireguard") is not False and self.data is not None

    def prime(self):
        self.read()

    def collect_slow(self):
        self.read()

    def peer_name(self, allowed: list[str]) -> str:
        for ip in allowed:
            bare = ip.split("/")[0]
            if ip in self.names or bare in self.names:
                return self.names.get(ip) or self.names[bare]
        return allowed[0].split("/")[0] if allowed else "?"

    def rate(self, key: str, rx: int, tx: int) -> tuple[float, float]:
        now = time.monotonic()
        prev = self.prev_counters.get(key)
        self.prev_counters[key] = (now, rx, tx)
        if not prev or now <= prev[0]:
            return 0.0, 0.0
        dt = now - prev[0]
        return max(0.0, (rx - prev[1]) / dt), max(0.0, (tx - prev[2]) / dt)

    def peers_every(self) -> float:
        cfg = self.config.get("wireguard")
        return max(12.0, float((cfg if isinstance(cfg, dict) else {}).get("peers_every", 60)))

    def read_peers_cached(self) -> dict[str, dict[str, dict[str, Any]]] | None:
        now = time.monotonic()
        if now - self.peers_at >= self.peers_every():
            self.peers_cache = read_peers()
            self.peers_at = now
        return self.peers_cache

    def read(self):
        if self.config.get("wireguard") is False or not shutil.which("wg"):
            return
        names = interfaces()
        if not names:
            self.data = {"ifaces": [], "peers_known": True, "at": time.time()} if self.data else None
            return
        peers = self.read_peers_cached()
        now = time.time()
        ifaces = []
        for name in names:
            rx, tx = counters(name)
            rx_rate, tx_rate = self.rate(name, rx, tx)
            entry: dict[str, Any] = {"name": name, "address": address(name), "rx": rx, "tx": tx,
                                     "rx_rate": rx_rate, "tx_rate": tx_rate, "peers": []}
            for key, p in sorted(((peers or {}).get(name) or {}).items()):
                allowed = p.get("allowed", [])
                hs = p.get("handshake", 0.0)
                prx, ptx = self.rate(f"{name}/{key}", p.get("rx", 0), p.get("tx", 0))
                entry["peers"].append({
                    "id": key[:8], "name": self.peer_name(allowed), "allowed": allowed,
                    "endpoint": p.get("endpoint", ""), "handshake": hs,
                    "online": bool(hs) and now - hs < ONLINE_FOR, "keepalive": p.get("keepalive", 0),
                    "rx": p.get("rx", 0), "tx": p.get("tx", 0), "rx_rate": prx, "tx_rate": ptx,
                })
            entry["peers"].sort(key=lambda p: (not p["online"], p["name"]))
            ifaces.append(entry)
        self.data = {"ifaces": ifaces, "peers_known": peers is not None, "at": now}

    def fill(self, s: Snapshot):
        s.wireguard = self.data

    # --- events and status

    @staticmethod
    def peers(s: Snapshot) -> list[tuple[str, dict[str, Any]]]:
        return [(i["name"], p) for i in (s.wireguard or {}).get("ifaces", []) for p in i["peers"]]

    def detect_events(self, s: Snapshot):
        if s.wireguard is None:
            return
        current = {i["name"] for i in s.wireguard.get("ifaces", [])}
        if self.prev_ifaces is not None:
            for name in self.prev_ifaces - current:
                self.emit("NET", f"wireguard {name} down", RED)
            for name in current - self.prev_ifaces:
                self.emit("NET", f"wireguard {name} up", G5)
        self.prev_ifaces = current
        for iface, p in self.peers(s):
            key = f"{iface}/{p['id']}"
            old = self.prev_online.get(key)
            if old is not None and old != p["online"]:
                if p["online"]:
                    self.emit("NET", f"wireguard peer {p['name']} connected ({p['endpoint'] or '-'})", G5)
                else:
                    self.emit("NET", f"wireguard peer {p['name']} offline", AMBER if not p["keepalive"] else RED)
            self.prev_online[key] = p["online"]

    def stale_keepalive_peers(self, s: Snapshot) -> list[dict[str, Any]]:
        """Peers that keep the tunnel alive on purpose (site-to-site) but stopped answering."""
        return [p for _, p in self.peers(s) if p["keepalive"] and not p["online"]]

    def summary(self, s: Snapshot) -> tuple[int, int]:
        peers = self.peers(s)
        return sum(1 for _, p in peers if p["online"]), len(peers)

    def alerts(self, s: Snapshot) -> list[str]:
        out = []
        if self.prev_ifaces is not None and s.wireguard is not None and not s.wireguard.get("ifaces"):
            out.append("WIREGUARD FORA DO AR")
        for p in self.stale_keepalive_peers(s):
            mins = int((time.time() - p["handshake"]) // 60) if p["handshake"] else 0
            out.append(f"WIREGUARD: {p['name'].upper()} SEM HANDSHAKE" + (f" HÁ {mins} MIN" if mins else ""))
        return out

    def ticker(self, s: Snapshot) -> list[str]:
        if not (s.wireguard or {}).get("ifaces") or not s.wireguard.get("peers_known"):
            return []
        online, total = self.summary(s)
        return [f"WIREGUARD {online}/{total} PEERS"]

    def boot_lines(self, s: Snapshot) -> list[tuple[str, str]]:
        lines = []
        for i in (s.wireguard or {}).get("ifaces", []):
            online = sum(1 for p in i["peers"] if p["online"])
            peers = f"{online}/{len(i['peers'])} peers" if s.wireguard.get("peers_known") else "peers: sem permissão"
            ok = s.wireguard.get("peers_known") and not any(p["keepalive"] and not p["online"] for p in i["peers"])
            lines.append(("OK" if ok else "WARN", f"wireguard {i['name']}  //  {i['address'] or '-'} · {peers}"))
        return lines

    def unit_view(self, unit: str, s: Snapshot) -> tuple[bool, str, int, str, int] | None:
        m = re.fullmatch(r"wg-quick@(.+?)(\.service)?", unit)
        if not m or s.wireguard is None:
            return None
        iface = next((i for i in s.wireguard.get("ifaces", []) if i["name"] == m.group(1)), None)
        if iface is None:
            return False, "DOWN", RED, f"{m.group(1)} sem interface", AMBER
        if not s.wireguard.get("peers_known"):
            return True, "ACTIVE", G5, f"{iface['address']}  peers: sudo ./system/wireguard-sudo.sh", G2
        online = sum(1 for p in iface["peers"] if p["online"])
        stale = any(p["keepalive"] and not p["online"] for p in iface["peers"])
        detail = f"{iface['address']}  {online}/{len(iface['peers'])} peers"
        return not stale, "ONLINE" if online else "NO PEER", G5 if online else AMBER, detail, AMBER if stale else G4

    def probe_lines(self, s: Snapshot) -> list[str]:
        if not (s.wireguard or {}).get("ifaces"):
            return []
        online, total = self.summary(s)
        return [f"wireguard {online}/{total} peers online"]

    def menu(self, m):
        s = self.collector.snap
        for i in (s.wireguard or {}).get("ifaces", []):
            online = sum(1 for p in i["peers"] if p["online"])
            m.system_info(f"WireGuard {i['name']}", f"{i['address'] or '-'} · {online}/{len(i['peers'])} peers online")
