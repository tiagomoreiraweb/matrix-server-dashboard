"""Runs the real entry point: --detect and one full frame with live collection (--once)."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, COLUMNS="200", LINES="56")
    return subprocess.run([sys.executable, "matrix_dashboard.py", "--config", "config.example.json", *args],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


class EntryPoint(unittest.TestCase):
    def test_detect(self):
        result = run("--detect")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("interface", result.stdout)

    def test_once(self):
        result = run("--once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SYSTEM // TELEMETRY", result.stdout)

    def test_once_boot(self):
        result = run("--once", "--at", "1.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BOOT // INITIALIZING", result.stdout)


if __name__ == "__main__":
    unittest.main()
