"""Network map: devices on the LAN, Tailscale peers and Docker networks.

Runs without root. The LAN sweep sends one empty UDP datagram to every
address of the subnet, which makes the kernel ARP for it; whatever answers
ends up in the neighbour table. An all-nodes ping on IPv6 catches devices
that only talk v6. Names come from mDNS, NetBIOS and reverse DNS.

The server only sees MAC addresses, so it cannot tell cable from Wi-Fi by
itself. The link type is taken from `config["devices"]` when set, otherwise
estimated: a locally administered (private/random) MAC is what phones,
tablets and laptops use on Wi-Fi, and some vendors only make Wi-Fi gear.

Traffic (sample_traffic, every few seconds) is what passes through this
server: byte counters of every TCP socket in the host (ss -ti), so each LAN
or Tailscale peer gets its rate with the server; the eth0 counters of each
container (/proc/<pid>/net/dev); and the totals of the server interfaces.
Traffic between other devices and the internet goes through the router and
never reaches this machine, so it cannot be shown here.
"""

from __future__ import annotations

import ipaddress
import json
import os
import random
import re
import shutil
import socket
import struct
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import ROOT
from .integrations import tailscale
from .runtime import ContainerRuntime
from .shell import run_cmd

OUI_FILES = ("/usr/share/nmap/nmap-mac-prefixes", "/usr/share/ieee-data/oui.txt")
WIFI_VENDORS = ("espressif", "tuya", "shelly", "itead", "sonoff", "amazon", "google", "ring ", "wyze",
                "xiaomi", "beijing xiaomi", "realme", "oppo", "motorola", "huawei device", "vivo mobile",
                "roku", "chromecast", "nintendo", "tp-link smart", "broadlink", "ezviz", "imou")
STATE_FILE = ROOT / ".netmap.json"
PORT_NAMES = {22: "ssh", 139: "samba", 445: "samba", 53: "dns", 80: "http", 443: "https", 8095: "painel",
              19999: "netdata", 5432: "postgres", 1883: "mqtt", 3389: "rdp", 5900: "vnc"}
SS_RE = re.compile(r"^\d+\s+\d+\s+(\S+):(\d+)\s+(\S+):(\d+)")




def norm_mac(mac: str) -> str:
    return mac.strip().lower()


def private_mac(mac: str) -> bool:
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except ValueError:
        return False


class OuiDB:
    def __init__(self):
        self.table: dict[str, str] = {}
        for path in OUI_FILES:
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        m = re.match(r"^([0-9A-Fa-f]{6})\s+(?:\(base 16\)\s+)?(.+)$", line.strip())
                        if m:
                            self.table.setdefault(m.group(1).upper(), m.group(2).strip())
            except OSError:
                continue

    def lookup(self, mac: str) -> str:
        if private_mac(mac):
            return "(MAC privado)"
        return self.table.get(mac.replace(":", "").upper()[:6], "")


# ---------------------------------------------------------------- name lookups

def _dns_name(data: bytes, off: int) -> tuple[str, int]:
    labels, jumped, end = [], False, off
    for _ in range(64):
        n = data[off]
        if n == 0:
            off += 1
            break
        if n & 0xC0 == 0xC0:
            if not jumped:
                end = off + 2
            off = ((n & 0x3F) << 8) | data[off + 1]
            jumped = True
            continue
        labels.append(data[off + 1:off + 1 + n].decode("utf-8", "replace"))
        off += 1 + n
    return ".".join(labels), (end if jumped else off)


def mdns_name(ip: str, timeout: float = 1.0) -> str:
    """Reverse PTR over multicast DNS (answers come back unicast to our port)."""
    qname = b"".join(bytes([len(p)]) + p.encode() for p in (list(reversed(ip.split("."))) + ["in-addr", "arpa"]))
    tid = random.randrange(65536)
    packet = struct.pack(">HHHHHH", tid, 0, 1, 0, 0, 0) + qname + b"\x00" + struct.pack(">HH", 12, 0x8001)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(packet, ("224.0.0.251", 5353))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data, _ = sock.recvfrom(4096)
            if len(data) < 12:
                continue
            an = struct.unpack(">H", data[6:8])[0]
            off = 12
            for _ in range(struct.unpack(">H", data[4:6])[0]):
                _, off = _dns_name(data, off)
                off += 4
            for _ in range(an):
                _, off = _dns_name(data, off)
                rtype, _, _, rdlen = struct.unpack(">HHIH", data[off:off + 10])
                off += 10
                if rtype == 12:
                    name, _ = _dns_name(data, off)
                    return name.removesuffix(".local")
                off += rdlen
    except (OSError, IndexError, struct.error):
        pass
    finally:
        sock.close()
    return ""


