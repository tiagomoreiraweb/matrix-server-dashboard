"""Docker through its command line (the user needs to be in the docker group)."""

from __future__ import annotations

import re
import shutil
import subprocess

from ..fmt import fmt_size, parse_size
from ..models import Container
from ..shell import run_cmd
from .base import ContainerRuntime, Endpoint, Network

AGE_RE = re.compile(r"(\d+|About an?|Less than a|an?)\s+(second|minute|hour|day|week|month|year)", re.I)
AGE_UNITS = {"second": "s", "minute": "m", "hour": "h", "day": "d", "week": "w", "month": "mo", "year": "y"}
PORT_RE = re.compile(r"(0\.0\.0\.0|\[::\]|127\.0\.0\.1):(\d+)->")
PORT_MAP_RE = re.compile(r"(?:(\d+\.\d+\.\d+\.\d+|\[::\]|::):)?(\d+)->(\d+)/tcp")
HEALTH_RE = re.compile(r"\((healthy|unhealthy|health: starting)\)")
EXIT_RE = re.compile(r"Exited \((\d+)\)")


def short_age(status: str) -> str:
    """'Up 3 days (healthy)' -> '3d'."""
    match = AGE_RE.search(status)
    if not match:
        return "-"
    num = match.group(1)
    if num.isdigit():
        n = num
    elif num.lower().startswith("less"):
        n = "<1"
    else:
        n = "1"
    return f"{n}{AGE_UNITS[match.group(2).lower()]}"


def short_ports(ports: str) -> str:
    """'0.0.0.0:8080->80/tcp, [::]:8080->80/tcp' -> ':8080'."""
    seen: list[str] = []
    for host, port in PORT_RE.findall(ports):
        label = f"lo:{port}" if host == "127.0.0.1" else f":{port}"
        if label not in seen and f":{port}" not in seen:
            seen.append(label)
    return ",".join(seen[:2]) if seen else "-"


def parse_container(line: str) -> Container | None:
    """One line of `docker ps --format "{{.Names}}\\t{{.State}}\\t{{.Status}}\\t{{.Image}}\\t{{.Ports}}"`."""
    parts = line.split("\t")
    if len(parts) < 4:
        return None
    name, state, status, image = parts[:4]
    ports = parts[4] if len(parts) > 4 else ""
    health = ""
    hm = HEALTH_RE.search(status)
    if hm:
        health = "starting" if "starting" in hm.group(1) else hm.group(1)
    em = EXIT_RE.search(status)
    return Container(name=name, state=state.lower(), health=health, age=short_age(status),
                     exit_code=em.group(1) if em else "", image=image, ports=short_ports(ports),
                     runtime=DockerRuntime.name)


class DockerRuntime(ContainerRuntime):
    name = "docker"
    label = "DOCKER"
    unavailable_hint = "not available (install Docker or add user to group docker)"
    boot_label = "docker engine"

    @staticmethod
    def installed() -> bool:
        return bool(shutil.which("docker"))

    def containers(self) -> list[Container] | None:
        code, out = run_cmd(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"],
            timeout=4.0,
        )
        if code != 0:
            return None
        return [ct for ct in map(parse_container, out.splitlines()) if ct]

    def stats(self) -> dict[str, tuple[float | None, str]] | None:
        code, out = run_cmd(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"],
            timeout=15.0,
        )
        if code != 0:
            return None
        stats: dict[str, tuple[float | None, str]] = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            try:
                cpu: float | None = float(parts[1].strip().rstrip("%"))
            except ValueError:
                cpu = None
            stats[parts[0]] = (cpu, fmt_size(parse_size(parts[2].split("/")[0])))
        return stats

    def state(self, name: str) -> tuple[str, str]:
        code, out = run_cmd(["docker", "inspect", "-f", "{{.State.Status}} {{.State.StartedAt}}", name], timeout=4.0)
        if code != 0:
            return "missing", ""
        status, started = (out.split() + ["", ""])[:2]
        return status, started

    def logs(self, name: str, since: str = "", tail: int = 0, timeout: float = 8.0) -> list[str]:
        args = ["docker", "logs"]
        if since:
            args += ["--since", since]
        if tail:
            args += ["--tail", str(tail)]
        try:
            proc = subprocess.run([*args, name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, timeout=timeout)
        except Exception:
            return []
        return proc.stdout.splitlines()

    def action(self, name: str, verb: str, timeout: float = 90.0) -> bool:
        if verb not in self.ACTIONS:
            return False
        code, _ = run_cmd(["docker", verb, name], timeout=timeout)
        return code == 0

    def restart_policies(self) -> dict[str, str]:
        code, ids = run_cmd(["docker", "ps", "-aq"], timeout=4.0)
        if code != 0 or not ids:
            return {}
        _, out = run_cmd(["docker", "inspect", "-f", "{{.Name}} {{.HostConfig.RestartPolicy.Name}}", *ids.split()],
                         timeout=6.0)
        result = {}
        for line in out.splitlines():
            parts = line.strip().lstrip("/").split()
            if len(parts) == 2:
                result[parts[0]] = parts[1]
        return result

    def endpoints(self) -> list[Endpoint]:
        code, out = run_cmd(["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Networks}}"],
                            timeout=4.0, strip=False)
        if code != 0:
            return []
        result = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            ports_raw = parts[2] if len(parts) > 2 else ""
            mapping: dict[int, tuple[str, int]] = {}
            for host, hport, cport in PORT_MAP_RE.findall(ports_raw):
                ip = "127.0.0.1" if host in ("", "0.0.0.0", "[::]", "::") else host
                mapping.setdefault(int(cport), (ip, int(hport)))
            result.append(Endpoint(parts[0], parts[1], mapping, (parts[3] if len(parts) > 3 else "") == "host"))
        return result

    def networks(self) -> list[Network]:
        code, ids = run_cmd(["docker", "network", "ls", "-q"], timeout=5.0, strip=False)
        if code != 0 or not ids.split():
            return []
        fmt = "{{.Name}}|{{.Driver}}|{{range .IPAM.Config}}{{.Subnet}} {{end}}|" \
              "{{range $k,$v := .Containers}}{{$v.Name}}={{$v.IPv4Address}},{{end}}"
        code, out = run_cmd(["docker", "network", "inspect", *ids.split(), "--format", fmt], timeout=8, strip=False)
        nets = []
        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) < 4 or parts[1] == "null":
                continue
            members = []
            for item in parts[3].split(","):
                if "=" in item:
                    cname, ip = item.split("=", 1)
                    members.append((cname, ip.split("/")[0] if "." in ip else ""))
            members.sort()
            nets.append(Network(parts[0], parts[1], parts[2].strip(), members))
        return nets

    def pids(self, skip: set[str] | None = None) -> dict[str, int] | None:
        code, out = run_cmd(["docker", "ps", "-q"], timeout=5.0, strip=False)
        if code != 0 or not out.split():
            return None
        _, out = run_cmd(["docker", "inspect", "-f", "{{.Name}} {{.State.Pid}}", *out.split()], timeout=6, strip=False)
        pids = {}
        for line in out.splitlines():
            cname, _, pid = line.strip().lstrip("/").partition(" ")
            if pid.isdigit() and int(pid) > 0 and cname not in (skip or set()):
                pids[cname] = int(pid)
        return pids

    def run_sidecar(self, name: str, image: str, script: str, timeout: float = 30.0) -> bool:
        code, _ = run_cmd(["docker", "run", "--rm", "--network", f"container:{name}", "--cap-add", "NET_ADMIN",
                           image, "sh", "-c", script], timeout=timeout)
        return code == 0
