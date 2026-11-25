"""Auto-discovery of what runs on this server.

Every list in config.json that holds the string "auto" is filled from here:

    "mounts":        ["auto"]            real disks (no snap, loop, tmpfs, /boot)
    "systemd_units": ["auto", {...}]     known host services that are installed
    "checks":        ["auto"]            HTTP/TCP probe for every Docker container
                                         with a published port (refreshed live)
    "web.allow":     ["auto"]            localhost, Tailscale and the local LANs

and the scalar settings "network_interface": "auto" and "claude": "auto".
Items next to "auto" are kept, so the user can add extras or override one
entry (an explicit check for a container replaces the automatic one).

Run `python3 autodetect.py` to print what would be detected on this machine.
"""

from __future__ import annotations

import getpass
import ipaddress
import os
import re
import shutil
import socket
import sys
from pathlib import Path
from typing import Any

import psutil

from .runtime import ContainerRuntime, from_config
from .shell import run_cmd

# ------------------------------------------------------------------ helpers


def current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or "operator"


def is_auto(value: Any) -> bool:
    return value == "auto" or (isinstance(value, list) and "auto" in value)


def expand(value: Any, detected: list[Any], key=None) -> list[Any]:
    """Replace the "auto" marker in a list by `detected`, keeping explicit items.

    With `key`, explicit items win over detected ones that share the same key.
    """
    if value == "auto":
        value = ["auto"]
    if not isinstance(value, list):
        return detected if value is None else value
    explicit = [v for v in value if v != "auto"]
    if "auto" not in value:
        return explicit
    if key is None:
        out = list(explicit)
        for d in detected:
            if d not in out:
                out.append(d)
        return out
    taken = {key(v) for v in explicit}
    return explicit + [d for d in detected if key(d) not in taken]


# ------------------------------------------------------------------- mounts

SKIP_FS = {"squashfs", "tmpfs", "devtmpfs", "overlay", "proc", "sysfs", "ramfs", "iso9660", "udf", "nsfs"}
SKIP_PREFIX = ("/boot", "/snap", "/var/lib/docker", "/var/snap", "/run", "/proc", "/sys", "/dev")


def detect_mounts(limit: int = 6) -> list[str]:
    seen_dev: set[str] = set()
    found: list[str] = []
    try:
        parts = psutil.disk_partitions(all=False)
    except Exception:
        return ["/"]
    for p in parts:
        mp, dev = p.mountpoint, p.device
        if p.fstype in SKIP_FS or "/loop" in dev:
            continue
        if mp != "/" and mp.startswith(SKIP_PREFIX):
            continue
        if dev in seen_dev:  # bind mounts of the same disk
            continue
        try:
            if psutil.disk_usage(mp).total < 1 << 30:  # < 1 GB: EFI and friends
                continue
        except OSError:
            continue
        seen_dev.add(dev)
        found.append(mp)
    found.sort(key=lambda m: (m != "/", m))
    return found[:limit] or ["/"]


# -------------------------------------------------------------------- network

def default_iface() -> str:
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            f = line.split()
            if len(f) > 2 and f[1] == "00000000":
                return f[0]
    except OSError:
        pass
    for name, st in psutil.net_if_stats().items():
        if st.isup and name != "lo" and not name.startswith(VIRTUAL_IFACES):
            return name
    return "-"


VIRTUAL_IFACES = ("lo", "docker", "br-", "veth", "tailscale", "virbr", "lxd", "lxc", "cni", "flannel", "zt", "wg", "tun")


