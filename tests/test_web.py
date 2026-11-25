"""Web mirror end to end: a real HTTP server, a client reading the event stream, a theme switch."""

from __future__ import annotations

import random
import socket
import threading
import time
import unittest
import urllib.request

import scenes

from matrixdash import theme
from matrixdash.render.screen import Screen
from matrixdash.web_view import WebMirror


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Stream(unittest.TestCase):
    def tearDown(self):
        theme.apply(theme.DEFAULT_THEME)

    def test_theme_change_reaches_open_pages(self):
        random.seed(1)
        d = scenes.demo.make_dashboard(120, 34)
        port = free_port()
        d.web = WebMirror({"port": port, "allow": ["127.0.0.1/32", "::1/128"]}, lambda: Screen(theme.SGR_LINUX),
                          theme.LINUX_PALETTE, "host")
        d.web.start()
        events: list[str] = []
        stop = threading.Event()

        def read():
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/stream", timeout=10) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace")
                    if line.startswith("event: "):
                        events.append(line[7:].strip())
                    if line.startswith("data: ") and events and events[-1] == "palette":
                        events.append(line)
                    if stop.is_set():
                        return

        reader = threading.Thread(target=read, daemon=True)
        reader.start()

        def publish(n: int):
            for _ in range(n):
                d.web.last_publish = float("-inf")  # the tests freeze the clock that throttles publish()
                d.web.publish(d.render_canvas(d.boot.duration() + 14.0))
                time.sleep(0.05)

        publish(5)
        d.set_theme("gelo")  # no new frame needed: the page is recolored right away
        time.sleep(0.5)
        publish(2)
        stop.set()
        publish(2)
        self.assertIn("frame", events)
        self.assertIn("palette", events)
        data = events[events.index("palette") + 1]
        self.assertIn(theme.THEMES["gelo"]["g5"], data)


class Retry(unittest.TestCase):
    def test_busy_port_is_retried(self):
        random.seed(1)
        d = scenes.demo.make_dashboard(120, 34)
        port = free_port()
        d.config["web"] = {"enabled": True, "port": port, "allow": ["127.0.0.1/32"]}
        blocker = socket.socket(socket.AF_INET6)
        blocker.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        blocker.bind(("::", port))
        blocker.listen()
        d.start_web()
        self.assertIsNone(d.web)
        d.retry_web(d.web_tried + 5)
        self.assertIsNone(d.web)  # too soon
        blocker.close()
        d.retry_web(d.web_tried + d.WEB_RETRY + 1)
        self.assertIsNotNone(d.web)