def netbios_name(ip: str, timeout: float = 0.8) -> str:
    """NetBIOS node status query (Windows machines, Samba, some NAS)."""
    packet = struct.pack(">HHHHHH", random.randrange(65536), 0, 1, 0, 0, 0)
    packet += b"\x20" + b"CK" + b"A" * 30 + b"\x00" + struct.pack(">HH", 0x21, 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(packet, (ip, 137))
        data, _ = sock.recvfrom(2048)
        off = 12 + 34 + 4 + 6
        count = data[off]
        off += 1
        for i in range(count):
            raw = data[off + i * 18:off + i * 18 + 18]
            name, suffix, flags = raw[:15].decode("ascii", "replace").strip(), raw[15], raw[16]
            if suffix == 0x00 and not flags & 0x80:
                return name
    except (OSError, IndexError):
        pass
    finally:
        sock.close()
    return ""


def rdns_name(ip: str) -> str:
    try:
        name = socket.gethostbyaddr(ip)[0]
    except (OSError, UnicodeError):
        return ""
    if name == ip or name.lower() in ("none", "localhost", "unknown"):
        return ""
    return name.split(".")[0] if name.endswith((".lan", ".home", ".local")) else name


def ping_ms(ip: str, timeout: int = 1) -> float | None:
    code, out = run_cmd(["ping", "-n", "-c", "1", "-W", str(timeout), ip], timeout=timeout + 1.5, strip=False)
    if code != 0:
        return None
    m = re.search(r"time=([\d.]+)", out)
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------- mapper

class NetMapper:
    def __init__(self, config: dict[str, Any], iface: str, runtimes: list[ContainerRuntime] | None = None, emit=None):
        self.config = config
        self.iface = iface
        self.runtimes = list(runtimes or [])
        self.emit = emit or (lambda *a, **k: None)
        self.oui = OuiDB()
        self.pool = ThreadPoolExecutor(max_workers=32)
        self.lock = threading.Lock()
        self.known: dict[str, dict[str, Any]] = {}
        self.names: dict[str, tuple[str, float]] = {}
        self.first_scan = True
        try:
            self.known = json.loads(STATE_FILE.read_text(encoding="utf-8")).get("devices", {})
        except (OSError, ValueError):
            self.known = {}
        self.result: dict[str, Any] | None = None
        # Traffic sampling state.
        self.port_names = dict(PORT_NAMES)
        for check in config.get("checks", []):
            if not isinstance(check, dict):  # the "auto" marker
                continue
            m = re.match(r"https?://(?:127\.0\.0\.1|localhost):(\d+)", str(check.get("url", "")))
            port = int(m.group(1)) if m else int(check.get("tcp_port") or 0)
            if port:
                self.port_names[port] = str(check.get("container") or check.get("name", "")).lower()
        self.containers: dict[str, int] = {}
        self.sock_prev: dict[tuple, tuple[int, int]] = {}
        self.cont_prev: dict[str, tuple[int, int]] = {}
        self.if_prev: dict[str, tuple[int, int]] = {}
        self.traffic_at = 0.0
        self.hist: dict[str, deque] = {}
        self.traffic: dict[str, Any] | None = None

    def overrides(self) -> dict[str, dict[str, Any]]:
        raw = self.config.get("devices") or {}
        return {norm_mac(k): (v if isinstance(v, dict) else {"name": str(v)}) for k, v in raw.items()}

    def subnet(self) -> ipaddress.IPv4Network | None:
        code, out = run_cmd(["ip", "-4", "-o", "addr", "show", "dev", self.iface], timeout=5.0, strip=False)
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+/\d+)", out)
        if not m:
            return None
        net = ipaddress.ip_interface(m.group(1)).network
        return net if net.num_addresses <= 1024 else ipaddress.ip_network(f"{m.group(1).split('/')[0]}/24", strict=False)

    def own(self) -> dict[str, str]:
        mac = ""
        try:
            mac = Path(f"/sys/class/net/{self.iface}/address").read_text().strip()
        except OSError:
            pass
        wireless = Path(f"/sys/class/net/{self.iface}/wireless").exists()
        _, out = run_cmd(["ip", "-4", "-o", "addr", "show", "dev", self.iface], timeout=5.0, strip=False)
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        return {"mac": mac, "ip": m.group(1) if m else "", "link": "wifi" if wireless else "cabo"}

    def gateway(self) -> str:
        _, out = run_cmd(["ip", "-4", "route", "show", "default"], timeout=5.0, strip=False)
        m = re.search(r"via (\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else ""

    def sweep(self, net: ipaddress.IPv4Network):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            for host in net.hosts():
                try:
                    sock.sendto(b"", (str(host), 9))
                except OSError:
                    pass
        finally:
            sock.close()
        if shutil.which("ping"):
            run_cmd(["ping", "-6", "-n", "-c", "2", "-w", "3", f"ff02::1%{self.iface}"], timeout=5, strip=False)
        else:
            time.sleep(3)

    def neighbours(self) -> dict[str, dict[str, Any]]:
        devices: dict[str, dict[str, Any]] = {}
        for fam in ("-4", "-6"):
            _, out = run_cmd(["ip", fam, "neigh", "show", "dev", self.iface], timeout=5.0, strip=False)
            for line in out.splitlines():
                parts = line.split()
                if "lladdr" not in parts or not parts:
                    continue
                state = parts[-1]
                if state in ("FAILED", "INCOMPLETE"):
                    continue
                mac = norm_mac(parts[parts.index("lladdr") + 1])
                d = devices.setdefault(mac, {"mac": mac, "ip": "", "ip6": [], "router": False})
                if fam == "-4":
                    d["ip"] = parts[0]
                elif not parts[0].startswith("fe80"):
                    d["ip6"].append(parts[0])
                else:
                    d.setdefault("ll6", parts[0])
                d["router"] = d["router"] or "router" in parts
        return devices

    def resolve(self, ip: str) -> str:
        cached = self.names.get(ip)
        if cached and time.time() - cached[1] < 1800:
            return cached[0]
        name = mdns_name(ip) or netbios_name(ip) or rdns_name(ip)
        self.names[ip] = (name, time.time())
        return name

    def link_of(self, mac: str, vendor: str, override: dict[str, Any]) -> tuple[str, bool]:
        """Return (link, estimated)."""
        link = str(override.get("link") or "").lower()
        if link in ("cabo", "wifi", "wi-fi", "eth", "ethernet", "lan"):
            return ("wifi" if "w" in link else "cabo"), False
        if private_mac(mac):
            return "wifi", True
        v = vendor.lower()
        if any(k in v for k in WIFI_VENDORS):
            return "wifi", True
        return "?", True

    def lan(self) -> dict[str, Any]:
        net = self.subnet()
        if net is None:
            return {"subnet": "", "devices": []}
        self.sweep(net)
        seen = self.neighbours()
        own = self.own()
        gw = self.gateway()
        over = self.overrides()
        now = time.time()

        online_ips = [d["ip"] for d in seen.values() if d["ip"]]
        pings = dict(zip(online_ips, self.pool.map(ping_ms, online_ips)))
        names = dict(zip(online_ips, self.pool.map(self.resolve, online_ips)))

        devices = []
        if own["mac"]:
            seen.pop(own["mac"], None)
            devices.append({"mac": own["mac"], "ip": own["ip"], "name": socket.gethostname(), "vendor": "este servidor",
                            "link": own["link"], "est": False, "role": "server", "online": True, "ms": 0.0,
                            "first": self.known.get(own["mac"], {}).get("first", now), "last": now, "ip6": 0})
        new_macs = []
        for mac, d in seen.items():
            info = self.known.get(mac, {})
            ov = over.get(mac, {})
            vendor = self.oui.lookup(mac)
            ip = d["ip"] or info.get("ip", "")
            role = "router" if d["ip"] == gw or d["router"] else ""
            name = str(ov.get("name") or ("" if role else names.get(d["ip"])) or info.get("name") or "")
            link, est = self.link_of(mac, vendor, ov)
            if role == "router" and link == "?":
                link, est = "gw", False
            if not info:
                new_macs.append((mac, ip, name, vendor))
            devices.append({"mac": mac, "ip": ip, "name": name, "vendor": vendor, "link": link, "est": est,
                            "role": role, "online": True, "ms": pings.get(d["ip"]),
                            "first": info.get("first", now), "last": now, "ip6": len(d["ip6"]), "ip6s": d["ip6"],
                            "new": not info and not self.first_scan or now - float(info.get("new_at", 0)) < 600})

        # Devices seen before but not now stay listed as offline.
        listed = {d["mac"] for d in devices}
        for mac, info in self.known.items():
            if mac in listed or now - float(info.get("last", 0)) > 30 * 86400:
                continue
            ov = over.get(mac, {})
            vendor = self.oui.lookup(mac)
            link, est = self.link_of(mac, vendor, ov)
            devices.append({"mac": mac, "ip": info.get("ip", ""), "name": str(ov.get("name") or info.get("name", "")),
                            "vendor": vendor, "link": link, "est": est, "role": info.get("role", ""), "online": False,
                            "ms": None, "first": info.get("first", now), "last": float(info.get("last", 0)), "ip6": 0})

        # Events: new devices and devices that left (only after the first scan).
        prev_online = {m for m, i in self.known.items() if now - float(i.get("last", 0)) < 200}
        if not self.first_scan:
            for mac, ip, name, vendor in new_macs:
                self.emit("NET", f"novo dispositivo {name or vendor or mac} {ip}"[:80], "new")
            for d in devices:
                if not d["online"] and d["mac"] in prev_online:
                    self.emit("NET", f"saiu da rede: {d['name'] or d['vendor'] or d['mac']} {d['ip']}"[:80], "gone")
        self.first_scan = False

        for d in devices:
            if d["online"]:
                entry = {"ip": d["ip"], "name": d["name"], "first": d["first"], "last": now, "role": d["role"]}
                new_at = self.known.get(d["mac"], {}).get("new_at") or (now if d.get("new") else 0)
                if new_at:
                    entry["new_at"] = new_at
                self.known[d["mac"]] = entry
        try:
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps({"devices": self.known}, indent=1), encoding="utf-8")
            os.replace(tmp, STATE_FILE)
        except OSError:
            pass

        def order(d):
            rank = {"router": 0, "server": 1}.get(d["role"], 2)
            try:
                ipn = int(ipaddress.ip_address(d["ip"])) if d["ip"] else 1 << 33
            except ValueError:
                ipn = 1 << 33
            return (not d["online"], rank, ipn)

        devices.sort(key=order)
        return {"subnet": str(net), "gateway": gw, "devices": devices}

    def tailscale(self) -> list[dict[str, Any]]:
        if not tailscale.installed():
            return []
        code, out = tailscale.status(timeout=5)
        try:
            data = json.loads(out)
        except ValueError:
            return []
        peers = []
        for p in (data.get("Peer") or {}).values():
            ips = p.get("TailscaleIPs") or []
            dns = str(p.get("DNSName") or "").split(".")[0]
            last = tailscale.parse_time(str(p.get("LastSeen") or "")) or 0.0
            peers.append({
                "name": dns or str(p.get("HostName") or "?"),
                "ip": next((i for i in ips if "." in i), ips[0] if ips else ""),
                "os": str(p.get("OS") or ""),
                "online": bool(p.get("Online")),
                "last": last,
                "path": "direto" if p.get("CurAddr") else (f"relay {p.get('Relay')}" if p.get("Relay") else ""),
                "exit": bool(p.get("ExitNode")),
            })
        peers.sort(key=lambda p: (not p["online"], p["name"]))
        return peers

    def docker(self) -> list[dict[str, Any]]:
        """Container networks of every runtime (the key keeps its old name for the snapshot export)."""
        nets: list[dict[str, Any]] = []
        pids: dict[str, int] = {}
        got_pids = False
        for rt in self.runtimes:
            found = [{"name": n.name, "driver": n.driver, "subnet": n.subnet, "members": n.members}
                     for n in rt.networks()]
            if not found:
                continue
            nets += found
            # Container PIDs, to read their own network counters (host-network ones share the host's).
            host_net = {m[0] for n in found if n["driver"] == "host" for m in n["members"]}
            rt_pids = rt.pids(host_net)
            if rt_pids is not None:
                got_pids = True
                pids.update(rt_pids)
        nets.sort(key=lambda n: (not n["members"], n["driver"] != "host", n["name"]))
        if got_pids:
            self.containers = pids
        return nets

    # --- traffic

    @staticmethod
    def _proc_conns(pid: int) -> set[str]:
        """Remote IPs with an established TCP connection inside a container."""
        peers = set()
        for name in ("tcp", "tcp6"):
            try:
                lines = Path(f"/proc/{pid}/net/{name}").read_text().splitlines()[1:]
            except OSError:
                continue
            for line in lines:
                parts = line.split()
                if len(parts) < 4 or parts[3] != "01":
                    continue
                raw = parts[2].split(":")[0]
                try:
                    if len(raw) == 8:
                        peers.add(socket.inet_ntop(socket.AF_INET, bytes.fromhex(raw)[::-1]))
                    else:
                        words = b"".join(bytes.fromhex(raw[i:i + 8])[::-1] for i in range(0, 32, 8))
                        ip = ipaddress.ip_address(words)
                        peers.add(str(ip.ipv4_mapped or ip))
                except (ValueError, OSError):
                    continue
        return peers

    @staticmethod
    def _dev_counters(path: str, iface: str) -> tuple[int, int] | None:
        try:
            for line in Path(path).read_text().splitlines():
                if line.strip().startswith(iface + ":"):
                    f = line.split(":", 1)[1].split()
                    return int(f[0]), int(f[8])
        except (OSError, ValueError, IndexError):
            pass
        return None

    def sample_traffic(self) -> dict[str, Any]:
        now = time.monotonic()
        dt = now - self.traffic_at if self.traffic_at else 0.0
        self.traffic_at = now
        peers: dict[str, dict[str, Any]] = {}

        def peer(ip: str) -> dict[str, Any]:
            return peers.setdefault(ip, {"rx": 0.0, "tx": 0.0, "svc": set()})

        # Host sockets: rx/tx are from the device's point of view (rx = what the device receives).
        _, out = run_cmd(["ss", "-tinH", "state", "established"], timeout=4, strip=False)
        cur: dict[tuple, tuple[int, int]] = {}
        lines = out.splitlines()
        for i, line in enumerate(lines):
            m = SS_RE.match(line)
            if not m or i + 1 >= len(lines):
                continue
            local, lport, remote, rport = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
            remote = remote.strip("[]").removeprefix("::ffff:")
            if remote.startswith(("127.", "::1")) or remote.startswith("172."):
                continue
            info = lines[i + 1]
            sent = re.search(r"bytes_acked:(\d+)", info)
            recv = re.search(r"bytes_received:(\d+)", info)
            key = (local, lport, remote, rport)
            cur[key] = (int(sent.group(1)) if sent else 0, int(recv.group(1)) if recv else 0)
            p = peer(remote)
            if lport in self.port_names:
                p["svc"].add(self.port_names[lport])
            elif rport in PORT_NAMES and rport < 1024:
                p["svc"].add("→" + PORT_NAMES[rport])
            elif lport < 32768:
                p["svc"].add(f":{lport}")
            if dt and key in self.sock_prev:
                ps, pr = self.sock_prev[key]
                p["rx"] += max(0, cur[key][0] - ps) / dt
                p["tx"] += max(0, cur[key][1] - pr) / dt
        self.sock_prev = cur

        # Containers: own interface counters, plus which peers talk to each one.
        containers = {}
        cur_c = {}
        for name, pid in self.containers.items():
            c = self._dev_counters(f"/proc/{pid}/net/dev", "eth0")
            if c is None:
                continue
            cur_c[name] = c
            rx = tx = 0.0
            if dt and name in self.cont_prev:
                rx = max(0, c[0] - self.cont_prev[name][0]) / dt
                tx = max(0, c[1] - self.cont_prev[name][1]) / dt
            containers[name] = {"rx": rx, "tx": tx}
            for ip in self._proc_conns(pid):
                if not ip.startswith(("127.", "172.")):
                    peer(ip)["svc"].add(name)
        self.cont_prev = cur_c

        # Server interfaces.
        ifaces = {}
        cur_i = {}
        for name in (self.iface, "tailscale0", "docker0"):
            c = self._dev_counters("/proc/net/dev", name)
            if c is None:
                continue
            cur_i[name] = c
            if dt and name in self.if_prev:
                ifaces[name] = {"rx": max(0, c[0] - self.if_prev[name][0]) / dt,
                                "tx": max(0, c[1] - self.if_prev[name][1]) / dt}
        self.if_prev = cur_i

        for ip, p in peers.items():
            h = self.hist.setdefault(ip, deque(maxlen=40))
            h.append(p["rx"] + p["tx"])
            p["hist"] = list(h)
            p["svc"] = sorted(p["svc"])
        for ip in list(self.hist):
            if ip not in peers:
                self.hist[ip].append(0.0)
                if not any(self.hist[ip]):
                    del self.hist[ip]
        self.traffic = {"peers": peers, "containers": containers, "ifaces": ifaces, "ready": bool(dt)}
        return self.traffic

    def scan(self) -> dict[str, Any]:
        lan = self.lan()
        result = {"lan": lan, "tailscale": self.tailscale(), "docker": self.docker(), "at": time.time()}
        with self.lock:
            self.result = result
        return result