def local_networks() -> list[str]:
    nets: list[str] = []
    for name, addrs in psutil.net_if_addrs().items():
        if name.startswith(VIRTUAL_IFACES):
            continue
        for a in addrs:
            if a.family not in (socket.AF_INET, socket.AF_INET6) or not a.netmask:
                continue
            try:
                addr = a.address.split("%")[0]
                mask = a.netmask
                if a.family == socket.AF_INET6:
                    # psutil gives the IPv6 netmask as an address; count its bits.
                    mask = str(bin(int(ipaddress.IPv6Address(mask))).count("1"))
                net = ipaddress.ip_network(f"{addr}/{mask}", strict=False)
            except ValueError:
                continue
            if net.is_private and not net.is_loopback and not net.is_link_local and str(net) not in nets:
                nets.append(str(net))
    return nets


def detect_allow() -> list[str]:
    base = ["127.0.0.1/32", "::1/128"]
    if shutil.which("tailscale") or Path("/var/lib/tailscale").exists():
        base += ["100.64.0.0/10", "fd7a:115c:a1e0::/48"]
    return base + [n for n in local_networks() if n not in base]


# --------------------------------------------------------------- host services

# (label, candidate units) - the first candidate that is installed is used.
SERVICE_CATALOG: list[tuple[str, list[str]]] = [
    ("DOCKER ENGINE", ["docker.service"]),
    ("PODMAN", ["podman.socket"]),
    ("SSH", ["ssh.service", "sshd.service", "ssh.socket"]),
    ("TAILSCALE", ["tailscaled.service"]),
    ("ZEROTIER", ["zerotier-one.service"]),
    ("WIREGUARD", ["wg-quick@wg0.service"]),
    ("CLOUDFLARED", ["cloudflared.service"]),
    ("NGINX", ["nginx.service"]),
    ("APACHE", ["apache2.service", "httpd.service"]),
    ("CADDY", ["caddy.service"]),
    ("MYSQL", ["mysql.service", "mysqld.service"]),
    ("MARIADB", ["mariadb.service"]),
    ("POSTGRESQL", ["postgresql.service"]),
    ("REDIS", ["redis-server.service", "redis.service"]),
    ("SAMBA", ["smbd.service", "smb.service"]),
    ("NFS SERVER", ["nfs-server.service", "nfs-kernel-server.service"]),
    ("NETDATA", ["netdata.service"]),
    ("COCKPIT", ["cockpit.socket"]),
    ("WEBMIN", ["webmin.service"]),
    ("PROMETHEUS", ["prometheus.service"]),
    ("NODE EXPORTER", ["prometheus-node-exporter.service", "node_exporter.service"]),
    ("GRAFANA", ["grafana-server.service"]),
    ("PLEX", ["plexmediaserver.service"]),
    ("JELLYFIN", ["jellyfin.service"]),
    ("PI-HOLE", ["pihole-FTL.service"]),
    ("UNBOUND", ["unbound.service"]),
    ("FAIL2BAN", ["fail2ban.service"]),
    ("UFW", ["ufw.service"]),
    ("K3S", ["k3s.service"]),
    ("LIBVIRT", ["libvirtd.service"]),
    ("SYNCTHING", ["syncthing@*.service"]),
    ("MOSQUITTO", ["mosquitto.service"]),
    ("HOME ASSISTANT", ["home-assistant@*.service", "homeassistant.service"]),
    ("CRON", ["cron.service", "crond.service", "cronie.service"]),
]

ON_STATES = {"enabled", "enabled-runtime", "alias", "generated", "indirect"}


def _unit_states() -> tuple[dict[str, str], set[str]]:
    """Installed unit files with their enablement state, and the units running now."""
    files: dict[str, str] = {}
    _, out = run_cmd(["systemctl", "list-unit-files", "--type=service,socket", "--no-legend", "--no-pager"],
                     timeout=4.0, strip=False)
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 2:
            files[f[0]] = f[1]
    active: set[str] = set()
    _, out = run_cmd(["systemctl", "list-units", "--type=service,socket", "--state=active", "--no-legend",
                      "--no-pager", "--plain"], timeout=4.0, strip=False)
    for line in out.splitlines():
        f = line.split()
        if f:
            active.add(f[0])
    return files, active


