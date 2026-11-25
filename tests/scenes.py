"""Deterministic dashboard frames used by the golden tests.

Every scene builds the dashboard with the demo data from tools/screenshots.py,
freezes the clock and the random generator and renders one canvas. The same
scene always produces the same characters and styles, so any change in the
drawing code shows up as a diff against tests/golden/<scene>.txt.
"""

from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

# Fixed clock: Tuesday 2026-11-24 14:32:07 UTC.
WALL = 1795530727.0
MONO = 100000.0

_real_localtime = time.localtime
_real_strftime = time.strftime


def freeze_clock():
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()
    time.time = lambda: WALL
    time.monotonic = lambda: MONO
    time.localtime = lambda secs=None: _real_localtime(WALL if secs is None else secs)
    time.strftime = lambda fmt, t=None: _real_strftime(fmt, t if t is not None else time.localtime())


freeze_clock()

import screenshots as demo  # noqa: E402  (imports the dashboard after the clock is frozen)

GIB = 1 << 30


def backup_state() -> dict:
    return {
        "status": "running", "phase": "uploading", "updated": WALL - 3, "dest": "gdrive:Backup",
        "source": "/data", "source_bytes": 1.2e12, "uploaded_bytes": 4.6e11, "initial_complete": False,
        "today": {"date": "2026-11-24", "bytes": 3.1e10},
        "run": {"speed": 3.2e6, "bwlimit": "3M", "transfers": 812, "checks": 40210, "errors": 2,
                "transferring": [{"name": "fotos/2024/viagem/IMG_2041.HEIC", "percentage": 37},
                                 {"name": "videos/aniversario.mp4", "percentage": 82}]},
    }


def icloud_state(status: str = "downloading") -> dict:
    return {"container": "icloudpd", "state": "running" if status != "paused" else "exited", "items": 18234,
            "bytes": 96 * GIB, "total": 25110, "speed": 2.4e6, "today": 3 * GIB,
            "current": "2023/08/14/IMG_8812.HEIC", "limit": "3M", "status": status, "next_check": WALL + 1800}


def plan_state() -> dict:
    return {"windows": {"five_hour": {"pct": 64.0, "resets": WALL + 2 * 3600},
                        "seven_day": {"pct": 92.0, "resets": WALL + 3 * 86400}},
            "updated": WALL - 30, "plan": "Max"}


