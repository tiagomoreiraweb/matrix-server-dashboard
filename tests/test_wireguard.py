"""WireGuard integration: interfaces and peers from canned `ip` / `wg show` output."""

from __future__ import annotations

import random
import unittest
from unittest import mock

import scenes

from matrixdash.integrations import WireGuardIntegration
from matrixdash.integrations import wireguard as wgmod
from matrixdash.theme import G5, RED

KEY_A = "A" * 43 + "="
KEY_B = "B" * 43 + "="
NOW = scenes.WALL
WG = {
    "allowed-ips": f"wg0\t{KEY_A}\t10.8.0.2/32 192.168.10.0/24\nwg0\t{KEY_B}\t10.8.0.3/32\n",
    "endpoints": f"wg0\t{KEY_A}\t203.0.113.7:51820\nwg0\t{KEY_B}\t(none)\n",
    "latest-handshakes": f"wg0\t{KEY_A}\t{int(NOW - 40)}\nwg0\t{KEY_B}\t{int(NOW - 4000)}\n",
    "transfer": f"wg0\t{KEY_A}\t1000\t2000\nwg0\t{KEY_B}\t0\t0\n",
    "persistent-keepalive": f"wg0\t{KEY_A}\t25\nwg0\t{KEY_B}\toff\n",
}


def fake(sudo_ok=True, handshakes=None):
    out = dict(WG)
    if handshakes:
        out["latest-handshakes"] = handshakes

    def run(args, timeout=2.0, strip=True):
        if args[:5] == ["ip", "-o", "link", "show", "type"]:
            return 0, "7: wg0: <POINTOPOINT,NOARP,UP,LOWER_UP> mtu 1420 qdisc noqueue state UNKNOWN"
        if args[:4] == ["ip", "-o", "-4", "addr"]:
            return 0, "7: wg0    inet 10.8.0.1/24 scope global wg0"
        if args[:2] == ["sudo", "-n"]:
            return (0, out[args[-1]]) if sudo_ok else (1, "")
        return 1, ""
    return run


def make(config=None):
    random.seed(1)
    d = scenes.demo.make_dashboard(190, 52)
    d.config.update(config or {})
    integ = WireGuardIntegration(d.collector)
    d.collector.integrations = [i for i in d.collector.integrations if not isinstance(i, WireGuardIntegration)]
    d.collector.integrations.append(integ)
    d.integrations = d.collector.integrations
    return d, integ


def read(integ, **kw):
    integ.peers_at = float("-inf")  # always re-read the peers in these tests
    with mock.patch.object(wgmod, "run_cmd", fake(**kw)), \
         mock.patch.object(wgmod.shutil, "which", lambda name: "/usr/bin/wg"), \
         mock.patch.object(wgmod, "counters", lambda iface: (5000, 7000)):
        integ.read()


class Reading(unittest.TestCase):
    def test_interfaces_and_peers(self):
        d, wg = make({"wireguard": {"names": {"10.8.0.2": "casa"}}})
        read(wg)
        self.assertTrue(wg.enabled())
        iface = wg.data["ifaces"][0]
        self.assertEqual((iface["name"], iface["address"]), ("wg0", "10.8.0.1/24"))
        casa, other = iface["peers"]
        self.assertEqual((casa["name"], casa["online"], casa["endpoint"], casa["keepalive"]),
                         ("casa", True, "203.0.113.7:51820", 25))
        self.assertEqual((other["name"], other["online"], other["endpoint"]), ("10.8.0.3", False, ""))
        self.assertNotIn(KEY_A, str(wg.data))  # only a short id of the public key is kept

    def test_without_sudo_shows_interface_only(self):
        d, wg = make()
        read(wg, sudo_ok=False)
        s = d.collector.snap
        wg.fill(s)
        self.assertFalse(s.wireguard["peers_known"])
        ok, state, _, detail, _ = wg.unit_view("wg-quick@wg0", s)
        self.assertEqual((ok, state), (True, "ACTIVE"))
        self.assertIn("wireguard-sudo.sh", detail)
        self.assertEqual(wg.ticker(s), [])

    def test_disabled(self):
        d, wg = make({"wireguard": False})
        read(wg)
        self.assertFalse(wg.enabled())