def detect_units() -> list[dict[str, str]]:
    if not shutil.which("systemctl"):
        return []
    files, active = _unit_states()
    found = []
    for label, candidates in SERVICE_CATALOG:
        for cand in candidates:
            if "*" in cand:
                rx = re.compile("^" + re.escape(cand).replace(r"\*", r"[^.]+") + "$")
                hits = sorted(u for u in active if rx.match(u)) or \
                    sorted(u for u, st in files.items() if rx.match(u) and st in ON_STATES and "@." not in u)
                if hits:
                    found.append({"name": label, "unit": hits[0]})
                    break
                continue
            if cand in active or files.get(cand) in ON_STATES:
                found.append({"name": label, "unit": cand.removesuffix(".service")})
                break
    return found


# ----------------------------------------------------------- container checks

# image substring -> (container port, HTTP path or None for TCP, label)
KNOWN_IMAGES: list[tuple[str, int, str | None, str]] = [
    ("home-assistant", 8123, "/", "HOME ASSISTANT"),
    ("homeassistant", 8123, "/", "HOME ASSISTANT"),
    ("grafana", 3000, "/api/health", "GRAFANA"),
    ("immich-server", 2283, "/api/server/ping", "IMMICH"),
    ("portainer", 9000, "/", "PORTAINER"),
    ("node-red", 1880, "/", "NODE-RED"),
    ("emqx", 18083, "/", "EMQX"),
    ("eclipse-mosquitto", 1883, None, "MOSQUITTO"),
    ("filebrowser", 80, "/health", "FILEBROWSER"),
    ("jellyfin", 8096, "/health", "JELLYFIN"),
    ("plex", 32400, "/identity", "PLEX"),
    ("nextcloud", 80, "/status.php", "NEXTCLOUD"),
    ("vaultwarden", 80, "/alive", "VAULTWARDEN"),
    ("uptime-kuma", 3001, "/", "UPTIME KUMA"),
    ("pihole", 80, "/admin/", "PI-HOLE"),
    ("adguardhome", 3000, "/", "ADGUARD"),
    ("frigate", 5000, "/api/version", "FRIGATE"),
    ("nginx-proxy-manager", 81, "/", "NGINX PROXY MGR"),
    ("traefik", 80, None, "TRAEFIK"),
    ("prometheus", 9090, "/-/healthy", "PROMETHEUS"),
    ("code-server", 8080, "/healthz", "CODE-SERVER"),
    ("syncthing", 8384, "/rest/noauth/health", "SYNCTHING"),
    ("qbittorrent", 8080, "/", "QBITTORRENT"),
    ("transmission", 9091, "/", "TRANSMISSION"),
    ("sonarr", 8989, "/ping", "SONARR"),
    ("radarr", 7878, "/ping", "RADARR"),
    ("prowlarr", 9696, "/ping", "PROWLARR"),
    ("gitea", 3000, "/api/healthz", "GITEA"),
    ("n8n", 5678, "/healthz", "N8N"),
    ("coolify", 8000, "/api/health", "COOLIFY"),
    ("postgres", 5432, None, "POSTGRES"),
    ("mariadb", 3306, None, "MARIADB"),
    ("mysql", 3306, None, "MYSQL"),
    ("redis", 6379, None, "REDIS"),
    ("mongo", 27017, None, "MONGODB"),
]

def _known(image: str) -> tuple[int, str | None, str] | None:
    img = image.lower().split("@")[0]
    for needle, port, path, label in KNOWN_IMAGES:
        if needle in img:
            return port, path, label
    return None