def usage_state() -> dict:
    def win(cost: float, tokens: float, msgs: int) -> dict:
        return {"cost": cost, "tokens": tokens, "messages": msgs, "input": tokens * 0.1, "output": tokens * 0.05,
                "cache_write": tokens * 0.25, "cache_read": tokens * 0.6}

    hour0 = int(WALL // 3600 * 3600)
    day0 = WALL - WALL % 86400
    hourly = [(hour0 - (23 - i) * 3600, win(0.4 + (i * 37 % 11) / 4, 1e5 * (i % 7 + 1), i)) for i in range(24)]
    daily = [(day0 - (13 - i) * 86400, win(3 + (i * 53 % 17), 2e6 * (i % 5 + 1), 40 + i)) for i in range(14)]
    weeks = [(day0 - 1 * 86400 - i * 7 * 86400, win(80 - i * 9, 4e7 - i * 3e6, 900)) for i in range(4)]
    return {
        "today": win(12.37, 4.2e6, 183), "last5h": win(6.1, 2.2e6, 77), "week": win(71.9, 3.1e7, 1220),
        "last7d": win(88.0, 3.6e7, 1500), "last30d": win(301.4, 1.4e8, 6100), "total": win(912.0, 4.4e8, 20500),
        "models": [("claude-opus-4-5", win(700.0, 3e8, 12000)), ("claude-sonnet-4-5", win(180.0, 1.2e8, 7000)),
                   ("claude-haiku-4-5", win(32.0, 2e7, 1500))],
        "sessions": 41, "active_sessions": 2, "since": WALL - 90 * 86400, "updated": WALL - 50,
        "hourly": hourly, "daily": daily, "weeks": weeks,
    }


def netmap_state() -> tuple[dict, dict]:
    def dev(ip, name, vendor, link, role="", online=True, ms=3.0, new=False, est=False):
        return {"mac": f"aa:bb:cc:00:00:{ip.split('.')[-1]:0>2}"[-17:], "ip": ip, "name": name, "vendor": vendor,
                "link": link, "est": est, "role": role, "online": online, "ms": ms if online else None,
                "first": WALL - 86400 * 30, "last": WALL if online else WALL - 7200, "ip6": 0, "ip6s": [],
                "new": new}

    devices = [
        dev("192.168.1.1", "", "TP-Link", "gw", "router", ms=1.0),
        dev("192.168.1.50", demo.HOST, "este servidor", "cabo", "server", ms=0.0),
        dev("192.168.1.20", "NOTEBOOK", "Dell", "wifi", est=True, ms=12.0),
        dev("192.168.1.31", "TV SALA", "Samsung", "wifi", ms=40.0),
        dev("192.168.1.42", "NAS", "Synology", "cabo", ms=2.0),
        dev("192.168.1.73", "", "Xiaomi", "?", new=True, ms=95.0),
        dev("192.168.1.80", "IMPRESSORA", "HP", "wifi", online=False),
    ]
    netmap = {
        "lan": {"subnet": "192.168.1.0/24", "gateway": "192.168.1.1", "devices": devices},
        "tailscale": [
            {"name": "celular", "ip": "100.64.0.11", "os": "android", "online": True, "last": WALL,
             "path": "direto", "exit": False},
            {"name": "trabalho", "ip": "100.64.0.12", "os": "windows", "online": True, "last": WALL,
             "path": "relay gru", "exit": True},
            {"name": "tablet", "ip": "100.64.0.13", "os": "ios", "online": False, "last": WALL - 3 * 86400,
             "path": "", "exit": False},
        ],
        "docker": [
            {"name": "immich_default", "driver": "bridge", "subnet": "172.18.0.0/16",
             "members": [("immich_postgres", "172.18.0.3"), ("immich_server", "172.18.0.2")]},
            {"name": "bridge", "driver": "bridge", "subnet": "172.17.0.0/16",
             "members": [("jellyfin", "172.17.0.2"), ("nextcloud", "172.17.0.3")]},
            {"name": "empty_net", "driver": "bridge", "subnet": "172.30.0.0/16", "members": []},
        ],
        "at": WALL - 12,
    }
    traffic = {
        "peers": {
            "192.168.1.20": {"rx": 2.5e6, "tx": 1.2e5, "svc": ["jellyfin", ":445"], "hist": [1e4 * i for i in range(40)]},
            "192.168.1.42": {"rx": 4e4, "tx": 3e6, "svc": ["→https"], "hist": [5e4] * 40},
            "100.64.0.11": {"rx": 1e5, "tx": 2e4, "svc": ["ssh"], "hist": [1e3] * 40},
            "8.8.8.8": {"rx": 3e3, "tx": 9e3, "svc": [], "hist": [0.0] * 40},
        },
        "containers": {"immich_server": {"rx": 1.5e6, "tx": 2e5}, "jellyfin": {"rx": 3e4, "tx": 2.6e6}},
        "ifaces": {"eth0": {"rx": 6.2e6, "tx": 1.3e6}, "tailscale0": {"rx": 1.2e5, "tx": 3e4}},
        "ready": True,
    }
    return netmap, traffic


def argocd_items() -> list[dict]:
    def app(name, ns, sync="Synced", health="Healthy", phase="Succeeded", msg="", days=3):
        return {"metadata": {"name": name, "namespace": "argocd"},
                "spec": {"project": "default", "destination": {"namespace": ns},
                         "source": {"repoURL": "https://example.com/infra.git", "path": f"k8s/{ns}",
                                    "targetRevision": "main"},
                         "syncPolicy": {"automated": {"selfHeal": True}}},
                "status": {"sync": {"status": sync, "revision": "a1b2c3d4e5f6"}, "health": {"status": health},
                           "operationState": {"phase": phase, "message": msg,
                                              "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                          time.gmtime(WALL - days * 86400))}}}
    return [app("shop", "shop", health="Degraded", days=0.02), app("blog", "blog", sync="OutOfSync", days=0.5),
            app("billing", "billing", phase="Failed", msg="one or more objects failed to apply: quota exceeded"),
            app("home", "home"), app("media", "media", days=12), app("monitoring", "monitoring", days=30)]


def k3s_containers() -> list:
    from matrixdash.models import Container
    rows = [("shop/api", "pending", "unhealthy", "ImagePullBackOff", "shop 0/1", None, ""),
            ("home/assistant", "running", "healthy", "", "home 1/1", 2.1, "410M"),
            ("media/jellyfin", "running", "healthy", "", "media 1/1", 0.8, "260M"),
            ("monitoring/grafana", "running", "starting", "", "monitoring 1/2", 0.3, "90M")]
    return [Container(name=n, state=st, health=h, age="3d", exit_code=r, image="app:1", ports=p, cpu=cpu,
                      mem=mem, runtime="k3s", display=n.split("/")[1]) for n, st, h, r, p, cpu, mem in rows]


# ------------------------------------------------------------------- scenes

def _render(cols: int, rows: int, setup=None, at: float | None = None, snap=None, after: float = 14.0):
    random.seed(1234)
    d = demo.make_dashboard(cols, rows)
    if snap:
        snap(d.collector.snap)
    random.seed(99)
    if setup:
        setup(d)
    if at is not None and at < 0:
        at = d.boot.duration() + at
    t = at if at is not None else d.boot.duration() + after
    return d.render_canvas(t)


def _integrations(s, ic_status="downloading"):
    s.backup = backup_state()
    s.icloud = icloud_state(ic_status)
    s.plan = plan_state()
    s.usage = usage_state()


def _netmap(s):
    s.netmap, s.nettraffic = netmap_state()


def _netmap_wireguard(s):
    _netmap(s)
    peer = {"id": "AAAAAAAA", "allowed": ["10.8.0.2/32"], "keepalive": 25, "rx": 0, "tx": 0}
    s.wireguard = {"peers_known": True, "at": WALL, "ifaces": [{
        "name": "wg0", "address": "10.8.0.1/24", "rx": 0, "tx": 0, "rx_rate": 0.0, "tx_rate": 0.0, "peers": [
            dict(peer, name="casa", endpoint="203.0.113.7:51820", handshake=WALL - 40, online=True,
                 rx_rate=2.1e4, tx_rate=3.4e5),
            dict(peer, id="BBBBBBBB", name="notebook", allowed=["10.8.0.3/32"], keepalive=0, endpoint="",
                 handshake=WALL - 7200, online=False, rx_rate=0.0, tx_rate=0.0)]}]}


def _menu_on_containers(d):
    d.menu.open()
    idx = next(i for i, it in enumerate(d.menu.items) if it["kind"] == "container")
    d.menu.cursor = idx
    d.menu.handle("right")


def _confirm(d):
    d.confirm("REINICIAR O SERVIDOR", ["O servidor fica fora do ar por 1 a 2 minutos.",
                                       "Painel e serviços habilitados voltam sozinhos."], lambda: None)
    d.notify("tela redesenhada", demo.theme.G4, 2)


def _usage_fixed(d):
    d.usage_mode = "relatório"


def _icloud_cfg(d):
    d.config["icloud"] = {"container": "icloudpd", "limit": "3M"}


def _cluster(d):
    from matrixdash.integrations import ArgoCDIntegration
    from matrixdash.integrations.argocd import parse_app, problem
    from matrixdash.runtime.k3s import K3sRuntime
    d.collector.runtimes = d.collector.runtimes[:1] + [K3sRuntime()]
    s = d.collector.snap
    s.containers = k3s_containers() + s.containers
    s.runtimes = [("docker", "DOCKER", True), ("k3s", "K3S", True)]
    d.collector.containers = s.containers
    argo = d.integration(ArgoCDIntegration)
    apps = sorted((parse_app(i) for i in argocd_items()), key=lambda a: (not problem(a), a["name"]))
    argo.explain(apps)
    s.argocd = {"apps": apps, "at": WALL - 5}


def _argocd_view(d):
    _cluster(d)
    d.toggle_view("argocd")


def _menu_typing_secret(d):
    d.config["alerts"] = {"delay": 2, "repeat": 60, "discord": {"webhook": "https://discord.com/api/webhooks/1/abcd"}}
    d.menu.open()
    d.menu.cursor = next(i for i, it in enumerate(d.menu.items) if it.get("key") == "tg_token")
    d.menu.handle("enter")
    for ch in "123456:SECRET":
        d.menu.handle(ch)


SCENES = {
    "dashboard": lambda: _render(190, 52),
    "boot": lambda: _render(120, 34, at=-0.4),
    "help": lambda: _render(160, 46, lambda d: setattr(d, "help_open", True)),
    "settings": lambda: _render(160, 46, lambda d: d.menu.open()),
    "settings_alerts": lambda: _render(160, 46, _menu_typing_secret),
    "settings_containers": lambda: _render(160, 46, _menu_on_containers),
    "medium": lambda: _render(130, 40),
    "compact": lambda: _render(92, 26),
    "wipe": lambda: _render(170, 48, after=0.5),
    "integrations": lambda: _render(200, 56, _icloud_cfg, snap=_integrations, after=4.0),
    "integrations_icloud": lambda: _render(200, 56, _icloud_cfg, snap=_integrations),
    "icloud_login": lambda: _render(200, 56, _icloud_cfg, snap=lambda s: _integrations(s, "login")),
    "usage": lambda: _render(200, 56, _usage_fixed, snap=_integrations),
    "netmap": lambda: _render(200, 56, lambda d: setattr(d, "netmap_open", True), snap=_netmap),
    "netmap_wireguard": lambda: _render(200, 56, lambda d: setattr(d, "netmap_open", True),
                                        snap=_netmap_wireguard),
    "netmap_narrow": lambda: _render(140, 48, lambda d: setattr(d, "netmap_open", True), snap=_netmap),
    "confirm": lambda: _render(160, 46, _confirm),
    "compact_integrations": lambda: _render(96, 40, snap=_integrations),
    "cluster": lambda: _render(200, 60, _cluster),
    "argocd": lambda: _render(200, 56, _argocd_view),
}


def dump(canvas) -> str:
    """Characters, then styles (one hex digit per cell), row by row."""
    lines = ["".join(row) for row in canvas.chars]
    lines.append("--- styles ---")
    lines += ["".join(format(st, "x") for st in row) for row in canvas.styles]
    return "\n".join(lines) + "\n"
