"""Argo CD: sync and health of every Application, read from the cluster with the k3s access.

Applications are custom resources in the cluster, so no Argo CD API token is needed: the
dashboard's ServiceAccount (system/k8s/matrix-dashboard-rbac.yaml) can list them.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..models import Snapshot
from ..runtime.k3s import K3sRuntime, parse_time
from ..theme import AMBER, CYAN, G4, G5, RED
from .base import Integration

BAD_HEALTH = ("Degraded", "Missing")
FAILED_OPS = ("Failed", "Error")


def parse_app(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("metadata") or {}
    spec = item.get("spec") or {}
    st = item.get("status") or {}
    op = st.get("operationState") or {}
    source = spec.get("source") or (spec.get("sources") or [{}])[0]
    history = st.get("history") or []
    message = ""
    for cond in st.get("conditions") or []:
        message = message or str(cond.get("message") or "")
    if not message and (st.get("health") or {}).get("status") in BAD_HEALTH:
        for res in st.get("resources") or []:
            health = res.get("health") or {}
            if health.get("status") in BAD_HEALTH:
                message = f"{res.get('kind', '')}/{res.get('name', '')}: {health.get('message') or health['status']}"
                break
    if not message and op.get("phase") in FAILED_OPS:
        message = str(op.get("message") or "")
    return {
        "name": str(meta.get("name", "")),
        "project": str(spec.get("project", "")),
        "namespace": str((spec.get("destination") or {}).get("namespace", "")),
        "sync": str((st.get("sync") or {}).get("status") or "Unknown"),
        "health": str((st.get("health") or {}).get("status") or "Unknown"),
        "revision": str((st.get("sync") or {}).get("revision") or "")[:7],
        "target": str(source.get("targetRevision") or "HEAD"),
        "auto": bool((spec.get("syncPolicy") or {}).get("automated")),
        "operation": str(op.get("phase") or ""),
        "synced_at": parse_time(str(op.get("finishedAt") or (history[-1].get("deployedAt") if history else "") or "")),
        "message": " ".join(message.split())[:200],
    }


def problem(app: dict[str, Any]) -> bool:
    return app["health"] != "Healthy" or app["sync"] != "Synced" or app["operation"] in FAILED_OPS


def summary(apps: list[dict[str, Any]]) -> tuple[int, int, int]:
    """(apps, healthy, synced)."""
    return (len(apps), sum(1 for a in apps if a["health"] == "Healthy"), sum(1 for a in apps if a["sync"] == "Synced"))


class ArgoCDIntegration(Integration):
    key = "argocd"
    hotkeys = ("A",)

    def __init__(self, collector):
        super().__init__(collector)
        self.data: dict[str, Any] | None = None
        self.available: bool | None = None  # None = not read yet
        self.prev: dict[str, tuple[str, str, str, str]] = {}

    def k3s(self) -> K3sRuntime | None:
        return next((rt for rt in self.collector.runtimes if isinstance(rt, K3sRuntime)), None)

    def enabled(self) -> bool:
        setting = self.config.get("argocd", "auto")
        if setting is False or self.k3s() is None:
            return False
        return self.available is not False

    # --- collection

    def prime(self):
        self.read()

    def collect_slow(self):
        self.read()

    def read(self):
        rt = self.k3s()
        if rt is None or self.config.get("argocd", "auto") is False:
            return
        code, out = rt.kubectl("get", "applications.argoproj.io", "-A", "-o", "json", timeout=10.0)
        if code != 0:
            # No CRD (Argo CD not installed) or no permission: hide everything after the first try.
            if self.available is None:
                self.available = False
            return
        try:
            items = json.loads(out).get("items", [])
        except ValueError:
            return
        self.available = True
        apps = sorted((parse_app(i) for i in items), key=lambda a: (not problem(a), a["name"]))
        self.explain(apps)
        self.data = {"apps": apps, "at": time.time()}

    def explain(self, apps: list[dict[str, Any]]):
        """Unhealthy app without a message: borrow the pod error of its namespace from the k3s rows.

        Argo CD keeps resource health in the app tree (not in the Application) on recent versions,
        so the Application alone often says "Degraded" without saying why."""
        broken = {}
        for ct in self.collector.containers:
            if ct.runtime == K3sRuntime.name and ct.health == "unhealthy":
                ns = ct.name.partition("/")[0]
                broken.setdefault(ns, f"{ct.short}: {ct.exit_code or ct.state}")
        for a in apps:
            if not a["message"] and a["health"] != "Healthy" and a["namespace"] in broken:
                a["message"] = broken[a["namespace"]]

    def fill(self, s: Snapshot):
        s.argocd = self.data

    def detect_events(self, s: Snapshot):
        apps = (s.argocd or {}).get("apps") or []
        current = {}
        for a in apps:
            state = (a["sync"], a["health"], a["revision"], a["operation"])
            current[a["name"]] = state
            old = self.prev.get(a["name"])
            if not self.prev or old is None:
                continue
            name = a["name"]
            if old[1] != a["health"]:
                style = G5 if a["health"] == "Healthy" else RED if a["health"] in BAD_HEALTH else AMBER
                self.emit("ARGOCD", f"{name} {old[1].lower()} -> {a['health'].lower()}", style)
            if old[0] != a["sync"]:
                self.emit("ARGOCD", f"{name} {a['sync'].lower()}", G5 if a["sync"] == "Synced" else AMBER)
            if old[2] != a["revision"] and a["revision"]:
                self.emit("ARGOCD", f"{name} deployed {a['revision']}", CYAN)
            if old[3] != a["operation"] and a["operation"] in FAILED_OPS:
                self.emit("ARGOCD", f"{name} sync failed: {a['message']}"[:80], RED)
        if apps:
            self.prev = current

    def probe_lines(self, s: Snapshot) -> list[str]:
        apps = (s.argocd or {}).get("apps")
        if not apps:
            return []
        n, healthy, synced = summary(apps)
        return [f"argocd {n} apps  healthy {healthy}/{n}  synced {synced}/{n}"]

    # --- screen

    def ticker(self, s: Snapshot) -> list[str]:
        apps = (s.argocd or {}).get("apps")
        if not apps:
            return []
        n, healthy, synced = summary(apps)
        return [f"ARGOCD {healthy}/{n} HEALTHY · {synced}/{n} SYNCED"]

    def alerts(self, s: Snapshot) -> list[str]:
        out = []
        for a in (s.argocd or {}).get("apps") or []:
            if a["health"] in BAD_HEALTH:
                out.append(f"ARGOCD {a['name'].upper()} {a['health'].upper()}")
            elif a["operation"] in FAILED_OPS:
                out.append(f"ARGOCD {a['name'].upper()} SYNC FALHOU")
        return out

    def boot_lines(self, s: Snapshot) -> list[tuple[str, str]]:
        apps = (s.argocd or {}).get("apps")
        if apps is None:
            return []
        n, healthy, synced = summary(apps)
        status = "OK" if healthy == n and synced == n else "WARN"
        return [(status, f"argo cd  //  {n} apps  ·  {healthy} healthy  ·  {synced} synced")]

    def key_label(self, key: str, s: Snapshot, dash) -> str | None:
        if key == "A":
            return "fechar argocd" if dash.view == "argocd" else "argocd"
        return None

    def handle_key(self, key: str, dash) -> bool:
        if key != "a":
            return False
        if not self.enabled():
            dash.notify("argo cd não encontrado no cluster", AMBER)
            return True
        dash.toggle_view("argocd")
        if dash.view == "argocd" and not self.data:
            dash.notify("lendo as applications do argo cd...", G4, 3)
        return True
