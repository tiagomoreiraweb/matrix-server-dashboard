"""Color themes: tables switched in place, 256-color mapping, menu choice and web palette event."""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

import scenes

from matrixdash import theme


class Themes(unittest.TestCase):
    def tearDown(self):
        theme.apply(theme.DEFAULT_THEME)

    def test_default_keeps_the_original_colors(self):
        theme.apply("ambar")
        theme.apply(theme.DEFAULT_THEME)
        self.assertEqual(theme.SGR_256, theme.MATRIX_SGR_256)
        self.assertEqual(theme.LINUX_PALETTE[10], "39ff6a")

    def test_every_theme_fills_every_slot(self):
        for name in theme.THEMES:
            self.assertEqual(theme.apply(name), name)
            c = theme.THEMES[name]
            self.assertEqual(theme.LINUX_PALETTE[2], c["g3"])
            self.assertEqual(theme.LINUX_PALETTE[6], c["accent"])
            self.assertTrue(all(v.startswith("38;5;") for k, v in theme.SGR_256.items() if k != theme.NONE))

    def test_tables_change_in_place(self):
        palette = theme.LINUX_PALETTE
        theme.apply("gelo")
        self.assertIs(palette, theme.LINUX_PALETTE)
        self.assertEqual(palette[10], theme.THEMES["gelo"]["g5"])

    def test_unknown_theme_and_overrides(self):
        self.assertEqual(theme.apply("nao-existe"), theme.DEFAULT_THEME)
        theme.apply("matrix", {"accent": "#FF00FF", "g5": "nope", "other": "123456"})
        self.assertEqual(theme.LINUX_PALETTE[6], "ff00ff")
        self.assertEqual(theme.LINUX_PALETTE[10], "39ff6a")
        self.assertEqual(theme.SGR_256[theme.CYAN], "38;5;201")

    def test_xterm256(self):
        self.assertEqual(theme.xterm256("000000"), 16)
        self.assertEqual(theme.xterm256("ffffff"), 231)
        self.assertEqual(theme.xterm256("ff0000"), 196)
        self.assertEqual(theme.xterm256("808080"), 244)


class Menu(unittest.TestCase):
    def tearDown(self):
        theme.apply(theme.DEFAULT_THEME)

    def test_choosing_a_theme_applies_and_saves(self):
        random.seed(1)
        d = scenes.demo.make_dashboard(160, 46)
        with tempfile.TemporaryDirectory() as tmp:
            d.config_path = Path(tmp) / "config.json"
            d.config_path.write_text(json.dumps({"operator": "X"}))
            menu = d.menu
            menu.open()
            menu.cursor = next(i for i, it in enumerate(menu.items) if it.get("key") == "theme")
            menu.handle("right")
            self.assertEqual(d.theme, "ambar")
            self.assertEqual(theme.LINUX_PALETTE[10], theme.THEMES["ambar"]["g5"])
            self.assertEqual(json.loads(d.config_path.read_text())["theme"], "ambar")
            self.assertIn("38;5;", d.screen.sgr[theme.G5])

    def test_web_pages_are_told(self):
        from matrixdash.web_view import WebMirror
        mirror = WebMirror({"port": 0, "allow": []}, lambda: None, theme.LINUX_PALETTE, "host")
        before = mirror.palette_id
        random.seed(1)
        d = scenes.demo.make_dashboard(160, 46)
        d.web = mirror
        d.set_theme("synthwave")
        self.assertEqual(mirror.palette_id, before + 1)
        self.assertEqual(mirror.palette[10], theme.THEMES["synthwave"]["g5"])


if __name__ == "__main__":
    unittest.main()
