"""Matrix Server Dashboard: terminal monitor for a Linux server (tty1, SSH or browser)."""

from pathlib import Path

VERSION = "3.0"

# Repository folder: config.json, assets/, web/ and the small state files live here.
ROOT = Path(__file__).resolve().parent.parent
