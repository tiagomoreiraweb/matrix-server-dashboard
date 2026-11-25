"""Keys, integration actions, menu savers and events (things the golden frames do not cover)."""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

import scenes

from matrixdash.integrations import BackupIntegration, ClaudeIntegration, ICloudIntegration
from matrixdash.runtime.base import ContainerRuntime
from matrixdash.theme import AMBER, CYAN, G5


def dashboard(cols: int = 190, rows: int = 52):
    random.seed(1)
    return scenes.demo.make_dashboard(cols, rows)


def last_toast(d) -> str:
    return d.toast[0] if d.toast else ""


class Keys(unittest.TestCase):
    def test_integration_keys_without_configuration(self):
        d = dashboard()
        d.handle_key("b")
        self.assertEqual(last_toast(d), "backup não configurado")
        d.handle_key("p")
        self.assertEqual(last_toast(d), "download do iCloud não configurado")

    def test_usage_mode_cycles(self):
        d = dashboard()
        modes = []
        for _ in range(3):
            d.handle_key("u")
            modes.append(d.usage_mode)
        self.assertEqual(modes, ["retrato", "relatório", "auto"])

    def test_unknown_key(self):
        d = dashboard()
        d.handle_key("z")
        self.assertIn("sem função", last_toast(d))

    def test_hotkeys_follow_enabled_integrations(self):
        d = dashboard()
        keys = [k for k, _ in d.available_hotkeys()]
        self.assertIn("U", keys)  # claude forced on by the demo
        self.assertNotIn("B", keys)
        self.assertNotIn("P", keys)

    def test_confirm_dialog(self):
        d = dashboard()
        done = []
        d.confirm("X", ["y"], lambda: done.append(1))
        d.handle_key("n")
        self.assertEqual(done, [])
        d.confirm("X", ["y"], lambda: done.append(1))
        d.handle_key("S")
        self.assertEqual(done, [1])


class Backup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.state = self.dir / "state.json"
        self.d = dashboard()
        self.d.config["backup_state"] = str(self.state)
        self.backup = BackupIntegration(self.d.collector)
        self.d.collector.integrations[0] = self.backup
        self.d.integrations = self.d.collector.integrations

    def tearDown(self):
        self.tmp.cleanup()

    def test_pause_resume_turbo_and_run_now(self):
        self.d.handle_key("b")
        self.assertTrue((self.dir / "PAUSE").exists())
        self.d.handle_key("b")
        self.assertFalse((self.dir / "PAUSE").exists())
        self.assertTrue((self.dir / "RUN_NOW").exists())
        self.d.handle_key("v")
        self.assertTrue(self.backup.turbo_on())
        self.d.handle_key("v")
        self.assertFalse(self.backup.turbo_on())
        (self.dir / "RUN_NOW").unlink()
        self.d.handle_key("s")
        self.assertTrue((self.dir / "RUN_NOW").exists())

    def test_state_file_and_events(self):
        self.backup.read()
        self.assertEqual(self.backup.data, {"status": "not_started"})
        self.state.write_text(json.dumps({"status": "running", "updated": scenes.WALL - 200}))
        self.backup.read()
        self.assertEqual(self.backup.data["status"], "stalled")  # no write for > 90 s
        s = scenes.demo.Snapshot()
        events = self.d.collector.events
        events.clear()
        for status in ("idle", "running", "done"):
            s.backup = {"status": status}
            self.backup.detect_events(s)
        self.assertEqual([(e.tag, e.text) for e in events],
                         [("BACKUP", "backup started"), ("BACKUP", "backup complete, drive in sync")])

    def test_menu_section_saves_backup_json(self):
        (self.dir / "backup.json").write_text(json.dumps({"bwlimit": "08:00,3M 23:00,8M", "other": 1}))
        menu = self.d.menu
        menu.open()
        keys = [it.get("key") for it in menu.items]
        self.assertIn("bk_day_rate", keys)
        menu.values["bk_day_rate"] = "5m"
        item = next(it for it in menu.items if it.get("key") == "bk_day_rate")
        item["save"]()
        saved = json.loads((self.dir / "backup.json").read_text())
        self.assertEqual(saved, {"bwlimit": "08:00,5M 23:00,8M", "other": 1, "daily_sync_at": "02:00"})
        self.assertEqual(menu.message, ("backup salvo · limite novo vale em segundos", G5))


