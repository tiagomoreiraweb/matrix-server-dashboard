"""K3sRuntime: workloads from pods, health from container states, metrics and restart."""

from __future__ import annotations

import json
import unittest
from unittest import mock

import scenes

from matrixdash import runtime
from matrixdash.runtime import k3s
from matrixdash.runtime.k3s import K3sRuntime, cpu_percent, mem_bytes, short_age

T0 = "2026-11-24T12:00:00Z"  # 2h32m before the frozen clock


def pod(ns, name, owner=None, tmpl="", ready=True, waiting="", phase="Running", image="app:1", started=T0):
    meta = {"namespace": ns, "name": name, "creationTimestamp": T0, "labels": {}}
    if owner:
        meta["ownerReferences"] = [{"kind": owner[0], "name": owner[1]}]
    if tmpl:
        meta["labels"]["pod-template-hash"] = tmpl
    state = {"waiting": {"reason": waiting}} if waiting else {"running": {"startedAt": started}}
    return {"metadata": meta, "spec": {"containers": [{"image": image}]},
            "status": {"phase": phase, "containerStatuses": [{"ready": ready and not waiting, "state": state}]}}


def workload(kind, ns, name, replicas=1):
    item = {"kind": kind, "metadata": {"namespace": ns, "name": name, "creationTimestamp": T0}}
    if kind == "DaemonSet":
        item["status"] = {"desiredNumberScheduled": replicas}
    else:
        item["spec"] = {"replicas": replicas}
    return item


PODS = {"items": [
    pod("web", "site-7d9f8-abcde", ("ReplicaSet", "site-7d9f8"), "7d9f8"),
    pod("web", "site-7d9f8-fghij", ("ReplicaSet", "site-7d9f8"), "7d9f8", ready=False),
    pod("data", "postgres-0", ("StatefulSet", "postgres")),
    pod("auth", "postgres-0", ("StatefulSet", "postgres")),
    pod("shop", "api-5c6-x1", ("ReplicaSet", "api-5c6"), "5c6", waiting="ImagePullBackOff"),
    pod("bot", "worker-11-a", ("ReplicaSet", "worker-11"), "11", waiting="CrashLoopBackOff"),
    pod("kube-system", "agent-xyz", ("DaemonSet", "agent")),
    pod("jobs", "backup-29-q", ("Job", "backup-29"), phase="Succeeded", ready=False),
    pod("misc", "debug", None),
]}
CONTROLLERS = {"items": [
    workload("Deployment", "web", "site", 2),
    workload("StatefulSet", "data", "postgres"),
    workload("StatefulSet", "auth", "postgres"),
    workload("Deployment", "shop", "api"),
    workload("Deployment", "bot", "worker"),
    workload("DaemonSet", "kube-system", "agent", 1),
    workload("Deployment", "old", "legacy", 0),
]}
TOP = """web   site-7d9f8-abcde   250m   100Mi
web   site-7d9f8-fghij   50m    20Mi
data  postgres-0         3m     1Gi
"""


def fake_kubectl(calls=None):
    def run(args, timeout=2.0, strip=True):
        if calls is not None:
            calls.append(args)
        rest = args[3:]  # after kubectl --kubeconfig <path>
        if rest[:3] == ["get", "pods", "-A"]:
            return 0, json.dumps(PODS)
        if rest[:2] == ["get", "deployments,statefulsets,daemonsets"]:
            return 0, json.dumps(CONTROLLERS)
        if rest[:2] == ["top", "pods"]:
            return 0, TOP
        if rest[:2] == ["rollout", "restart"]:
            return 0, "restarted"
        return 1, ""
    return run


