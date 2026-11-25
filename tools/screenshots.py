#!/usr/bin/env python3
"""Render documentation screenshots of the dashboard to PNG, with demo data.

    .venv/bin/python tools/screenshots.py [output dir]   (default: docs/screenshots)

Nothing from the real server ends up in the images: hostname, IPs, containers,
services and events are replaced by the fixed demo values below, so the
pictures are the same on every machine and safe to publish. The frames are
drawn by the dashboard's own renderer and painted with the green console
palette, cell by cell, so they look exactly like the monitor.
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from matrixdash import settings_menu, theme  # noqa: E402
from matrixdash.dashboard import Dashboard  # noqa: E402
from matrixdash.models import ClaudeInfo, Container, Event, Snapshot  # noqa: E402
from matrixdash.render.canvas import Canvas  # noqa: E402

HOST = "matrix-lab"
USER = "admin"
GIB = 1 << 30

# ------------------------------------------------------------------ demo data

DEMO_NET = {"mode": "FIXO", "ip": "192.168.1.50", "prefix": "24", "gateway": "192.168.1.1",
            "dns": "192.168.1.1, 1.1.1.1", "mac": "52:54:00:12:34:56", "ipv6": ""}

CONTAINERS = [
    ("immich_server", "running", "healthy", "6d", "ghcr.io/immich-app/immich-server:v1", ":2283", 3.1, "512M"),
    ("immich_postgres", "running", "healthy", "6d", "ghcr.io/immich-app/postgres:14", "-", 0.4, "188M"),
    ("homeassistant", "running", "", "3d", "ghcr.io/home-assistant/home-assistant:stable", "-", 1.8, "402M"),
    ("jellyfin", "running", "healthy", "6d", "jellyfin/jellyfin:latest", ":8096", 0.9, "260M"),
    ("nextcloud", "running", "", "2d", "nextcloud:29", ":8080", 0.3, "143M"),
    ("vaultwarden", "running", "healthy", "6d", "vaultwarden/server:latest", ":8081", 0.0, "21M"),
    ("grafana", "running", "", "6d", "grafana/grafana:latest", ":3000", 0.2, "88M"),
    ("uptime-kuma", "running", "healthy", "6d", "louislam/uptime-kuma:1", ":3001", 0.6, "97M"),
    ("pihole", "running", "healthy", "6d", "pihole/pihole:latest", ":53", 0.1, "64M"),
    ("watchtower", "exited", "", "1h", "containrrr/watchtower", "-", None, ""),
]
PROBES = {
    "immich_server": (True, 200, 4.0, "IMMICH"),
    "homeassistant": (True, 200, 7.0, "HOME ASSISTANT"),
    "jellyfin": (True, 200, 3.0, "JELLYFIN"),
    "nextcloud": (True, 200, 21.0, "NEXTCLOUD"),
    "vaultwarden": (True, 200, 2.0, "VAULTWARDEN"),
    "grafana": (True, 200, 5.0, "GRAFANA"),
    "uptime-kuma": (True, 200, 6.0, "UPTIME KUMA"),
    "pihole": (True, 200, 3.0, "PI-HOLE"),
}
UNITS = [("DOCKER ENGINE", "docker", "active"), ("SSH", "ssh", "active"), ("TAILSCALE", "tailscaled", "active"),
         ("NGINX", "nginx", "active"), ("SAMBA", "smbd", "active"), ("FAIL2BAN", "fail2ban", "active"),
         ("CRON", "cron", "active")]
EVENTS = [
    ("SYSTEM", "matrix dashboard v3.0 online", theme.G5),
    ("SYSTEM", "watching 10 containers, 7 host units", theme.G4),
    ("DOCKER", "watchtower exited (0)", theme.G4),
    ("HTTP", "nextcloud endpoint back (200)", theme.G5),
    ("NET", "new device on the LAN: 192.168.1.73 (TV SALA)", theme.AMBER),
    ("PROBE", "disk /mnt/storage 61% used  1.4T free", theme.G3),
    ("CLAUDE", "session started (2 active)", theme.CYAN),
]


def wave(n: int, base: float, amp: float, seed: int) -> list[float]:
    rnd = random.Random(seed)
    out, v = [], base
    for i in range(n):
        v = max(0.0, v * 0.7 + (base + amp * (0.5 + 0.5 * __import__("math").sin(i / 9 + seed))) * 0.3
                + rnd.uniform(-amp, amp) * 0.25)
        out.append(v)
    return out


def demo_snapshot() -> Snapshot:
    s = Snapshot(hostname=HOST, kernel="6.8.0-48-generic", cores=8)
    s.per_core = [18, 31, 12, 44, 9, 22, 27, 15]
    s.cpu = sum(s.per_core) / len(s.per_core)
    s.ram, s.ram_used, s.ram_total = 42.0, int(13.4 * GIB), 32 * GIB
    s.swap, s.swap_used, s.swap_total = 2.0, int(0.1 * GIB), 4 * GIB
    s.load, s.uptime_s, s.procs, s.temperature = (1.42, 1.18, 0.97), 6 * 86400 + 4 * 3600 + 17 * 60, 312, 47.0
    s.ip, s.iface = DEMO_NET["ip"], "eth0"
    s.disks = [("/", 23.0, int(107 * GIB), int(468 * GIB)), ("/mnt/storage", 61.0, int(2.24 * 1024 * GIB), int(3.64 * 1024 * GIB))]
    s.down, s.up = 6.2e6, 1.3e6
    s.internet = s.net4 = s.net6 = True
    s.lat4, s.lat6 = 12.0, 14.0
    s.latency = 12.0
    s.docker_ok = True
    s.containers = [Container(name=n, state=st, health=h, age=a, exit_code="0" if st == "exited" else "",
                                 image=img, ports=p, cpu=cpu, mem=mem)
                    for n, st, h, a, img, p, cpu, mem in CONTAINERS]
    s.units = list(UNITS)
    s.probes = dict(PROBES)
    s.claude = ClaudeInfo(running=True, version="2.1.0", sessions=2, remote=HOST, procs=3, cpu=6.5,
                             rss=640 << 20, since=time.time() - 5 * 3600, working=True)
    s.tailscale = {"state": "Running", "ip": "100.64.0.10", "online": True, "expiry_days": 120}
    s.cpu_hist = wave(300, 22, 18, 1)
    s.down_hist = [v * 2.5e5 for v in wave(300, 14, 12, 2)]
    s.up_hist = [v * 6e4 for v in wave(300, 14, 12, 3)]
    s.lat_hist = wave(120, 12, 4, 4)
    s.claude_hist = wave(120, 5, 6, 5)
    return s


# ------------------------------------------------------------------ painting

def palette() -> dict[int, tuple[tuple[int, int, int], tuple[int, int, int] | None]]:
    """style id -> (foreground, background) from the Linux console mapping."""
    rgb = {n: tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) for n, h in theme.LINUX_PALETTE.items()}

    def slot(code: int) -> int:
        return code - 30 if code < 90 else code - 90 + 8

    out = {}
    for style, sgr in theme.SGR_LINUX.items():
        fg, bg = rgb[7], None
        for part in sgr.split(";"):
            c = int(part)
            if 30 <= c <= 37 or 90 <= c <= 97:
                fg = rgb[slot(c)]
            elif 40 <= c <= 47:
                bg = rgb[c - 40]
        out[style] = (fg, bg)
    return out


def find_font() -> str:
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/TTF/DejaVuSansMono.ttf"):
        if os.path.exists(p):
            return p
    try:
        return subprocess.run(["fc-match", "-f", "%{file}", "monospace"], capture_output=True, text=True).stdout
    except OSError:
        sys.exit("precisa de uma fonte monoespaçada (apt install fonts-dejavu-core)")


def paint(canvas: Canvas, path: Path, size: int = 16):
    font = ImageFont.truetype(find_font(), size)
    cw = round(font.getlength("M"))
    asc, desc = font.getmetrics()
    ch = asc + desc
    pad = 18
    img = Image.new("RGB", (canvas.w * cw + pad * 2, canvas.h * ch + pad * 2), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    colors = palette()
    for y in range(canvas.h):
        for x in range(canvas.w):
            fg, bg = colors.get(canvas.styles[y][x], colors[theme.G3])
            px, py = pad + x * cw, pad + y * ch
            if bg:
                draw.rectangle([px, py, px + cw - 1, py + ch - 1], fill=bg)
            c = canvas.chars[y][x]
            if c != " " and canvas.styles[y][x] != theme.NONE:
                draw.text((px, py), c, font=font, fill=fg)
    img.save(path, optimize=True)
    print(f"  {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}  {img.width}x{img.height}")


# ------------------------------------------------------------------- scenes

def make_dashboard(cols: int, rows: int) -> Dashboard:
    os.environ["COLUMNS"], os.environ["LINES"] = str(cols), str(rows)
    cfg = ROOT / "config.example.json"
    settings_menu.read_ipv4 = lambda iface: dict(DEMO_NET)
    settings_menu.NETCFG_HELPER = sys.executable  # any existing file: shows the editable network fields
    d = Dashboard(cfg)
    d.config["claude"] = True
    d.config["network_interface"] = "eth0"
    d.config["title"] = f"{HOST.upper()} // MATRIX SERVER MONITOR"
    d.user, d.operator = USER, "ADMIN"
    d.collector.hostname = HOST
    d.portrait.fallback_text = HOST
    d.portrait.path = ROOT / "assets" / "__demo_no_image__.png"
    d.instant = True
    d.next_glitch = float("inf")
    snap = demo_snapshot()
    d.collector.snap = snap
    d.collector.events.clear()
    now_wall, now_mono = time.time(), time.monotonic()
    for i, (tag, text, style) in enumerate(EVENTS):
        d.collector.events.append(Event(now_wall - (len(EVENTS) - i) * 47, now_mono - 60, tag, text, style))
    d.boot.build_lines(snap)
    random.seed(7)
    for _ in range(120):
        d.rain.resize(cols, rows)
        d.rain.update()
    return d


def shot(name: str, cols: int, rows: int, out: Path, setup=None, at: float | None = None):
    d = make_dashboard(cols, rows)
    if setup:
        setup(d)
    if at is not None and at < 0:  # negative = seconds before the end of the boot sequence
        at = d.boot.duration() + at
    t = at if at is not None else d.boot.duration() + 14.0
    canvas = d.render_canvas(t)
    paint(canvas, out / name)


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    print("gerando prints (dados de demonstração):")
    shot("dashboard.png", 190, 52, out)
    shot("boot.png", 120, 34, out, at=-0.4)
    shot("help.png", 160, 46, out, lambda d: setattr(d, "help_open", True))
    shot("settings.png", 160, 46, out, lambda d: d.menu.open())
    shot("medium.png", 130, 40, out)
    shot("compact.png", 92, 26, out)
    # One preview per color theme (menu C -> PAINEL -> Tema).
    (out / "temas").mkdir(exist_ok=True)
    for name in theme.THEMES:
        shot(f"temas/{name}.png", 150, 44, out, lambda d, name=name: d.set_theme(name))
    theme.apply(theme.DEFAULT_THEME)


if __name__ == "__main__":
    main()