class FakeRuntime(ContainerRuntime):
    name, label = "fake", "FAKE"

    def __init__(self):
        self.calls = []

    def containers(self):
        return []

    def action(self, name, verb, timeout=90.0):
        self.calls.append((name, verb))
        return True

    def run_sidecar(self, name, image, script, timeout=30.0):
        self.calls.append((name, "tc", script))
        return True


class ICloud(unittest.TestCase):
    def test_limit_is_saved_and_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = dashboard()
            d.config_path = Path(tmp) / "config.json"
            d.config_path.write_text(json.dumps({"title": "x"}))
            rt = FakeRuntime()
            d.collector.runtimes = [rt]
            d.config["icloud"] = {"container": "icloudpd"}
            ic = d.integration(ICloudIntegration)
            self.assertIsNone(ic.set_limit(d.config_path, "3M"))
            self.assertEqual(json.loads(d.config_path.read_text()), {"title": "x", "icloud": {"limit": "3M"}})
            for _ in range(100):
                if rt.calls:
                    break
                __import__("time").sleep(0.01)
            self.assertEqual(rt.calls[0][:2], ("icloudpd", "tc"))
            self.assertIn("rate 24mbit", rt.calls[0][2])

    def test_log_parsing(self):
        info = {"total": 0, "current": ""}
        status = ICloudIntegration.parse_logs([
            "2026-11-24 10:00:00 INFO     Downloading 25110 original photos",
            "2026-11-24 10:00:05 INFO     Downloaded /data/2023/08/IMG_1.HEIC",
        ], info)
        self.assertEqual((status, info["total"], info["current"]), ("downloading", 25110, "2023/08/IMG_1.HEIC"))
        status = ICloudIntegration.parse_logs(["2026-11-24 10:00:00 ERROR    Authentication failed: invalid password"],
                                              {"total": 0})
        self.assertEqual(status, "login")


class Ticker(unittest.TestCase):
    def test_plan_and_icloud_items_without_backup(self):
        d = dashboard()
        s = d.collector.snap
        s.plan = scenes.plan_state()
        s.icloud = scenes.icloud_state()
        items = [i for integ in d.integrations for i in integ.ticker(s)]
        self.assertEqual(items, ["CLAUDE 5H 64% · SEMANA 92%", "ICLOUD 72.6% · 18234/25110 ITENS"])

    def test_alerts_from_integrations(self):
        d = dashboard()
        s = d.collector.snap
        s.icloud = scenes.icloud_state("login")
        s.tailscale = {"state": "NeedsLogin"}
        s.plan = {"windows": {"five_hour": {"pct": 100.0, "resets": scenes.WALL + 600}}}
        alerts = d.alerts(s)
        self.assertEqual(alerts[-3:], ["CLAUDE: LIMITE DE 5H ESGOTADO - RENOVA ÀS 14:42",
                                       "ICLOUD PRECISA DE LOGIN - ABRA A PORTA 8090",
                                       "TAILSCALE DESLOGADO - SEM ACESSO REMOTO"])


class ContainerMenu(unittest.TestCase):
    def test_action_goes_to_owning_runtime(self):
        d = dashboard()
        rt = FakeRuntime()
        d.collector.runtimes = [rt]
        d.collector.owner = {"jellyfin": rt}
        menu = d.menu
        menu.open()
        menu.container_action("jellyfin", "reiniciar", "")
        modal = d.modal
        self.assertEqual(modal["title"], "REINICIAR CONTAINER")
        d.handle_key("s")
        for _ in range(100):
            if rt.calls:
                break
            __import__("time").sleep(0.01)
        self.assertEqual(rt.calls, [("jellyfin", "restart")])


class Claude(unittest.TestCase):
    def test_session_events(self):
        d = dashboard()
        claude = d.integration(ClaudeIntegration)
        events = d.collector.events
        events.clear()
        s = scenes.demo.Snapshot()
        for n in (1, 2, 1):
            s.claude = scenes.demo.ClaudeInfo(running=True, sessions=n)
            claude.detect_events(s)
        self.assertEqual([(e.text, e.style) for e in events],
                         [("session started (2 active)", CYAN), ("session ended (1 active)", CYAN)])

    def test_probe_lines(self):
        d = dashboard()
        claude = d.integration(ClaudeIntegration)
        s = scenes.demo.Snapshot()
        self.assertEqual(claude.probe_lines(s), ["claude code not running"])
        self.assertNotEqual(AMBER, G5)


if __name__ == "__main__":
    unittest.main()