class K3s(unittest.TestCase):
    def setUp(self):
        self.calls: list = []
        patches = [mock.patch.object(k3s, "run_cmd", fake_kubectl(self.calls)),
                   mock.patch.object(k3s, "find_kubeconfig", lambda configured="": "/tmp/kc.yaml")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.rt = K3sRuntime()

    def test_one_row_per_workload(self):
        by = {c.name: c for c in self.rt.containers()}
        self.assertEqual(sorted(by), ["auth/postgres", "bot/worker", "data/postgres", "kube-system/agent",
                                      "misc/debug", "old/legacy", "shop/api", "web/site"])
        site = by["web/site"]
        self.assertEqual((site.state, site.health, site.ports, site.short, site.age, site.runtime),
                         ("running", "starting", "web 1/2", "site", "2h", "k3s"))
        self.assertEqual((by["data/postgres"].health, by["data/postgres"].short), ("healthy", "postgres"))
        self.assertEqual((by["shop/api"].state, by["shop/api"].health, by["shop/api"].exit_code),
                         ("pending", "unhealthy", "ImagePullBackOff"))
        self.assertEqual((by["bot/worker"].state, by["bot/worker"].health), ("restarting", "unhealthy"))
        self.assertEqual(by["old/legacy"].state, "exited")
        self.assertEqual(by["kube-system/agent"].ports, "kube-system 1/1")

    def test_stats_summed_per_workload(self):
        self.rt.containers()
        stats = self.rt.stats()
        self.assertAlmostEqual(stats["web/site"][0], 30.0)
        self.assertEqual(stats["web/site"][1], "120M")
        self.assertEqual(stats["data/postgres"], (0.3, "1.0G"))

    def test_restart_uses_rollout_on_the_workload(self):
        self.rt.containers()
        self.assertTrue(self.rt.action("web/site", "restart"))
        self.assertEqual(self.calls[-1][3:], ["rollout", "restart", "-n", "web", "deployment/site"])
        self.assertTrue(self.rt.action("data/postgres", "restart"))
        self.assertEqual(self.calls[-1][3:], ["rollout", "restart", "-n", "data", "statefulset/postgres"])
        self.assertFalse(self.rt.action("misc/debug", "restart"))  # bare pod
        self.assertFalse(self.rt.action("web/site", "stop"))

    def test_unreachable(self):
        with mock.patch.object(k3s, "run_cmd", lambda *a, **k: (1, "")):
            self.assertIsNone(self.rt.containers())
            self.assertIsNone(self.rt.stats())

    def test_units(self):
        self.assertEqual(cpu_percent("250m"), 25.0)
        self.assertEqual(cpu_percent("2"), 200.0)
        self.assertEqual(mem_bytes("1Gi"), 1024 ** 3)
        self.assertEqual(short_age(59), "59s")
        self.assertEqual(short_age(3 * 86400), "3d")


class Detection(unittest.TestCase):
    def test_auto_picks_installed_runtimes(self):
        with mock.patch.object(runtime.DockerRuntime, "installed", staticmethod(lambda: True)), \
             mock.patch.object(runtime.K3sRuntime, "installed", staticmethod(lambda: True)):
            self.assertEqual([r.name for r in runtime.from_config({})], ["docker", "k3s"])
        with mock.patch.object(runtime.DockerRuntime, "installed", staticmethod(lambda: False)), \
             mock.patch.object(runtime.K3sRuntime, "installed", staticmethod(lambda: False)):
            self.assertEqual([r.name for r in runtime.from_config({})], ["docker"])
        self.assertEqual([r.name for r in runtime.from_config({"runtimes": ["k3s"]})], ["k3s"])


class Screen(unittest.TestCase):
    def test_k3s_problem_shows_in_alerts_and_menu(self):
        d = scenes.demo.make_dashboard(190, 52)
        rt = K3sRuntime()
        with mock.patch.object(k3s, "run_cmd", fake_kubectl()), \
             mock.patch.object(k3s, "find_kubeconfig", lambda configured="": "/tmp/kc.yaml"):
            d.collector.runtimes = [rt]
            d.collector.refresh_containers()
        s = d.collector.snap
        s.containers = d.collector.containers
        s.runtimes = d.collector.runtime_status
        alerts = d.alerts(s)
        self.assertIn("API IMAGEPULLBACKOFF", alerts)
        self.assertIn("WORKER CRASHLOOPBACKOFF", alerts)
        menu = d.menu
        menu.load = lambda: None
        menu.sysinfo = {"ip": "", "prefix": "", "gateway": "", "mode": "", "mac": "", "ipv6": "", "dns": ""}
        menu.build()
        rows = {it["label"]: it["actions"] for it in menu.items if it["kind"] == "container"}
        self.assertEqual(rows["web/site"], ["reiniciar"])
        self.assertNotIn("old/legacy", rows)  # scaled to zero: nothing to restart
        self.assertNotIn("misc/debug", rows)  # bare pod


if __name__ == "__main__":
    unittest.main()
