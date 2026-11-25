"""Settings screen (hotkey C)."""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import threading
from typing import TYPE_CHECKING, Any, Callable

from . import autodetect, theme, validators
from .config import DEFAULT_CONFIG, save_user_config
from .render.canvas import Canvas
from .render.rain import MatrixRain
from .sysinfo import get_local_ip, iface_for_ip, read_ipv4
from .theme import AMBER, CYAN, G1, G2, G3, G4, G5, G6, RED, SPINNER, TEXT, WHITE

if TYPE_CHECKING:
    from .dashboard import Dashboard

NETCFG_HELPER = "/usr/local/sbin/matrix-netcfg"


class MenuBuilder:
    """Collects the rows of the settings screen; integrations add their sections through it."""

    def __init__(self, menu: SettingsMenu):
        self.menu = menu
        self.items: list[dict[str, Any]] = []
        # (label, value) lines that integrations add to the SISTEMA section at the end
        self.system: list[tuple[str, str]] = []

    def header(self, label: str, info: str = ""):
        self.items.append({"kind": "header", "label": label, "info": info})

    def field(self, key: str, label: str, hint: str, validate: validators.Validator | None,
              save: Callable[[], None] | None = None, kind: str = "text", options: list[str] | None = None,
              secret: bool = False, max_len: int = 40):
        """secret: shown as ******abcd, typed blind; Enter on an empty edit keeps it, "-" clears it."""
        self.items.append({"kind": kind, "key": key, "label": label, "hint": hint, "validate": validate,
                           "save": save, "options": options, "secret": secret, "max_len": max_len})

    def action(self, label: str, hint: str, fn: Callable[[], None], style: int = G5):
        self.items.append({"kind": "action", "label": label, "hint": hint, "action": fn, "style": style})

    def info(self, label: str, value: str):
        self.items.append({"kind": "info", "label": label, "value": value})

    def system_info(self, label: str, value: str):
        self.system.append((label, value))


