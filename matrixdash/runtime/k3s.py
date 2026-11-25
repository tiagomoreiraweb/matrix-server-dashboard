"""Kubernetes (k3s) through kubectl: one row per workload (Deployment, StatefulSet, DaemonSet).

The dashboard's access comes from its own ServiceAccount (system/k8s/matrix-dashboard-rbac.yaml):
read pods, workloads and metrics, and patch workloads for `rollout restart`.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from ..fmt import fmt_size
from ..models import Container
from ..shell import run_cmd
from .base import ContainerRuntime

KUBECONFIGS = ("~/.kube/matrix-dashboard.yaml", "~/.kube/config", "/etc/rancher/k3s/k3s.yaml")
# Waiting / terminated reasons that mean the workload is broken, not just starting.
BAD_REASONS = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError",
               "CreateContainerError", "InvalidImageName", "RunContainerError", "OOMKilled", "Error"}
KINDS = {"Deployment": "deployment", "StatefulSet": "statefulset", "DaemonSet": "daemonset"}


def find_kubeconfig(configured: str = "") -> str | None:
    """First readable kubeconfig: the configured one, $KUBECONFIG, the dashboard's own, ~/.kube/config, k3s'."""
    for candidate in (configured, os.environ.get("KUBECONFIG", ""), *KUBECONFIGS):
        if candidate:
            path = Path(os.path.expanduser(candidate))
            if path.is_file() and os.access(path, os.R_OK):
                return str(path)
    return None


def parse_time(value: str) -> float:
    """Epoch of a Kubernetes timestamp (UTC, '2026-11-24T14:03:11Z'); 0 when missing."""
    try:
        return time.mktime(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except (TypeError, ValueError):
        return 0.0


def short_age(seconds: float) -> str:
    """Same units as Docker's column: 45s, 12m, 3h, 5d, 2w, 4mo, 1y."""
    seconds = max(0, int(seconds))
    for unit, size in (("y", 365 * 86400), ("mo", 30 * 86400), ("w", 7 * 86400), ("d", 86400), ("h", 3600),
                       ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def cpu_percent(value: str) -> float:
    """'250m' or '1' (cores) -> percent of one core, like `docker stats`."""
    value = value.strip()
    try:
        if value.endswith("n"):
            return float(value[:-1]) / 1e7
        if value.endswith("u"):
            return float(value[:-1]) / 1e4
        if value.endswith("m"):
            return float(value[:-1]) / 10
        return float(value) * 100
    except ValueError:
        return 0.0


def mem_bytes(value: str) -> float:
    units = {"Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4, "K": 1e3, "M": 1e6, "G": 1e9}
    value = value.strip()
    for suffix, mult in units.items():
        if value.endswith(suffix):
            try:
                return float(value[:-len(suffix)]) * mult
            except ValueError:
                return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def workload_of(pod: dict[str, Any]) -> tuple[str, str]:
    """(kind, name) of the workload that owns a pod; ("Pod", pod name) for bare pods."""
    meta = pod.get("metadata") or {}
    for ref in meta.get("ownerReferences") or []:
        kind, name = ref.get("kind", ""), ref.get("name", "")
        if kind == "ReplicaSet":
            tmpl = (meta.get("labels") or {}).get("pod-template-hash", "")
            if tmpl and name.endswith("-" + tmpl):
                return "Deployment", name[: -len(tmpl) - 1]
            return "ReplicaSet", name
        if kind in ("StatefulSet", "DaemonSet", "Job"):
            return kind, name
    return "Pod", meta.get("name", "")


class Workload:
    def __init__(self, ns: str, kind: str, name: str):
        self.ns, self.kind, self.name = ns, kind, name
        self.desired: int | None = None
        self.pods: list[dict[str, Any]] = []
        self.created = 0.0

    @property
    def key(self) -> str:
        return f"{self.ns}/{self.name}"

    def to_container(self, now: float) -> Container:
        ready = bad = restarting = 0
        reason = ""
        image = ""
        started: list[float] = []
        for pod in self.pods:
            spec = pod.get("spec") or {}
            status = pod.get("status") or {}
            if not image:
                image = ((spec.get("containers") or [{}])[0]).get("image", "")
            statuses = status.get("containerStatuses") or []
            if statuses and all(cs.get("ready") for cs in statuses):
                ready += 1
            for cs in statuses:
                state = cs.get("state") or {}
                why = (state.get("waiting") or {}).get("reason") or (state.get("terminated") or {}).get("reason") or ""
                if why in BAD_REASONS:
                    bad += 1
                    reason = reason or why
                    if why == "CrashLoopBackOff":
                        restarting += 1
                run = (state.get("running") or {}).get("startedAt")
                if run:
                    started.append(parse_time(run))
        desired = self.desired if self.desired is not None else len(self.pods)
        if desired == 0 and not self.pods:
            state, health = "exited", ""
        elif restarting:
            state, health = "restarting", "unhealthy"
        elif ready:
            state = "running"
            health = "unhealthy" if bad else "healthy" if ready >= desired else "starting"
        else:
            state, health = "pending", "unhealthy" if bad else "starting"
        since = max(started) if started else self.created
        return Container(
            name=self.key, state=state, health=health,
            age=short_age(now - since) if since else "-",
            exit_code=reason, image=image,
            ports=f"{self.ns} {ready}/{desired}",
            runtime=K3sRuntime.name, display=self.name,
        )


class K3sRuntime(ContainerRuntime):
    name = "k3s"
    label = "K3S"
    unavailable_hint = "not available (run: sudo ./system/k8s/make-kubeconfig.sh)"
    ACTIONS = ("restart",)
    boot_label = "k3s cluster"
    boot_unit = "workloads"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.kinds: dict[str, str] = {}  # container key -> workload kind, for actions

    @staticmethod
    def installed() -> bool:
        return bool(shutil.which("kubectl")) and find_kubeconfig() is not None

    def kubeconfig(self) -> str | None:
        return find_kubeconfig(str(self.config.get("kubeconfig") or ""))

    def kubectl(self, *args: str, timeout: float = 8.0) -> tuple[int, str]:
        cfg = self.kubeconfig()
        if not cfg:
            return 1, ""
        return run_cmd(["kubectl", "--kubeconfig", cfg, *args], timeout=timeout)

    def get_json(self, *args: str) -> dict[str, Any] | None:
        code, out = self.kubectl("get", *args, "-o", "json")
        if code != 0:
            return None
        try:
            return json.loads(out)
        except ValueError:
            return None

    def workloads(self) -> list[Workload] | None:
        pods = self.get_json("pods", "-A")
        if pods is None:
            return None
        controllers = self.get_json("deployments,statefulsets,daemonsets", "-A") or {"items": []}
        found: dict[tuple[str, str, str], Workload] = {}
        for item in controllers.get("items", []):
            meta = item.get("metadata") or {}
            kind = item.get("kind", "")
            w = found.setdefault((meta.get("namespace", ""), kind, meta.get("name", "")),
                                 Workload(meta.get("namespace", ""), kind, meta.get("name", "")))
            w.created = parse_time(meta.get("creationTimestamp", ""))
            if kind == "DaemonSet":
                w.desired = int((item.get("status") or {}).get("desiredNumberScheduled") or 0)
            else:
                replicas = (item.get("spec") or {}).get("replicas")
                w.desired = 1 if replicas is None else int(replicas)
        for pod in pods.get("items", []):
            if (pod.get("status") or {}).get("phase") in ("Succeeded",):
                continue  # finished job pods
            meta = pod.get("metadata") or {}
            ns = meta.get("namespace", "")
            kind, name = workload_of(pod)
            w = found.setdefault((ns, kind, name), Workload(ns, kind, name))
            w.pods.append(pod)
            if not w.created:
                w.created = parse_time(meta.get("creationTimestamp", ""))
        return sorted(found.values(), key=lambda w: (w.ns, w.name))

    def containers(self) -> list[Container] | None:
        found = self.workloads()
        if found is None:
            return None
        now = time.time()
        # Two workloads with the same name in different namespaces stay apart through the key "ns/name".
        self.kinds = {w.key: w.kind for w in found}
        return [w.to_container(now) for w in found]

    def stats(self) -> dict[str, tuple[float | None, str]] | None:
        code, out = self.kubectl("top", "pods", "-A", "--no-headers")
        if code != 0:
            return None
        pods = self.get_json("pods", "-A") or {"items": []}
        owner = {}
        for pod in pods.get("items", []):
            meta = pod.get("metadata") or {}
            owner[(meta.get("namespace"), meta.get("name"))] = f"{meta.get('namespace')}/{workload_of(pod)[1]}"
        cpu: dict[str, float] = {}
        mem: dict[str, float] = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            key = owner.get((parts[0], parts[1]))
            if not key:
                continue
            cpu[key] = cpu.get(key, 0.0) + cpu_percent(parts[2])
            mem[key] = mem.get(key, 0.0) + mem_bytes(parts[3])
        return {k: (cpu[k], fmt_size(mem[k])) for k in cpu}

    def state(self, name: str) -> tuple[str, str]:
        for ct in self.containers() or []:
            if ct.name == name:
                return ct.state, ""
        return "missing", ""

    def logs(self, name: str, since: str = "", tail: int = 0, timeout: float = 8.0) -> list[str]:
        ns, _, workload = name.partition("/")
        kind = KINDS.get(self.kinds.get(name, "Deployment"), "deployment")
        args = ["logs", "-n", ns, f"{kind}/{workload}"]
        if since:
            args.append(f"--since={since}")
        if tail:
            args.append(f"--tail={tail}")
        code, out = self.kubectl(*args, timeout=timeout)
        return out.splitlines() if code == 0 else []

    def supports(self, name: str, verb: str) -> bool:
        # Bare pods and jobs have no workload to restart; a scaled-to-zero one has nothing to restart.
        return verb == "restart" and self.kinds.get(name) in KINDS

    def action(self, name: str, verb: str, timeout: float = 90.0) -> bool:
        if verb != "restart":
            return False
        ns, _, workload = name.partition("/")
        kind = KINDS.get(self.kinds.get(name, ""))
        if not kind:
            return False  # bare pods and jobs are not restarted from the dashboard
        code, _ = self.kubectl("rollout", "restart", "-n", ns, f"{kind}/{workload}", timeout=timeout)
        return code == 0
