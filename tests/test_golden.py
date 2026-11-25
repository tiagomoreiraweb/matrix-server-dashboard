"""Golden tests: every scene must render exactly like tests/golden/<scene>.txt.

    .venv/bin/python -m unittest discover -s tests            # check
    UPDATE_GOLDEN=1 .venv/bin/python -m unittest discover -s tests   # accept the current output

Run on Linux (the dashboard uses termios). Clock, timezone and random numbers
are fixed by tests/scenes.py, so the frames do not depend on the machine.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

import scenes

GOLDEN = Path(__file__).resolve().parent / "golden"


def first_difference(expected: str, actual: str) -> str:
    exp, act = expected.splitlines(), actual.splitlines()
    for i, (a, b) in enumerate(zip(exp, act)):
        if a != b:
            col = next((j for j, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            return f"line {i + 1}, column {col + 1}\n  expected: {a!r}\n  actual:   {b!r}"
    return f"line count {len(exp)} != {len(act)}"


class GoldenFrames(unittest.TestCase):
    maxDiff = None


def _make_test(name: str):
    def test(self):
        actual = scenes.dump(scenes.SCENES[name]())
        path = GOLDEN / f"{name}.txt"
        if os.environ.get("UPDATE_GOLDEN"):
            GOLDEN.mkdir(exist_ok=True)
            path.write_text(actual, encoding="utf-8")
            return
        self.assertTrue(path.exists(), f"missing {path.name}: run with UPDATE_GOLDEN=1")
        expected = path.read_text(encoding="utf-8")
        if expected != actual:
            self.fail(f"scene '{name}' changed: {first_difference(expected, actual)}")
    return test


for _name in scenes.SCENES:
    setattr(GoldenFrames, f"test_{_name}", _make_test(_name))


class Determinism(unittest.TestCase):
    def test_same_scene_twice(self):
        for name in ("dashboard", "integrations", "netmap"):
            self.assertEqual(scenes.dump(scenes.SCENES[name]()), scenes.dump(scenes.SCENES[name]()), name)


if __name__ == "__main__":
    unittest.main()
