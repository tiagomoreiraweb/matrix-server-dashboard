"""Argo CD integration: Application parsing, events, alerts and the reason borrowed from the pods."""

from __future__ import annotations

import json
import random
import unittest
from unittest import mock

import scenes

from matrixdash.integrations import ArgoCDIntegration
from matrixdash.integrations.argocd import parse_app, summary
from matrixdash.runtime import k3s
from matrixdash.runtime.k3s import K3sRuntime
from matrixdash.theme import CYAN, G5, RED


def make():
    random.seed(1)
    d = scenes.demo.make_dashboard(190, 52)
    d.collector.runtimes = [K3sRuntime()]
    return d, d.integration(ArgoCDIntegration)


class Parsing(unittest.TestCase):
    def test_fields(self):
        apps = {a["name"]: a for a in map(parse_app, scenes.argocd_items())}
        self.assertEqual((apps["shop"]["health"], apps["shop"]["sync"], apps["shop"]["revision"]),
                         ("Degraded", "Synced", "a1b2c3d"))
        self.assertEqual(apps["billing"]["operation"], "Failed")
        self.assertIn("quota exceeded", apps["billing"]["message"])
        self.assertEqual(apps["blog"]["sync"], "OutOfSync")
        self.assertTrue(apps["home"]["auto"])
        self.assertEqual(summary(list(apps.values())), (6, 5, 5))

    def test_resource_health_message(self):
        item = scenes.argocd_items()[0]
        item["status"]["resources"] = [{"kind": "ConfigMap", "name": "env"},
                                       {"kind": "Deployment", "name": "api",
                                        "health": {"status": "Degraded", "message": "exceeded progress deadline"}}]
        self.assertEqual(parse_app(item)["message"], "Deployment/api: exceeded progress deadline")


class Reading(unittest.TestCase):
    def test_reads_through_kubectl_and_explains(self):
        d, argo = make()
        d.collector.containers = scenes.k3s_containers()
        out = json.dumps({"items": scenes.argocd_items()})
        with mock.patch.object(k3s, "find_kubeconfig", lambda configured="": "/tmp/kc"), \
             mock.patch.object(k3s, "run_cmd", lambda args, timeout=2.0, strip=True: (0, out)):
            argo.read()
        self.assertTrue(argo.enabled())
        names = [a["name"] for a in argo.data["apps"]]
        self.assertEqual(names[:3], ["billing", "blog", "shop"])  # problems first
        shop = next(a for a in argo.data["apps"] if a["name"] == "shop")
        self.assertEqual(shop["message"], "api: ImagePullBackOff")

    def test_hidden_without_argocd(self):
        d, argo = make()
        with mock.patch.object(k3s, "find_kubeconfig", lambda configured="": "/tmp/kc"), \
             mock.patch.object(k3s, "run_cmd", lambda *a, **k: (1, "")):
            argo.read()
        self.assertFalse(argo.enabled())
        self.assertNotIn("A", [k for k, _ in d.available_hotkeys()])
        d.handle_key("a")
        self.assertEqual(d.toast[0], "argo cd não encontrado no cluster")

    def test_disabled_without_k3s(self):
        d, argo = make()
        d.collector.runtimes = []
        self.assertFalse(argo.enabled())


class Events(unittest.TestCase):
    def test_transitions(self):
        d, argo = make()
        s = scenes.demo.Snapshot()
        app = parse_app(scenes.argocd_items()[3])  # home, healthy
        s.argocd = {"apps": [dict(app)]}
        argo.detect_events(s)
        events = d.collector.events
        events.clear()
        s.argocd = {"apps": [dict(app, health="Degraded", revision="ffff000")]}
        argo.detect_events(s)
        s.argocd = {"apps": [dict(app, health="Healthy", revision="ffff000", operation="Failed", message="boom")]}
        argo.detect_events(s)
        self.assertEqual([(e.text, e.style) for e in events], [
            ("home healthy -> degraded", RED), ("home deployed ffff000", CYAN),
            ("home degraded -> healthy", G5), ("home sync failed: boom", RED)])

    def test_alerts_ticker_and_boot(self):
        d, argo = make()
        s = d.collector.snap
        s.argocd = {"apps": [parse_app(i) for i in scenes.argocd_items()]}
        self.assertEqual(argo.alerts(s), ["ARGOCD SHOP DEGRADED", "ARGOCD BILLING SYNC FALHOU"])
        self.assertEqual(argo.ticker(s), ["ARGOCD 5/6 HEALTHY · 5/6 SYNCED"])
        self.assertEqual(argo.boot_lines(s), [("WARN", "argo cd  //  6 apps  ·  5 healthy  ·  5 synced")])

    def test_view_key(self):
        d, argo = make()
        d.handle_key("a")
        self.assertEqual(d.view, "argocd")
        d.handle_key("w")
        self.assertIsNone(d.view)
        self.assertTrue(d.netmap_open)


if __name__ == "__main__":
    unittest.main()
