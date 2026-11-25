"""Command line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import autodetect
from .config import merge_config
from .dashboard import Dashboard


def main():
    parser = argparse.ArgumentParser(description="Matrix-style terminal server dashboard")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--once", action="store_true", help="Render one frame and exit")
    parser.add_argument("--at", type=float, default=None, help="With --once: seconds since start to render")
    parser.add_argument("--detect", action="store_true", help="Print what was auto-detected on this server and exit")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    if args.detect:
        print(autodetect.report(merge_config(config_path)))
        return

    dashboard = Dashboard(config_path)
    dashboard.run(once=args.once, at=args.at)
