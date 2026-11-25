"""Host facts read without root: addresses, temperature, latency, HTTP probes."""

from __future__ import annotations

import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

from . import VERSION
from .shell import run_cmd


def get_local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "-"
    finally:
        sock.close()


def iface_for_ip(ip: str) -> str:
    try:
        for name, addrs in psutil.net_if_addrs().items():
            if any(a.family == socket.AF_INET and a.address == ip for a in addrs):
                return name
    except Exception:
        pass
    return "-"


def get_temperature() -> float | None:
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False)
    except Exception:
        return None
    for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
        valid = [e.current for e in temps.get(key, []) if e.current is not None]
        if valid:
            return max(valid)
    for entries in temps.values():
        valid = [e.current for e in entries if e.current is not None]
        if valid:
            return max(valid)
    return None


def tcp_latency(host: str, port: int, timeout: float = 1.0) -> float | None:
    started = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return (time.monotonic() - started) * 1000
    except OSError:
        return None


_UNVERIFIED_SSL = ssl._create_unverified_context()


def http_probe(url: str, host_header: str = "", timeout: float = 1.5) -> tuple[bool, int, float | None]:
    headers = {"User-Agent": f"matrix-dashboard/{VERSION}"}
    if host_header:
        headers["Host"] = host_header
    started = time.monotonic()
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout, context=_UNVERIFIED_SSL) as response:
            code = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        code = exc.code
    except Exception:
        return False, 0, None
    return code < 500, code, (time.monotonic() - started) * 1000


def read_ipv4(iface: str) -> dict[str, str]:
    """Current IPv4 settings of an interface, without root."""
    info = {"mode": "FIXO", "ip": "", "prefix": "", "gateway": "", "dns": "", "mac": "", "ipv6": ""}
    _, out = run_cmd(["ip", "-o", "addr", "show", "dev", iface])
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", out)
    if m:
        info["ip"], info["prefix"] = m.group(1), m.group(2)
    m6 = re.search(r"inet6 ([0-9a-f:]+)/\d+ scope global", out)
    if m6:
        info["ipv6"] = m6.group(1)
    _, route = run_cmd(["ip", "-4", "route", "show", "default", "dev", iface])
    gw = re.search(r"via (\S+)", route)
    info["gateway"] = gw.group(1) if gw else ""
    if "proto dhcp" in route:
        info["mode"] = "DHCP"
    _, dns = run_cmd(["resolvectl", "dns", iface])
    servers = [x for x in dns.split(":", 1)[-1].split() if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", x)]
    info["dns"] = ", ".join(servers)
    try:
        info["mac"] = Path(f"/sys/class/net/{iface}/address").read_text().strip()
    except OSError:
        pass
    return info
