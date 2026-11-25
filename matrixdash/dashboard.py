"""Main loop: keyboard, layout of the panels and frame output."""

from __future__ import annotations

import os
import random
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, TypeVar

from . import VERSION, alerts, autodetect, theme
from .collector import Collector
from .config import merge_config
from .fmt import fmt_uptime
from .integrations import ArgoCDIntegration, ClaudeIntegration, Integration
from .models import Snapshot
from .panels.agent import AgentSection
from .panels.argocd import ArgoPanel, ArgoSection
from .panels.backup import BackupPanel
from .panels.base import Panel
from .panels.boot import BootScreen
from .panels.console import ConsolePanel
from .panels.header import HeaderPanel
from .panels.icloud import ICloudPanel
from .panels.keybar import KeyBar
from .panels.netmap import NetMapPanel
from .panels.network import NetworkPanel
from .panels.overlays import Overlays
from .panels.portrait import PortraitPanel
from .panels.services import ServicesPanel, ServicesSection
from .panels.system import SystemPanel
from .panels.usage import UsagePanel
from .render.canvas import Canvas
from .render.charts import graph_rows
from .render.portrait import Portrait
from .render.rain import MatrixRain
from .render.screen import Screen
from .render.widgets import level
from .settings_menu import SettingsMenu
from .terminal import Terminal
from .theme import (
    AMBER,
    CYAN,
    G2,
    G3,
    G4,
    G5,
    G6,
    LINUX_PALETTE,
    MATRIX_CHARS,
    NONE,
    RED,
    SGR_256,
    SGR_LINUX,
    TEXT,
)
from .web_view import WebMirror

I = TypeVar("I", bound=Integration)

# Display order of the key bar. Keys owned by an integration only show while it is enabled.
HOTKEYS = [
    ("H", "ajuda"), ("C", "config"), ("B", "backup"), ("S", "sync agora"), ("V", "rede"), ("P", "icloud"),
    ("U", "uso IA"), ("A", "argocd"), ("W", "mapa rede"), ("X", "terminal"), ("N", "teste rede"), ("E", "economia"),
    ("T", "apagar tela"), ("M", "chuva"), ("I", "retrato"), ("D", "desligar"), ("R", "reiniciar"),
]
IGNORED_KEYS = ("", "esc", "enter", " ", "up", "down", "left", "right", "backspace")