class SettingsMenu:
    """Keyboard-driven settings screen (hotkey C): network, integrations, panel, containers."""

    def __init__(self, dash: Dashboard):
        self.d = dash
        self.active = False
        self.items: list[dict[str, Any]] = []
        self.values: dict[str, str] = {}
        self.sysinfo: dict[str, str] = {}
        self.cursor = 0
        self.scroll = 0
        self.edit_buffer: str | None = None
        self.message: tuple[str, int] | None = None
        self.net_dirty = False
        self.busy = ""

    # --- data

    def iface(self) -> str:
        iface = str(self.d.config.get("network_interface") or self.d.collector.snap.iface or "-")
        return iface if iface not in ("-", "auto") else autodetect.default_iface()

    def load(self):
        net = read_ipv4(self.iface())
        self.sysinfo = net
        v = self.values
        v["net_mode"] = net["mode"]
        v["net_ip"] = net["ip"]
        v["net_prefix"] = net["prefix"] or "24"
        v["net_gateway"] = net["gateway"]
        v["net_dns"] = net["dns"] or net["gateway"]
        self.net_dirty = False

        cfg = self.d.config
        v["operator"] = self.d.operator
        v["fps"] = str(self.d.fps)
        v["density"] = f"{float(cfg.get('matrix_density', 0.45)):.2f}"
        v["theme"] = self.d.theme
        screen = cfg.get("screen_off") or {}
        v["screen_off"] = "LIGADO" if screen.get("enabled") else "DESLIGADO"
        v["screen_from"] = str(screen.get("from", "00:00"))
        v["screen_to"] = str(screen.get("to", "07:00"))
        th = cfg.get("thresholds", {})
        for key in ("cpu", "ram", "disk", "temperature"):
            v[f"th_{key}"] = str(th.get(key, DEFAULT_CONFIG["thresholds"][key]))
        for integ in self.d.integrations:
            integ.menu_load(v)
        self.d.collector.notifier.menu_load(v)

    def build(self):
        m = MenuBuilder(self)
        net_now = self.sysinfo
        m.header("REDE", f"atual: {net_now['ip']}/{net_now['prefix']} via {net_now['gateway'] or '-'} ({net_now['mode']})")
        if not os.path.exists(NETCFG_HELPER):
            m.header("  só leitura", "para editar a rede daqui: sudo ./install_hotkeys_sudo.sh (Ubuntu/netplan)")
        else:
            m.field("net_mode", "Modo IPv4", "FIXO = IP definido aqui · DHCP = o roteador escolhe", None,
                    self.mark_net, "choice", ["FIXO", "DHCP"])
            if self.values.get("net_mode") == "FIXO":
                m.field("net_ip", "Endereço IP", "ex.: 192.168.1.100", validators.ipv4, self.mark_net)
                m.field("net_prefix", "Prefixo (máscara)", "24 = 255.255.255.0", validators.prefix, self.mark_net)
                m.field("net_gateway", "Gateway (roteador)", "ex.: 192.168.1.1", validators.ipv4, self.mark_net)
                m.field("net_dns", "DNS", "separe com vírgula · ex.: 192.168.1.1, 1.1.1.1", validators.dns, self.mark_net)
            m.action("Aplicar configuração de rede", "pede confirmação · se o roteador não responder, volta sozinho",
                     self.apply_network, AMBER)

        for integ in self.d.integrations:
            integ.menu(m)
        self.d.collector.notifier.menu(m)

        m.header("PAINEL")
        save = self.save_panel
        m.field("operator", "Nome do operador", "aparece no retrato e no boot", validators.name, save)
        m.field("theme", "Tema de cores", "◂ ▸ troca na hora · " + " · ".join(theme.THEME_LABELS.values()),
                None, save, "choice", list(theme.THEMES))
        m.field("fps", "Quadros por segundo", "2 a 30 · menos = menos CPU", validators.int_range(2, 30), save)
        m.field("density", "Densidade da chuva", "0.05 a 1.00", validators.float_range(0.05, 1.0), save)
        m.field("screen_off", "Apagar tela automático", "apaga o monitor no horário abaixo · tecla acende por 5 min",
                None, save, "choice", ["DESLIGADO", "LIGADO"])
        m.field("screen_from", "  apagar às", "HH:MM", validators.clock, save)
        m.field("screen_to", "  acender às", "HH:MM", validators.clock, save)
        m.field("th_cpu", "Alerta de CPU (%)", "10 a 100", validators.int_range(10, 100), save)
        m.field("th_ram", "Alerta de RAM (%)", "10 a 100", validators.int_range(10, 100), save)
        m.field("th_disk", "Alerta de disco (%)", "10 a 100", validators.int_range(10, 100), save)
        m.field("th_temperature", "Alerta de temperatura (°C)", "40 a 110", validators.int_range(40, 110), save)

        snap = self.d.collector.snap
        m.header("CONTAINERS", "◂ ▸ escolhe a ação · OK executa")
        policies = self.restart_policies()
        for ct in sorted(snap.containers, key=lambda x: x.name):
            actions = self.container_actions(ct)
            if not actions:
                continue
            m.items.append({"kind": "container", "label": ct.name, "state": ct.state, "actions": actions,
                            "choice": 0, "policy": policies.get(ct.name, ""),
                            "hint": (f"◂ ▸ escolhe: {' / '.join(actions)} · OK executa" if len(actions) > 1
                                     else f"OK para {actions[0]} {ct.name}")})

        m.header("SISTEMA")
        ts = snap.tailscale or {}
        m.info("Hostname", snap.hostname)
        m.info("Interface", f"{self.iface()} · MAC {net_now.get('mac', '')}")
        m.info("IPv4", f"{net_now['ip']}/{net_now['prefix']} via {net_now['gateway'] or '-'}")
        m.info("IPv6", net_now.get("ipv6", "") or "-")
        m.info("DNS em uso", net_now.get("dns", "") or "-")
        m.info("Tailscale", f"{ts.get('ip', '-')} · {ts.get('state', '-')}"
                            + (f" · chave expira em {ts['expiry_days']}d" if ts.get("expiry_days") is not None else ""))
        for label, value in m.system:
            m.info(label, value)
        m.info("Kernel", snap.kernel)
        self.items = m.items

    # --- savers

    def mark_net(self):
        self.net_dirty = True
        self.message = ("rede alterada · use 'Aplicar configuração de rede' para valer", AMBER)

    def save_panel(self):
        v = self.values
        d = self.d
        cfg = d.config
        d.operator = v["operator"].strip().upper()
        cfg["operator"] = d.operator
        d.fps = int(v["fps"])
        cfg["fps"] = d.fps
        if v["theme"] != d.theme:
            cfg["theme"] = d.set_theme(v["theme"])
        density = float(v["density"])
        if abs(density - float(cfg.get("matrix_density", 0.45))) > 1e-6:
            cfg["matrix_density"] = round(density, 2)
            d.rain = MatrixRain(d.width, d.height, density)
        cfg["screen_off"] = {"enabled": v["screen_off"] == "LIGADO", "from": v["screen_from"], "to": v["screen_to"]}
        for key in ("cpu", "ram", "disk", "temperature"):
            cfg["thresholds"][key] = int(v[f"th_{key}"])

        def copy_panel_keys(raw: dict[str, Any]):
            for key in ("operator", "fps", "theme", "matrix_density", "screen_off", "thresholds"):
                if key in cfg:
                    raw[key] = cfg[key]
        try:
            save_user_config(d.config_path, copy_panel_keys)
            self.message = ("painel salvo", G5)
        except (OSError, ValueError) as exc:
            self.message = (f"erro ao salvar: {exc}"[:70], RED)

    # --- actions

    def run_bg(self, label: str, fn):
        if self.busy:
            self.message = (f"aguarde: {self.busy}", AMBER)
            return
        self.busy = label
        self.message = (f"{label}...", CYAN)

        def worker():
            try:
                fn()
            finally:
                self.busy = ""
        threading.Thread(target=worker, daemon=True).start()

    def apply_network(self):
        v = self.values
        if v["net_mode"] == "DHCP":
            args = ["dhcp"]
            lines = ["Modo: IP automático (DHCP)", "O IP do servidor passa a ser escolhido pelo roteador."]
        else:
            for key, check in (("net_ip", validators.ipv4), ("net_prefix", validators.prefix),
                               ("net_gateway", validators.ipv4), ("net_dns", validators.dns)):
                err = check(v[key])
                if err:
                    self.message = (f"{err} ({key.replace('net_', '')})", RED)
                    return
            iface = ipaddress.IPv4Interface(f"{v['net_ip']}/{v['net_prefix']}")
            if ipaddress.IPv4Address(v["net_gateway"]) not in iface.network:
                self.message = (f"gateway fora da rede {iface.network}", RED)
                return
            dns = ",".join(x.strip() for x in v["net_dns"].split(",") if x.strip())
            args = ["static", str(iface), v["net_gateway"], dns]
            lines = [f"IP fixo: {iface}", f"Gateway: {v['net_gateway']}   DNS: {dns}"]
        lines += ["A rede pisca por alguns segundos (Tailscale reconecta).",
                  "Se o roteador não responder em 30 s, volta a config anterior."]
        self.d.confirm("APLICAR REDE", lines, lambda: self.run_bg("aplicando rede", lambda: self._apply_network(args)), 15)

    def _apply_network(self, args: list[str]):
        try:
            result = subprocess.run(["sudo", "-n", NETCFG_HELPER, *args],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        except Exception as exc:
            self.message = (f"falhou: {exc}"[:70], RED)
            return
        if "password is required" in result.stderr or "not allowed" in result.stderr or result.returncode == 1 and not result.stdout:
            self.message = ("sem permissão: rode  sudo ~/matrix-server-dashboard/install_hotkeys_sudo.sh", RED)
            self.d.collector.emit("ERROR", "rede: falta instalar o ajudante (install_hotkeys_sudo.sh)", RED)
            return
        try:
            data = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            data = {"ok": False, "message": (result.stderr or "resposta inválida").strip()[:70]}
        ok = bool(data.get("ok"))
        self.message = (str(data.get("message", "")), G5 if ok else RED)
        self.d.collector.emit("NET", f"config de rede: {data.get('message', '')}"[:80], G5 if ok else RED)
        self.d.notify(str(data.get("message", "")), G5 if ok else RED, 6)
        if ok:
            self.d.collector.ip = get_local_ip()
            self.d.collector.iface = iface_for_ip(self.d.collector.ip)
        self.load()
        self.build()

    def container_actions(self, ct) -> list[str]:
        """Menu verbs the container's runtime allows (k3s only restarts; Docker also stops and starts)."""
        rt = self.d.collector.runtime_for(ct.name)
        allowed = {v for v in ("start", "stop", "restart") if rt and rt.supports(ct.name, v)}
        if ct.state == "exited" and "start" not in allowed:
            return []
        wanted = ["reiniciar", "desligar"] if ct.state == "running" else ["ligar"]
        actions = [v for v in wanted if self.CONTAINER_VERBS[v][0] in allowed]
        return actions or (["reiniciar"] if "restart" in allowed else [])

    def restart_policies(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for rt in self.d.collector.runtimes:
            result.update(rt.restart_policies())
        return result

    CONTAINER_VERBS = {
        "reiniciar": ("restart", "reiniciado"),
        "desligar": ("stop", "desligado"),
        "ligar": ("start", "ligado"),
    }

    def container_action(self, name: str, verb: str, policy: str):
        cmd, done = self.CONTAINER_VERBS[verb]

        def run():
            rt = self.d.collector.runtime_for(name)
            ok = bool(rt and rt.action(name, cmd, timeout=90))
            self.message = (f"{name} {done}" if ok else f"falha ao {verb} {name}", G5 if ok else RED)
            self.d.collector.emit(rt.label if rt else "DOCKER",
                                  f"{name} {done} pelo menu" if ok else f"falha ao {verb} {name}", G5 if ok else RED)
            # Refresh the list right away so the row shows the new state and actions.
            self.d.collector.refresh_containers()
            self.d.collector.snap.containers = self.d.collector.containers
            current = name
            self.build()
            self.cursor = next((i for i, it in enumerate(self.items)
                                if it["kind"] == "container" and it["label"] == current), self.cursor)

        if verb == "desligar":
            lines = [f"Container: {name}", "Os serviços dele ficam fora do ar até você ligar de novo."]
            if policy == "always":
                lines.append("Atenção: ele volta a ligar sozinho se o servidor reiniciar.")
            else:
                lines.append("Ele continua desligado mesmo se o servidor reiniciar.")
            if name in ("cloudflared", "traefik"):
                lines.append("CUIDADO: este container dá acesso externo a outros serviços.")
        elif verb == "ligar":
            lines = [f"Container: {name}", "O container será iniciado com a configuração atual."]
        else:
            lines = [f"Container: {name}", "Os serviços dele ficam fora do ar por alguns segundos."]
        self.d.confirm(f"{verb.upper()} CONTAINER", lines, lambda: self.run_bg(f"{verb} {name}", run))

    # --- navigation

    def open(self):
        self.load()
        self.build()
        self.active = True
        self.edit_buffer = None
        self.scroll = 0
        self.cursor = self.next_selectable(-1, 1)
        self.message = None

    def close(self):
        self.active = False
        self.edit_buffer = None
        if self.net_dirty:
            self.d.notify("alterações de rede não aplicadas foram descartadas", AMBER, 4)
        else:
            self.d.notify("configurações fechadas", G4, 2)

    @staticmethod
    def selectable(item: dict[str, Any]) -> bool:
        return item["kind"] not in ("header", "info")

    def next_selectable(self, start: int, step: int) -> int:
        i = start + step
        while 0 <= i < len(self.items):
            if self.selectable(self.items[i]):
                return i
            i += step
        return start if 0 <= start < len(self.items) else 0

    def handle(self, key: str):
        if not self.items:
            return
        item = self.items[self.cursor]
        if self.edit_buffer is not None:
            if key == "esc":
                self.edit_buffer = None
                self.message = ("edição cancelada", G4)
            elif key == "enter":
                value = self.edit_buffer.strip()
                if item.get("secret") and not value:
                    self.edit_buffer = None
                    self.message = ("mantido o valor anterior", G4)
                    return
                if value == "-":
                    value = ""  # clears the field (channel off)
                err = item["validate"](value) if item.get("validate") and value else None
                if err:
                    self.message = (err, RED)
                    return
                self.values[item["key"]] = value
                self.edit_buffer = None
                if item.get("save"):
                    item["save"]()
            elif key == "backspace":
                self.edit_buffer = self.edit_buffer[:-1]
            elif len(key) == 1 and key.isprintable() and len(self.edit_buffer) < item.get("max_len", 40):
                self.edit_buffer += key
            return

        if key in ("esc", "c", "C", "q", "Q"):
            self.close()
        elif key == "up":
            self.cursor = self.next_selectable(self.cursor, -1)
        elif key == "down":
            self.cursor = self.next_selectable(self.cursor, 1)
        elif key in ("enter", "left", "right", " "):
            kind = item["kind"]
            if kind == "container":
                if key in ("left", "right"):
                    step = -1 if key == "left" else 1
                    item["choice"] = (item["choice"] + step) % len(item["actions"])
                elif key == "enter":
                    self.container_action(item["label"], item["actions"][item["choice"]], item.get("policy", ""))
            elif kind == "choice":
                opts = item["options"]
                idx = opts.index(self.values[item["key"]]) if self.values[item["key"]] in opts else 0
                idx = (idx + (-1 if key == "left" else 1)) % len(opts)
                self.values[item["key"]] = opts[idx]
                if item.get("save"):
                    item["save"]()
                if item["key"] == "net_mode":
                    current = self.items[self.cursor]["label"]
                    self.build()
                    self.cursor = next((i for i, it in enumerate(self.items) if it.get("label") == current), self.cursor)
            elif key == "enter" and kind == "text":
                # Secrets start empty: the old value never shows up (the screen also goes to the web page).
                self.edit_buffer = "" if item.get("secret") else self.values.get(item["key"], "")
                self.message = ("digite e confirme com OK · ESC cancela", CYAN)
            elif key == "enter" and kind == "action":
                item["action"]()

    # --- drawing

    def draw(self, c: Canvas, t: float):
        bw = min(104, c.w - 6)
        bh = min(c.h - 4, 46)
        bx, by = (c.w - bw) // 2, (c.h - bh) // 2
        c.box(bx, by, bw, bh, "▸ CONFIGURAÇÕES", "↑↓ navegar · OK editar · ESC fechar", G4, G6)
        c.pulse(bx, by, bw, bh, t * 30, 10)
        ix, iw = bx + 3, bw - 6
        value_x = ix + 32
        list_top, list_h = by + 2, bh - 6
        if self.cursor < self.scroll:
            self.scroll = max(0, self.cursor - 1)
        if self.cursor >= self.scroll + list_h:
            self.scroll = self.cursor - list_h + 1
        blink = int(t * 2.5) % 2 == 0
        for row, idx in enumerate(range(self.scroll, min(len(self.items), self.scroll + list_h))):
            it = self.items[idx]
            yy = list_top + row
            sel = idx == self.cursor
            kind = it["kind"]
            if kind == "header":
                c.put(ix, yy, "━━ " + it["label"] + " ", G5)
                info = it.get("info", "")
                fill_x = ix + len(it["label"]) + 4
                c.put(fill_x, yy, "─" * max(0, iw - len(it["label"]) - 4), G1)
                if info:
                    c.put(ix + iw - len(info), yy, f" {info}", G3)
                continue
            if sel:
                c.put(ix, yy, "▶", G6)
            label_style = WHITE if sel else TEXT
            if kind == "info":
                c.put(ix + 2, yy, it["label"], G3)
                c.put(value_x, yy, str(it["value"])[: iw - 32], TEXT)
            elif kind == "action":
                c.put(ix + 2, yy, f"▸ {it['label']}", it.get("style", G5) if not sel else G6)
                if self.net_dirty and "rede" in it["label"]:
                    c.put(value_x + 10, yy, "● alterações pendentes", AMBER if blink else G3)
            elif kind == "container":
                running = it["state"] == "running"
                c.put(ix + 2, yy, "●", G5 if running else AMBER)
                # k3s names ("namespace/workload") can be long: keep the state column clear
                label = it["label"] if len(it["label"]) <= 27 else it["label"][:26] + "~"
                c.put(ix + 4, yy, label, label_style)
                c.put(value_x, yy, "RUNNING" if running else "DESLIGADO", G5 if running else AMBER)
                if it.get("policy") == "always" and sel:
                    c.put(value_x + 11, yy, "always", G2)
                if sel:
                    verb = it["actions"][it["choice"]]
                    style = RED if verb == "desligar" else CYAN
                    arrows = len(it["actions"]) > 1
                    c.put(value_x + 19, yy, f"◂ {verb.upper()} ▸" if arrows else f"[ OK = {verb.upper()} ]", style)
            else:
                c.put(ix + 2, yy, it["label"], label_style)
                if sel and self.edit_buffer is not None:
                    shown = "*" * len(self.edit_buffer) if it.get("secret") else self.edit_buffer
                    shown = shown[-max(1, iw - 34):]  # long URLs: keep the end, where the typing is
                    c.put(value_x, yy, shown, CYAN)
                    if blink:
                        c.put(value_x + len(shown), yy, "█", CYAN)
                else:
                    value = self.values.get(it["key"], "")
                    if it.get("secret") and value:
                        value = "******" + value[-4:]
                    if kind == "choice":
                        value = f"◂ {value} ▸" if sel else value
                    pending = it["key"].startswith("net_") and self.net_dirty
                    c.put(value_x, yy, value[: iw - 32], AMBER if pending else G5)
        if self.scroll > 0:
            c.put(bx + bw - 3, list_top, "▲", G4)
        if self.scroll + list_h < len(self.items):
            c.put(bx + bw - 3, list_top + list_h - 1, "▼", G4)

        c.put(ix, by + bh - 3, "─" * iw, G1)
        hint = self.items[self.cursor].get("hint", "") if self.items else ""
        if self.busy:
            right, right_style = f"{SPINNER[int(t * 10) % 4]} {self.busy}", CYAN
        elif self.message:
            right, right_style = self.message
        else:
            right, right_style = "", G3
        right = right[:iw]
        c.put(ix, by + bh - 2, hint[: max(0, iw - len(right) - 3)], G3)
        if right:
            c.put(ix + iw - len(right), by + bh - 2, right, right_style)
