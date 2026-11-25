"""Background data collection."""

from __future__ import annotations

import os
import socket
import threading
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any, TypeVar

import psutil

from . import autodetect, health
from .fmt import fmt_rate, fmt_size
from .integrations import ALL as INTEGRATIONS
from .integrations import Integration
from .models import Container, Event, Snapshot
from .netmap import NetMapper
from .notify.manager import AlertManager
from .runtime import ContainerRuntime, from_config
from .shell import run_cmd
from .storage import write_json
from .sysinfo import (
    get_local_ip,
    get_temperature,
    http_probe,
    iface_for_ip,
    tcp_latency,
)
from .theme import AMBER, CYAN, G3, G4, G5, RED

I = TypeVar("I", bound=Integration)


class Collector:
    """Gathers server data in background threads.

    The fast loop (cpu, memory, network, containers, fast integrations) builds a
    new Snapshot every second; the slow loop (container stats, systemd units,
    HTTP probes, slow integrations) feeds results that the fast loop merges in.
    The renderer only reads `self.snap`, which is replaced atomically.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.snap = Snapshot()
        self.events: deque[Event] = deque(maxlen=200)
        self.stop = threading.Event()
        self.ping_host = str(config.get("ping_host", "1.1.1.1"))
        self.ping_host6 = str(config.get("ping_host6", "2606:4700:4700::1111"))
        # Consecutive failures per family; a link only counts as down after 3.
        self.net_fails = {"v4": 0, "v6": 0}
        self.net_lat: dict[str, float | None] = {"v4": None, "v6": None}
        self.has_v6 = False
        self.prev_net: dict[str, bool] = {}
        self.hidden = {str(x).lower() for x in config.get("hide_containers", [])}
        self.thresholds = config.get("thresholds", {})

        self.cpu_hist: deque[float] = deque(maxlen=300)
        self.down_hist: deque[float] = deque(maxlen=300)
        self.up_hist: deque[float] = deque(maxlen=300)
        self.lat_hist: deque[float] = deque(maxlen=120)

        self.hostname = socket.gethostname()
        self.kernel = os.uname().release
        self.cores = psutil.cpu_count() or 1
        psutil.cpu_percent(percpu=True)
        psutil.cpu_percent()

        self.ip = get_local_ip()
        self.iface = iface_for_ip(self.ip)
        self.last_net = self._net_counters()
        self.last_net_at = time.monotonic()

        self.runtimes: list[ContainerRuntime] = from_config(config)
        self.owner: dict[str, ContainerRuntime] = {}
        self.container_stats: dict[str, tuple[float | None, str]] = {}
        self.containers: list[Container] = []
        self.docker_ok = False
        self.runtime_status: list[tuple[str, str, bool]] = []
        self.flagged: set[str] = set()
        self.units: list[tuple[str, str, str]] = []
        self.probes: dict[str, tuple[bool, int, float | None, str]] = {}
        self.integrations: list[Integration] = [cls(self) for cls in INTEGRATIONS]

        self.prev_containers: dict[str, tuple[str, str]] | None = None
        self.prev_units: dict[str, str] | None = None
        self.prev_probes: dict[str, bool] = {}
        self.alert_state: dict[str, bool] = {}
        self.probe_cycle = 0
        self.last_probe_event = time.monotonic()
        self.notifier = AlertManager(self)
        self.netmap_styles = {"new": AMBER, "gone": G3}
        self.netmapper = NetMapper(config, self.iface, self.runtimes,
                                   lambda tag, text, kind: self.emit(tag, text, self.netmap_styles.get(kind, G4)))

    def integration(self, kind: type[I]) -> I:
        return next(i for i in self.integrations if isinstance(i, kind))

    # --- events

    def emit(self, tag: str, text: str, style: int = G4):
        self.events.append(Event(time.time(), time.monotonic(), tag, text, style))

    # --- collectors

    def _net_counters(self) -> tuple[int, int]:
        try:
            per = psutil.net_io_counters(pernic=True)
            if self.iface in per:
                io = per[self.iface]
            else:
                io = psutil.net_io_counters()
            return io.bytes_recv, io.bytes_sent
        except Exception:
            return 0, 0

    def runtime_for(self, name: str) -> ContainerRuntime | None:
        """Runtime that owns a container (the first one when the container is unknown)."""
        return self.owner.get(name) or (self.runtimes[0] if self.runtimes else None)

    def runtime_label(self, name: str) -> str:
        rt = self.runtime_for(name)
        return rt.label if rt else "CONTAINER"

    def refresh_containers(self):
        """Containers of every runtime, with the stats of the last slow cycle merged in."""
        result: list[Container] = []
        owner: dict[str, ContainerRuntime] = {}
        reachable = False
        status = []
        for rt in self.runtimes:
            found = rt.containers()
            status.append((rt.name, rt.label, found is not None))
            if found is None:
                continue
            reachable = True
            for ct in found:
                if ct.name.lower() in self.hidden:
                    continue
                running = ct.state == "running"
                cpu, mem = self.container_stats.get(ct.name, (None, ""))
                ct.cpu = cpu if running else None
                ct.mem = mem if running else ""
                owner[ct.name] = rt
                result.append(ct)
        self.docker_ok = reachable
        self.runtime_status = status
        self.containers = result
        self.owner.update(owner)

    def refresh_stats(self):
        stats: dict[str, tuple[float | None, str]] = {}
        reachable = False
        for rt in self.runtimes:
            found = rt.stats()
            if found is not None:
                reachable = True
                stats.update(found)
        if reachable:  # keep the last numbers while the runtime does not answer
            self.container_stats = stats

    def refresh_units(self):
        units_cfg = self.config.get("systemd_units", [])
        if not units_cfg:
            return
        names = [str(u.get("unit", "")) for u in units_cfg]
        _, out = run_cmd(["systemctl", "is-active", *names], timeout=3.0)
        states = out.splitlines()
        self.units = [
            (str(u.get("name", u.get("unit", "?"))), str(u.get("unit", "")),
             states[i].strip() if i < len(states) else "unknown")
            for i, u in enumerate(units_cfg)
        ]

    def refresh_probes(self):
        probes = {}
        for check in autodetect.live_checks(self.config.get("checks"), self.runtimes):
            name = str(check.get("name", "CHECK"))
            key = str(check.get("container") or name)
            if check.get("url"):
                ok, code, ms = http_probe(str(check["url"]), str(check.get("host_header", "")))
                probes[key] = (ok, code, ms, name)
            elif check.get("tcp_host") and check.get("tcp_port"):
                ms = tcp_latency(str(check["tcp_host"]), int(check["tcp_port"]))
                probes[key] = (ms is not None, 0, ms, name)
        self.probes = probes

    def _slow_once(self):
        self.refresh_stats()
        self.refresh_units()
        for integ in self.integrations:
            integ.collect_slow()
        self.refresh_probes()

    def collect_fast(self, tick: int):
        now = time.monotonic()
        s = Snapshot(hostname=self.hostname, kernel=self.kernel, cores=self.cores)

        s.per_core = psutil.cpu_percent(percpu=True)
        s.cpu = sum(s.per_core) / max(1, len(s.per_core))
        vm = psutil.virtual_memory()
        s.ram, s.ram_used, s.ram_total = vm.percent, vm.total - vm.available, vm.total
        sw = psutil.swap_memory()
        s.swap, s.swap_used, s.swap_total = sw.percent, sw.used, sw.total
        try:
            s.load = os.getloadavg()
        except OSError:
            s.load = (0.0, 0.0, 0.0)
        s.uptime_s = int(time.time() - psutil.boot_time())
        s.procs = len(psutil.pids())
        if tick % 2 == 0 or self.snap.temperature is None:
            s.temperature = get_temperature()
        else:
            s.temperature = self.snap.temperature

        if tick % 15 == 0:
            self.ip = get_local_ip()
            self.iface = iface_for_ip(self.ip)
        s.ip, s.iface = self.ip, self.iface

        for mount in self.config.get("mounts", ["/"]):
            if not os.path.exists(mount):
                continue
            try:
                du = psutil.disk_usage(mount)
                s.disks.append((mount, du.percent, du.used, du.total))
            except Exception:
                pass

        rx, tx = self._net_counters()
        dt = max(0.001, now - self.last_net_at)
        s.down = max(0.0, (rx - self.last_net[0]) / dt)
        s.up = max(0.0, (tx - self.last_net[1]) / dt)
        self.last_net, self.last_net_at = (rx, tx), now

        s.net4 = self.net_fails["v4"] < 3
        s.net6 = (self.net_fails["v6"] < 3) if self.has_v6 else None
        s.lat4, s.lat6 = self.net_lat["v4"], self.net_lat["v6"]
        s.internet = s.net4 or bool(s.net6)
        s.latency = s.lat4 if s.lat4 is not None else s.lat6
        if s.latency is not None:
            self.lat_hist.append(s.latency)

        if tick % 4 == 0:
            self.refresh_containers()
        for integ in self.integrations:
            integ.collect_fast(tick)

        s.docker_ok = self.docker_ok
        s.runtimes = self.runtime_status
        s.containers = self.containers
        s.units = self.units
        s.probes = self.probes
        s.netmap = self.netmapper.result
        s.nettraffic = self.netmapper.traffic
        for integ in self.integrations:
            integ.fill(s)

        self.cpu_hist.append(s.cpu)
        self.down_hist.append(s.down)
        self.up_hist.append(s.up)
        s.cpu_hist = list(self.cpu_hist)
        s.down_hist = list(self.down_hist)
        s.up_hist = list(self.up_hist)
        s.lat_hist = list(self.lat_hist)

        self._detect_events(s)
        s.flagged = set(self.flagged)
        self.snap = s
        try:
            self.notifier.check(s)
        except Exception as exc:
            self.emit("ERROR", f"alertas: {exc}"[:80], RED)

    # --- event detection

    def _alert(self, key: str, active: bool, on_text: str, off_text: str):
        before = self.alert_state.get(key, False)
        if active and not before:
            self.emit("ALERT", on_text, RED)
        elif before and not active:
            self.emit("OK", off_text, G5)
        self.alert_state[key] = active

    def _container_events(self, s: Snapshot):
        current = {c.name: (c.state, c.health) for c in s.containers}
        if self.prev_containers is not None:
            for name, (state, health) in current.items():
                old = self.prev_containers.get(name)
                tag = self.runtime_label(name)
                if old is None:
                    self.emit(tag, f"{name} created ({state})", CYAN)
                elif old[0] != state:
                    style = G5 if state == "running" else RED
                    self.emit(tag, f"{name} {old[0]} -> {state}", style)
                    if state == "running":
                        self.flagged.discard(name)
                    else:
                        self.flagged.add(name)
                elif old[1] != health and health:
                    style = G5 if health == "healthy" else AMBER if health == "starting" else RED
                    self.emit(tag, f"{name} health: {health}", style)
            for name in self.prev_containers:
                if name not in current:
                    self.emit(self.runtime_label(name), f"{name} removed", AMBER)
                    self.flagged.discard(name)
        self.prev_containers = current

    def _detect_events(self, s: Snapshot):
        if s.docker_ok:
            self._container_events(s)

        if s.units:
            current_units = {label: state for label, _, state in s.units}
            if self.prev_units is not None:
                for label, state in current_units.items():
                    old = self.prev_units.get(label)
                    if old and old != state:
                        self.emit("SYSTEMD", f"{label.lower()} {old} -> {state}", G5 if state == "active" else RED)
            self.prev_units = current_units

        for key, (ok, code, _, name) in s.probes.items():
            old = self.prev_probes.get(key)
            if old is not None and old != ok:
                if ok:
                    self.emit("HTTP", f"{name.lower()} endpoint back ({code})", G5)
                else:
                    self.emit("HTTP", f"{name.lower()} endpoint not responding", RED)
            self.prev_probes[key] = ok

        for integ in self.integrations:
            integ.detect_events(s)

        for fam, up in (("IPv4", s.net4), ("IPv6", s.net6)):
            if up is None:
                continue
            old = self.prev_net.get(fam)
            if old is not None and old != up:
                if up:
                    self.emit("NET", f"internet {fam} restored", G5)
                else:
                    self.emit("NET", f"internet {fam} lost", RED)
            self.prev_net[fam] = up

        for breach in health.thresholds(s, self.thresholds):
            self._alert(breach.key, breach.active, breach.event_on, breach.event_off)

        now = time.monotonic()
        if now - self.last_probe_event >= 9:
            self.last_probe_event = now
            self._probe_line(s)

    @staticmethod
    def _runtime_lines(s: Snapshot, running: int) -> list[str]:
        if len(s.runtimes) < 2:
            return [f"docker {running}/{len(s.containers)} containers running"]
        lines = []
        for name, _, _ in s.runtimes:
            mine = [c for c in s.containers if c.runtime == name]
            lines.append(f"{name} {sum(1 for c in mine if c.state == 'running')}/{len(mine)} running")
        return lines

    def _probe_line(self, s: Snapshot):
        running = sum(1 for c in s.containers if c.state == "running")
        lines = [
            f"cpu {s.cpu:.1f}%  load {s.load[0]:.2f}  procs {s.procs}"
            + (f"  temp {s.temperature:.0f}°C" if s.temperature is not None else ""),
            f"net down {fmt_rate(s.down)}  up {fmt_rate(s.up)}  "
            + "  ".join(f"{fam} " + (f"{lat:.0f} ms" if up and lat is not None else "down")
                        for fam, up, lat in (("v4", s.net4, s.lat4), ("v6", s.net6, s.lat6)) if up is not None),
            *self._runtime_lines(s, running),
            f"memory {fmt_size(s.ram_used)} / {fmt_size(s.ram_total)}  swap {s.swap:.0f}%",
        ]
        for mount, pct, used, total in s.disks:
            lines.append(f"disk {mount} {pct:.0f}% used  {fmt_size(total - used)} free")
        for integ in self.integrations:
            lines += integ.probe_lines(s)
        text = lines[self.probe_cycle % len(lines)]
        self.probe_cycle += 1
        self.emit("PROBE", text, G3)

    # --- threads

    def _loop(self, name: str, step, interval: float, quiet: bool = False):
        """Run `step` every `interval` seconds until stop; errors become console events."""
        while not self.stop.is_set():
            try:
                step()
            except Exception as exc:
                if not quiet:
                    self.emit("ERROR", f"{name}: {exc}"[:80], RED)
            self.stop.wait(interval)

    def _fast_loop(self):
        tick = 1
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                self.collect_fast(tick)
            except Exception as exc:
                self.emit("ERROR", f"collector: {exc}"[:80], RED)
            tick += 1
            self.stop.wait(max(0.05, 1.0 - (time.monotonic() - started)))

    def prime(self):
        self.refresh_containers()
        self._net_probe()
        self.refresh_units()
        for integ in self.integrations:
            integ.prime()
        time.sleep(0.15)
        self.collect_fast(0)

    def _net_probe(self):
        self.has_v6 = any(
            a.family == socket.AF_INET6 and not a.address.startswith("fe80")
            for addrs in psutil.net_if_addrs().values() for a in addrs
        )
        for fam, host in (("v4", self.ping_host), ("v6", self.ping_host6)):
            if fam == "v6" and not self.has_v6:
                continue
            # Port 443 is open on networks that block outbound DNS (53).
            ms = tcp_latency(host, 443, timeout=3.0)
            if ms is None:
                self.net_fails[fam] += 1
                if self.net_fails[fam] >= 3:
                    self.net_lat[fam] = None
            else:
                self.net_fails[fam] = 0
                self.net_lat[fam] = ms

    # --- export for the web hub (server-hub reads this file)

    EVENT_LEVEL = {RED: "critical", AMBER: "warning", G5: "good", CYAN: "info"}

    def export_snapshot(self, path: Path):
        s = self.snap
        data = asdict(s)
        data["flagged"] = sorted(s.flagged)
        data["events"] = [
            {"t": e.wall, "tag": e.tag, "text": e.text, "level": self.EVENT_LEVEL.get(e.style, "neutral")}
            for e in list(self.events)[-80:]
        ]
        data["exported_at"] = time.time()
        write_json(path, data, default=str)

    def _export_loop(self):
        path = Path(os.path.expanduser(str(self.config.get("export_path") or "~/.cache/server-hub/snapshot.json")))
        path.parent.mkdir(parents=True, exist_ok=True)
        while not self.stop.is_set():
            try:
                self.export_snapshot(path)
            except Exception as exc:
                self.emit("ERROR", f"export: {exc}"[:80], RED)
                self.stop.wait(10.0)
            self.stop.wait(1.0)

    def start(self):
        netmap_every = max(30.0, float((self.config.get("netmap") or {}).get("interval", 60)))
        loops = [
            self._export_loop,
            lambda: self._loop("net", self._net_probe, 2.0, quiet=True),
            lambda: self._loop("traffic", self.netmapper.sample_traffic, 3.0),
            lambda: self._loop("netmap", self.netmapper.scan, netmap_every),
            self._fast_loop,
            lambda: self._loop("slow collector", self._slow_once, 12.0),
        ]
        for target in loops:
            threading.Thread(target=target, daemon=True).start()