class Interval(unittest.TestCase):
    def test_peers_are_read_once_a_minute(self):
        d, wg = make()
        calls = []
        run = fake()

        def counting(args, timeout=2.0, strip=True):
            if args[:2] == ["sudo", "-n"]:
                calls.append(args[-1])
            return run(args, timeout, strip)
        clock = [1000.0]
        with mock.patch.object(wgmod, "run_cmd", counting), \
             mock.patch.object(wgmod.shutil, "which", lambda name: "/usr/bin/wg"), \
             mock.patch.object(wgmod, "counters", lambda iface: (5000, 7000)), \
             mock.patch.object(wgmod.time, "monotonic", lambda: clock[0]):
            wg.read()
            clock[0] += 12
            wg.read()
            self.assertEqual(len(calls), 5)  # second read reused the peers
            self.assertEqual(len(wg.data["ifaces"][0]["peers"]), 2)
            clock[0] += 50
            wg.read()
            self.assertEqual(len(calls), 10)


class Status(unittest.TestCase):
    def test_unit_row_ticker_boot(self):
        d, wg = make()
        read(wg)
        s = d.collector.snap
        wg.fill(s)
        self.assertEqual(wg.unit_view("wg-quick@wg0", s)[:3], (True, "ONLINE", G5))
        self.assertIsNone(wg.unit_view("ssh", s))
        self.assertEqual(wg.ticker(s), ["WIREGUARD 1/2 PEERS"])
        self.assertEqual(wg.boot_lines(s), [("OK", "wireguard wg0  //  10.8.0.1/24 · 1/2 peers")])

    def test_keepalive_peer_lost_raises_alert_and_event(self):
        d, wg = make()
        s = d.collector.snap
        read(wg)
        wg.fill(s)
        wg.detect_events(s)
        events = d.collector.events
        events.clear()
        read(wg, handshakes=f"wg0\t{KEY_A}\t{int(NOW - 600)}\nwg0\t{KEY_B}\t0\n")
        wg.fill(s)
        wg.detect_events(s)
        self.assertEqual([(e.text, e.style) for e in events], [("wireguard peer 10.8.0.2 offline", RED)])
        self.assertEqual(wg.alerts(s), ["WIREGUARD: 10.8.0.2 SEM HANDSHAKE HÁ 10 MIN"])
        ok, state, _, _, _ = wg.unit_view("wg-quick@wg0", s)
        self.assertEqual((ok, state), (False, "NO PEER"))

    def test_interface_gone(self):
        d, wg = make()
        s = d.collector.snap
        read(wg)
        wg.fill(s)
        wg.detect_events(s)
        with mock.patch.object(wgmod, "interfaces", lambda: []), \
             mock.patch.object(wgmod.shutil, "which", lambda name: "/usr/bin/wg"):
            wg.read()
        wg.fill(s)
        wg.detect_events(s)
        self.assertIn("WIREGUARD FORA DO AR", wg.alerts(s))
        self.assertEqual(wg.unit_view("wg-quick@wg0", s)[:2], (False, "DOWN"))

    def test_menu_system_line(self):
        d, wg = make()
        read(wg)
        wg.fill(d.collector.snap)
        menu = d.menu
        menu.sysinfo = {"ip": "", "prefix": "", "gateway": "", "mode": "", "mac": "", "ipv6": "", "dns": ""}
        menu.build()
        info = {it["label"]: it["value"] for it in menu.items if it["kind"] == "info"}
        self.assertEqual(info["WireGuard wg0"], "10.8.0.1/24 · 1/2 peers online")


if __name__ == "__main__":
    unittest.main()
