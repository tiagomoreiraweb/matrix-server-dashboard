"""Data passed from the collector to the renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Container:
    name: str
    state: str
    health: str
    age: str
    exit_code: str
    image: str
    ports: str
    cpu: float | None = None
    mem: str = ""
    # runtime that owns it ("docker", "k3s"...)
    runtime: str = ""
    # short name for narrow columns when `name` carries a prefix (k3s: name "ns/workload", display "workload")
    display: str = ""

    @property
    def short(self) -> str:
        return self.display or self.name


@dataclass
class ClaudeInfo:
    running: bool = False
    version: str = ""
    sessions: int = 0
    remote: str = ""
    procs: int = 0
    cpu: float = 0.0
    rss: int = 0
    since: float = 0.0
    working: bool = False


@dataclass
class Event:
    wall: float
    mono: float
    tag: str
    text: str
    style: int


@dataclass
class Snapshot:
    hostname: str = "-"
    kernel: str = "-"
    cores: int = 1
    cpu: float = 0.0
    per_core: list[float] = field(default_factory=list)
    ram: float = 0.0
    ram_used: int = 0
    ram_total: int = 0
    swap: float = 0.0
    swap_used: int = 0
    swap_total: int = 0
    load: tuple[float, float, float] = (0.0, 0.0, 0.0)
    uptime_s: int = 0
    temperature: float | None = None
    ip: str = "-"
    iface: str = "-"
    procs: int = 0
    disks: list[tuple[str, float, int, int]] = field(default_factory=list)
    down: float = 0.0
    up: float = 0.0
    latency: float | None = None
    internet: bool = False
    net4: bool = False
    net6: bool | None = None
    lat4: float | None = None
    lat6: float | None = None
    docker_ok: bool = False
    # (name, label, reachable) of every configured container runtime
    runtimes: list[tuple[str, str, bool]] = field(default_factory=list)
    containers: list[Container] = field(default_factory=list)
    flagged: set[str] = field(default_factory=set)
    units: list[tuple[str, str, str]] = field(default_factory=list)
    probes: dict[str, tuple[bool, int, float | None, str]] = field(default_factory=dict)
    claude: ClaudeInfo = field(default_factory=ClaudeInfo)
    backup: dict[str, Any] | None = None
    tailscale: dict[str, Any] | None = None
    icloud: dict[str, Any] | None = None
    argocd: dict[str, Any] | None = None
    wireguard: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    netmap: dict[str, Any] | None = None
    nettraffic: dict[str, Any] | None = None
    cpu_hist: list[float] = field(default_factory=list)
    down_hist: list[float] = field(default_factory=list)
    up_hist: list[float] = field(default_factory=list)
    lat_hist: list[float] = field(default_factory=list)
    claude_hist: list[float] = field(default_factory=list)