def container_checks(runtimes: list[ContainerRuntime] | None = None) -> list[dict[str, Any]]:
    """One probe per running container: its published port, or the known default on host networking."""
    checks = []
    for ep in (e for rt in (runtimes if runtimes is not None else from_config()) for e in rt.endpoints()):
        name, mapping = ep.name, ep.ports
        known = _known(ep.image)
        target: tuple[str, int] | None = None
        path: str | None = None
        label = name.upper().replace("_", " ").replace("-", " ")[:18]
        if known:
            kport, path, klabel = known
            label = klabel
            if kport in mapping:
                target = mapping[kport]
            elif ep.host_network:
                target = ("127.0.0.1", kport)
            elif mapping:  # app moved to another port: only check that it accepts connections
                target, path = sorted(mapping.values(), key=lambda t: t[1])[0], None
        elif mapping:
            target = sorted(mapping.values(), key=lambda t: t[1])[0]
        if not target:
            continue
        check: dict[str, Any] = {"name": label, "container": name, "auto": True}
        if path:
            check["url"] = f"http://{target[0]}:{target[1]}{path}"
        else:
            check["tcp_host"], check["tcp_port"] = target
        checks.append(check)
    return checks


# ------------------------------------------------------------------- claude

def claude_installed() -> bool:
    home = Path.home()
    return bool(shutil.which("claude") or (home / ".local/bin/claude").exists()
                or (home / ".local/share/claude/versions").exists())


# --------------------------------------------------------------------- apply

def resolve(config: dict[str, Any]) -> dict[str, Any]:
    """Fill the "auto" entries of a merged config in place and return it."""
    if is_auto(config.get("mounts")):
        config["mounts"] = expand(config["mounts"], detect_mounts())
    if config.get("network_interface") in ("auto", "", None):
        config["network_interface"] = default_iface()
    if is_auto(config.get("systemd_units")):
        config["systemd_units"] = expand(config["systemd_units"], detect_units(),
                                         key=lambda u: str(u.get("unit", "")).removesuffix(".service"))
    web = config.get("web") or {}
    if is_auto(web.get("allow")):
        web["allow"] = expand(web["allow"], detect_allow())
    if config.get("claude", "auto") == "auto":
        config["claude"] = claude_installed()
    else:
        config["claude"] = bool(config.get("claude"))
    if not config.get("title"):
        config["title"] = f"{socket.gethostname().upper()} // MATRIX SERVER MONITOR"
    if not config.get("operator"):
        config["operator"] = current_user()
    return config


def live_checks(config_checks: Any, runtimes: list[ContainerRuntime] | None = None) -> list[dict[str, Any]]:
    """Checks to probe now: explicit ones plus, with "auto", one per running container."""
    if not is_auto(config_checks):
        return list(config_checks or [])
    return expand(config_checks, container_checks(runtimes),
                  key=lambda c: str(c.get("container") or c.get("name")))


def report(config: dict[str, Any]) -> str:
    resolve(config)
    lines = [f"host        {socket.gethostname()}",
             f"interface   {config['network_interface']}",
             f"disks       {', '.join(config['mounts'])}",
             "services    " + (", ".join(f"{u['name']} ({u['unit']})" for u in config["systemd_units"]) or "-")]
    runtimes = from_config(config)
    checks = live_checks(config.get("checks"), runtimes)
    for rt in runtimes:
        found = rt.containers()
        lines.append(f"{rt.name:<11} " + (f"{len(found)} {rt.boot_unit}" if found is not None else rt.unavailable_hint))
    for c in checks:
        target = c.get("url") or f"tcp {c.get('tcp_host')}:{c.get('tcp_port')}"
        lines.append(f"  probe     {c['name']:<18} {target}")
    lines.append(f"tailscale   {'yes' if shutil.which('tailscale') else 'no'}")
    lines.append(f"claude code {'yes' if config['claude'] else 'no'}")
    web = config.get("web") or {}
    if web.get("enabled"):
        lines.append(f"web mirror  port {web.get('port', 8095)}  allow {', '.join(web.get('allow', []))}")
    else:
        lines.append("web mirror  off")
    return "\n".join(lines)


if __name__ == "__main__":
    from .config import merge_config

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "config.json"
    print(report(merge_config(path)))