class Dashboard:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.base_dir = config_path.resolve().parent
        self.config = merge_config(config_path)
        image_path = Path(self.config.get("image", "assets/portrait.txt"))
        if not image_path.is_absolute():
            image_path = self.base_dir / image_path
        self.portrait = Portrait(image_path, socket.gethostname())
        self.user = autodetect.current_user()
        self.operator = str(self.config.get("operator") or self.user).upper()

        self.fps = max(2, min(30, int(self.config.get("fps", 12))))
        self.thresholds = self.config.get("thresholds", {})
        self.matrix_enabled = True
        self.image_enabled = True
        self.boot_enabled = bool(self.config.get("boot_animation", True))

        self.theme = theme.apply(str(self.config.get("theme") or theme.DEFAULT_THEME),
                                 self.config.get("theme_colors") or {})
        self.linux_console = os.environ.get("TERM", "") == "linux"
        self.terminal = Terminal(self.linux_console and bool(self.config.get("console_palette", True)))
        self.screen = Screen(SGR_LINUX if self.linux_console else SGR_256)

        size = shutil.get_terminal_size((120, 40))
        self.width = max(40, size.columns)
        self.height = max(18, size.lines)
        self.rain = MatrixRain(self.width, self.height, float(self.config.get("matrix_density", 0.45)))

        self.collector = Collector(self.config)
        self.integrations = self.collector.integrations
        self.eased: dict[str, float] = {}
        self.instant = False
        self.art_size: tuple[int, int] | None = None
        self.graph_cache: dict[tuple, list[str]] = {}
        self.graph_cache_snap: Snapshot | None = None
        self.start = time.monotonic()
        self.next_glitch = self.start + random.uniform(6, 10)
        self.glitch_until = 0.0
        self.glitch_rows: dict[int, int] = {}
        self.last_full_redraw = self.start
        self.stop = False
        self.eco = False
        self.blanked = False
        self.help_open = False
        self.modal: dict[str, Any] | None = None
        self.toast: tuple[str, int, float] | None = None
        self.speedtest_running = False
        self.menu = SettingsMenu(self)
        self.web: WebMirror | None = None
        self.usage_mode = "auto"
        self.netmap_open = False
        # full-screen view shown in place of the system and services panels ("argocd")
        self.view: str | None = None
        self.auto_blanked = False
        self.wake_until = 0.0

        self.boot = BootScreen(self)
        self.header = HeaderPanel(self)
        self.system = SystemPanel(self)
        self.services = ServicesPanel(self)
        self.usage = UsagePanel(self)
        self.portrait_panel = PortraitPanel(self)
        self.netmap = NetMapPanel(self)
        self.network = NetworkPanel(self)
        self.icloud = ICloudPanel(self)
        self.backup = BackupPanel(self)
        self.console = ConsolePanel(self)
        self.keybar = KeyBar(self)
        self.overlays = Overlays(self)
        self.agent = AgentSection()
        self.argo_section = ArgoSection()
        self.views: dict[str, Panel] = {"argocd": ArgoPanel(self)}

    def integration(self, kind: type[I]) -> I:
        return self.collector.integration(kind)

    # --- keyboard

    def read_key(self):
        if self.web:
            for key in self.web.pop_keys():
                # A web viewer's X opens the terminal in the browser, never the local console.
                if key.lower() != "x":
                    self.handle_key(key)
        try:
            for key in self.terminal.keys():
                self.handle_key(key)
        except Exception:
            pass

    def open_shell(self):
        """Hand the local console to a login shell; the dashboard resumes when it exits."""
        if not self.terminal.interactive():
            self.notify("sem console local: use o terminal da página web", AMBER)
            return
        self.collector.emit("SYSTEM", "terminal local aberto", CYAN)
        try:
            self.terminal.shell()
        except OSError as exc:
            self.collector.emit("ERROR", f"terminal: {exc}"[:80], RED)
        finally:
            self.screen.invalidate()
            self.collector.emit("SYSTEM", "terminal local fechado", G4)

    def notify(self, text: str, style: int = G5, seconds: float = 3.5):
        self.toast = (text, style, time.monotonic() + seconds)

    def confirm(self, title: str, lines: list[str], action, seconds: float = 10.0):
        self.modal = {"title": title, "lines": lines, "action": action, "deadline": time.monotonic() + seconds}

    def handle_key(self, key: str):
        if self.blanked:
            self.blanked = False
            if self.auto_blanked:
                self.auto_blanked = False
                self.wake_until = time.monotonic() + 300
                self.notify("tela ligada por 5 min", G5, 3)
            else:
                self.notify("tela ligada", G5, 2)
            self.screen.invalidate()
            return
        k = key.lower()
        if self.modal:
            modal, self.modal = self.modal, None
            if k in ("s", "y"):
                modal["action"]()
            else:
                self.notify("cancelado", G4, 2)
            return
        if self.menu.active:
            self.menu.handle(key)
            return
        if self.help_open:
            self.help_open = False
            if k in ("h", "?", "esc", "enter", " ", ""):
                return
        if k in ("h", "?"):
            self.help_open = True
        elif k == "c":
            self.menu.open()
        elif k == "m":
            self.matrix_enabled = not self.matrix_enabled
            self.notify(f"chuva matrix {'ligada' if self.matrix_enabled else 'desligada'}", G5, 2)
        elif k == "i":
            self.image_enabled = not self.image_enabled
            self.notify(f"retrato {'ligado' if self.image_enabled else 'desligado'}", G5, 2)
        elif k == "g":
            self.next_glitch = time.monotonic()
        elif k in ("l", "\x0c"):
            self.screen.invalidate()
            self.notify("tela redesenhada", G4, 2)
        elif k == "e":
            self.eco = not self.eco
            self.matrix_enabled = not self.eco
            self.notify(f"modo economia {'ligado: 4 fps, sem chuva' if self.eco else 'desligado'}", G5)
        elif k == "t":
            self.blanked = True
            self.screen.invalidate()
        elif any(integ.handle_key(k, self) for integ in self.integrations):
            pass
        elif k == "n":
            self.start_speedtest()
        elif k == "x":
            self.open_shell()
        elif k == "w":
            self.netmap_open = not self.netmap_open
            self.view = None
            self.screen.invalidate()
            if self.netmap_open and not self.collector.snap.netmap:
                self.notify("mapeando a rede... primeira varredura leva ~5 s", CYAN, 4)
        elif k == "d":
            self.confirm("DESLIGAR O SERVIDOR", [
                "Todos os serviços e containers serão parados.",
                "Para ligar de novo é preciso acesso físico (ou Wake-on-LAN).",
            ], lambda: self.power("poweroff"))
        elif k == "r":
            self.confirm("REINICIAR O SERVIDOR", [
                "O servidor fica fora do ar por 1 a 2 minutos.",
                "Painel e serviços habilitados voltam sozinhos.",
            ], lambda: self.power("reboot"))
        elif k == "q":
            self.confirm("FECHAR O PAINEL", [
                "O monitor fica sem o painel até reiniciar o serviço",
                "(ou o servidor). Os serviços continuam rodando.",
            ], lambda: setattr(self, "stop", True))
        elif k not in IGNORED_KEYS:
            self.notify(f"tecla '{k}' sem função · H mostra os atalhos", G3, 2.5)

    def available_hotkeys(self) -> list[tuple[str, str]]:
        """Only the keys whose feature exists on this server."""
        skip = {k for integ in self.integrations if not integ.enabled() for k in integ.hotkeys}
        return [(k, lbl) for k, lbl in HOTKEYS if k not in skip]

    # --- actions

    def update_auto_blank(self):
        sched = self.config.get("screen_off") or {}
        if not sched.get("enabled"):
            if self.auto_blanked:
                self.auto_blanked = self.blanked = False
                self.screen.invalidate()
            return
        now = time.strftime("%H:%M")
        start, end = str(sched.get("from", "00:00")), str(sched.get("to", "07:00"))
        in_window = start <= now < end if start <= end else (now >= start or now < end)
        busy = self.menu.active or self.modal is not None
        if in_window and not self.blanked and not busy and time.monotonic() > self.wake_until:
            self.blanked = self.auto_blanked = True
            self.screen.invalidate()
        elif not in_window and self.auto_blanked:
            self.auto_blanked = self.blanked = False
            self.screen.invalidate()

    def power(self, verb: str):
        label = "desligamento" if verb == "poweroff" else "reinício"
        self.collector.emit("SYSTEM", f"{label} solicitado pelo teclado", AMBER)
        try:
            result = subprocess.run(["sudo", "-n", "/usr/bin/systemctl", verb],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=15)
            ok = result.returncode == 0
        except Exception:
            ok = False
        if ok:
            self.notify("DESLIGANDO..." if verb == "poweroff" else "REINICIANDO...", AMBER, 30)
        else:
            self.notify("sem permissão: rode  sudo ./install_hotkeys_sudo.sh", RED, 8)
            self.collector.emit("ERROR", f"{label} negado: falta a regra do sudo", RED)

    def start_speedtest(self):
        if self.speedtest_running:
            self.notify("teste de velocidade já em andamento", G4)
            return
        self.speedtest_running = True
        self.notify("testando velocidade da internet...", CYAN, 6)
        self.collector.emit("NET", "teste de velocidade iniciado", CYAN)
        threading.Thread(target=self._speedtest, daemon=True).start()

    def _speedtest(self):
        try:
            started = time.monotonic()
            req = urllib.request.Request("https://speed.cloudflare.com/__down?bytes=25000000",
                                         headers={"User-Agent": f"matrix-dashboard/{VERSION}"})
            got = 0
            with urllib.request.urlopen(req, timeout=30) as resp:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    got += len(chunk)
            down = got * 8 / (time.monotonic() - started) / 1e6
            payload = os.urandom(10_000_000)
            started = time.monotonic()
            req = urllib.request.Request("https://speed.cloudflare.com/__up", data=payload, method="POST",
                                         headers={"User-Agent": f"matrix-dashboard/{VERSION}",
                                                  "Content-Type": "application/octet-stream"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp.read()
            up = len(payload) * 8 / (time.monotonic() - started) / 1e6
            self.collector.emit("NET", f"velocidade: down {down:.0f} Mbps · up {up:.0f} Mbps", G5)
            self.notify(f"down {down:.0f} Mbps · up {up:.0f} Mbps", G5, 8)
        except Exception as exc:
            self.collector.emit("NET", f"teste de velocidade falhou: {exc}"[:70], RED)
            self.notify("teste de velocidade falhou", RED)
        finally:
            self.speedtest_running = False

    # --- helpers used by the panels

    def ease(self, key: str, target: float, rate: float = 0.22) -> float:
        """Value that glides towards `target` a bit every frame (instantly in --once and the tests)."""
        if self.instant:
            return target
        cur = self.eased.get(key, 0.0)
        cur += (target - cur) * rate
        if abs(target - cur) < 0.05:
            cur = target
        self.eased[key] = cur
        return cur

    def graph(self, name: str, values: list[float], width: int, height: int, vmax: float | None = None) -> list[str]:
        # History only changes once per second, so graphs are rebuilt per snapshot.
        if self.graph_cache_snap is not self.collector.snap:
            self.graph_cache = {}
            self.graph_cache_snap = self.collector.snap
        key = (name, width, height, vmax)
        if key not in self.graph_cache:
            self.graph_cache[key] = graph_rows(values, width, height, vmax)
        return self.graph_cache[key]

    def level_style(self, metric: str, value: float) -> int:
        return level(value, float(self.thresholds.get(metric, 999)))

    def service_sections(self) -> list[ServicesSection]:
        sections: list[ServicesSection] = []
        if self.integration(ArgoCDIntegration).enabled():
            sections.append(self.argo_section)
        if self.integration(ClaudeIntegration).enabled():
            sections.append(self.agent)
        return sections

    def set_theme(self, name: str) -> str:
        """Switch colors now: terminal, Linux console palette and open web pages."""
        self.theme = theme.apply(name, self.config.get("theme_colors") or {})
        self.screen = Screen(SGR_LINUX if self.linux_console else SGR_256)
        self.terminal.load_palette()
        if self.web:
            self.web.palette_changed()
        return self.theme

    def toggle_view(self, name: str):
        self.view = None if self.view == name else name
        self.netmap_open = False
        self.screen.invalidate()

    def alerts(self, s: Snapshot) -> list[str]:
        return [a.text for a in alerts.active(s, self.thresholds, self.integrations)]

    def usage_page_active(self, s: Snapshot, t: float) -> bool:
        if not s.usage or self.usage_mode == "retrato":
            return False
        if self.usage_mode == "relatório":
            return True
        # auto: 40 s portrait, 20 s report
        return (t % 60) >= 40

    # --- frame

    def update_glitch(self, now: float):
        if now >= self.next_glitch:
            n_rows = len(self.portrait.rows) or 40
            start = random.randrange(max(1, n_rows - 4))
            self.glitch_rows = {}
            for i in range(random.randint(1, 4)):
                self.glitch_rows[start + i] = random.choice([-5, -4, -3, -2, 2, 3, 4, 6])
            if random.random() < 0.4:
                self.glitch_rows[random.randrange(n_rows)] = random.choice([-8, 8])
            self.glitch_until = now + random.uniform(0.15, 0.35)
            self.next_glitch = now + random.uniform(5.0, 11.0)

    def draw_compact(self, c: Canvas, s: Snapshot, t: float):
        alerts = self.alerts(s)
        c.box(0, 0, c.w, 3, "◈ MATRIX SERVER", time.strftime("%H:%M:%S"), RED if alerts else G2, G5)
        c.put(2, 1, f"{s.hostname}  {s.ip}  up {fmt_uptime(s.uptime_s)}"[: c.w - 4], TEXT)
        rest = c.h - 3
        sys_h = min(14, max(9, rest // 2))
        self.system.draw(c, s, 0, 3, c.w, sys_h, t)
        if rest - sys_h >= 5:
            self.services.draw(c, s, 0, 3 + sys_h, c.w, rest - sys_h, t)

    def draw_bottom(self, c: Canvas, s: Snapshot, y: int, h: int, left_w: int, show_portrait: bool, t: float):
        """Network graphs, the backup / iCloud slot when configured, and the console."""
        if s.backup is not None and self.width >= 150:
            net_w = max(48, self.width * 31 // 100)
            backup_w = max(46, self.width * 30 // 100)
            self.network.draw(c, s, 0, y, net_w, h, t)
            ic_status = str((s.icloud or {}).get("status", ""))
            if s.icloud and ic_status == "login":
                self.icloud.draw(c, s, net_w, y, backup_w, h, t, "!")
            elif s.icloud:
                # Drive and iCloud share the slot, alternating every 8 s.
                if int(t / 8) % 2 == 0:
                    self.backup.draw(c, s, net_w, y, backup_w, h, t, "1/2")
                else:
                    self.icloud.draw(c, s, net_w, y, backup_w, h, t, "2/2")
            else:
                self.backup.draw(c, s, net_w, y, backup_w, h, t)
            self.console.draw(c, s, net_w + backup_w, y, self.width - net_w - backup_w, h, t)
        else:
            net_w = left_w if show_portrait else self.width // 2
            self.network.draw(c, s, 0, y, net_w, h, t)
            self.console.draw(c, s, net_w, y, self.width - net_w, h, t)

    def render_canvas(self, elapsed: float) -> Canvas:
        size = shutil.get_terminal_size((120, 40))
        self.width = max(40, size.columns)
        self.height = max(18, size.lines)
        self.rain.resize(self.width, self.height)
        c = Canvas(self.width, self.height)

        s = self.collector.snap
        boot_t = self.boot.duration() if self.boot_enabled and self.boot.lines else 0.0
        booting = elapsed < boot_t
        compact = self.width < 100 or self.height < 30

        header_h = HeaderPanel.HEIGHT
        bottom_h = 9 if self.height >= 44 else 7
        body_y = header_h
        body_h = self.height - header_h - bottom_h
        if self.art_size is None:
            self.art_size = self.portrait.natural_size()
        show_portrait = self.image_enabled and self.width >= 140 and body_h >= 24 and not compact
        if show_portrait:
            portrait_w = min(self.art_size[0] + 4, self.width - 72)
            left_w = self.width - portrait_w
        else:
            portrait_w = 0
            left_w = self.width

        if self.matrix_enabled:
            self.rain.update()
            dim_rect = None
            if show_portrait and not booting:
                dim_rect = (left_w + 1, body_y + 1, left_w + portrait_w - 1, body_y + body_h - 1)
            self.rain.draw(c, dim_rect)

        if booting:
            self.boot.draw(c, s, 0, 0, c.w, c.h, elapsed)
            return c

        t = elapsed - boot_t
        self.update_glitch(time.monotonic())

        if compact:
            self.draw_compact(c, s, t)
            return c

        self.header.draw(c, s, 0, 0, self.width, header_h, t)

        if self.netmap_open:
            self.netmap.draw(c, s, 0, body_y, self.width, body_h, t)
        elif self.view in self.views:
            self.views[self.view].draw(c, s, 0, body_y, self.width, body_h, t)
        elif show_portrait or left_w < 150:
            system_h = 15 if body_h >= 38 else max(10, body_h // 2 - 2)
            self.system.draw(c, s, 0, body_y, left_w, system_h, t)
            self.services.draw(c, s, 0, body_y + system_h, left_w, body_h - system_h, t)
        else:
            sys_w = left_w * 2 // 5
            self.system.draw(c, s, 0, body_y, sys_w, body_h, t)
            self.services.draw(c, s, sys_w, body_y, left_w - sys_w, body_h, t)
        if show_portrait and not self.netmap_open and self.view is None:
            if self.usage_page_active(s, t):
                self.usage.draw(c, s, left_w, body_y, portrait_w, body_h, t)
            else:
                self.portrait_panel.draw(c, s, left_w, body_y, portrait_w, body_h, t)

        self.draw_bottom(c, s, self.height - bottom_h, bottom_h, left_w, show_portrait, t)
        self.keybar.draw(c, s, 0, 0, c.w, c.h, t)
        self.overlays.draw(c, s, 0, 0, c.w, c.h, t)

        # Wipe transition right after the boot sequence.
        if self.boot_enabled and t < 1.0:
            wipe = int(self.width * (t / 1.0))
            for yy in range(self.height):
                rc, rs = c.chars[yy], c.styles[yy]
                if wipe < self.width:
                    rc[wipe:] = [" "] * (self.width - wipe)
                    rs[wipe:] = [NONE] * (self.width - wipe)
                for k, (ch, st) in enumerate((("█", G6), ("▒", G5), ("░", G3))):
                    xx = wipe - k
                    if 0 <= xx < self.width:
                        rc[xx], rs[xx] = (random.choice(MATRIX_CHARS), G6) if k == 0 and random.random() < 0.3 else (ch, st)
        return c

    WEB_RETRY = 30.0

    def start_web(self, quiet: bool = False):
        """Start the web mirror; when the port is taken (another instance), run() tries again later."""
        web_cfg = self.config.get("web") or {}
        if not web_cfg.get("enabled"):
            return
        self.web_tried = time.monotonic()
        try:
            # The mirror keeps a reference to the palette, so a theme change reaches the page.
            self.web = WebMirror(web_cfg, lambda: Screen(SGR_LINUX), LINUX_PALETTE, self.collector.hostname)
            self.web.start()
            self.collector.emit("SYSTEM", f"web mirror on port {self.web.port}", G4)
        except OSError as exc:
            self.web = None
            if not quiet:
                self.collector.emit("SYSTEM", f"web mirror: porta ocupada ({exc.strerror or exc}), tento de novo a cada 30 s"[:80],
                                    AMBER)

    def retry_web(self, now: float):
        if self.web is None and (self.config.get("web") or {}).get("enabled") and \
                now - getattr(self, "web_tried", 0.0) > self.WEB_RETRY:
            self.start_web(quiet=True)

    def run(self, once: bool = False, at: float | None = None):
        self.collector.prime()
        self.boot.build_lines(self.collector.snap)
        self.collector.emit("SYSTEM", f"matrix dashboard v{VERSION} online", G5)
        self.collector.emit("SYSTEM", f"watching {len(self.collector.snap.containers)} containers, "
                                      f"{len(self.collector.snap.units)} host units", G4)

        if once:
            self.instant = True
            self.collector._slow_once()
            self.collector.refresh_containers()
            self.collector.collect_fast(1)
            elapsed = at if at is not None else self.boot.duration() + 12.0
            for _ in range(3):
                self.rain.update()
            print(self.screen.plain(self.render_canvas(elapsed)))
            return

        self.collector.start()
        self.start_web()
        self.terminal.setup()
        try:
            signal.signal(signal.SIGINT, lambda *_: setattr(self, "stop", True))
            signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stop", True))
        except Exception:
            pass

        frame_time = 1.0 / self.fps
        self.start = time.monotonic()
        try:
            while not self.stop:
                started = time.monotonic()
                self.read_key()
                self.retry_web(started)
                if started - self.last_full_redraw > 120:
                    self.screen.invalidate()
                    self.last_full_redraw = started
                self.update_auto_blank()
                if self.blanked:
                    blank = Canvas(self.width, self.height)
                    self.terminal.write(self.screen.frame(blank))
                    # The monitor is dark, but remote viewers still get the dashboard.
                    if self.web and self.web.clients:
                        self.web.publish(self.render_canvas(started - self.start))
                    time.sleep(0.2)
                    continue
                canvas = self.render_canvas(started - self.start)
                self.terminal.write(self.screen.frame(canvas))
                if self.web and self.web.clients:
                    self.web.publish(canvas)
                spent = time.monotonic() - started
                budget = 0.25 if self.eco else frame_time
                if spent < budget:
                    time.sleep(budget - spent)
        finally:
            self.collector.stop.set()
            self.terminal.restore()
