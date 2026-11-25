"""Defaults and loading of config.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from . import autodetect
from .storage import write_json

DEFAULT_CONFIG: dict[str, Any] = {
    # "" = "<HOSTNAME> // MATRIX SERVER MONITOR"
    "title": "",
    # name shown on the boot screen; "" = the Linux user
    "operator": "",
    "brand": "MATRIX SECURE TERMINAL",
    # photo (png/jpg) or ready ASCII art (.txt); missing file = server name in big letters
    "image": "assets/portrait.png",
    "fps": 12,
    "matrix_density": 0.45,
    # color theme: matrix, ambar, gelo, synthwave, mono (menu C -> PAINEL -> Tema)
    "theme": "matrix",
    # optional per-color overrides on top of the theme: {"accent": "ff00ff", "g5": "39ff6a"}
    "theme_colors": {},
    "boot_animation": True,
    "console_palette": True,
    "ping_host": "1.1.1.1",
    "ping_host6": "2606:4700:4700::1111",
    # Lists with "auto" are filled by autodetect.py; extra items next to "auto" are kept.
    "mounts": ["auto"],
    "thresholds": {
        "cpu": 85,
        "ram": 85,
        "disk": 90,
        "temperature": 80
    },
    "systemd_units": ["auto"],
    "checks": ["auto"],
    "hide_containers": [],
    # container sources: "auto" = every one installed here ("docker", "k3s")
    "runtimes": ["auto"],
    # k3s: kubeconfig of the dashboard's ServiceAccount (system/k8s/make-kubeconfig.sh); "" = search
    "kubeconfig": "",
    # Argo CD applications read from the k3s cluster: "auto" = when the CRD exists, false = never
    "argocd": "auto",
    # WireGuard: false hides it; {"names": {"10.8.0.2": "casa"}} names peers by allowed IP;
    # "peers_every": seconds between peer reads (they need sudo), default 60
    "wireguard": {},
    # optional integrations, off unless configured
    "backup_state": "",
    "icloud": {},
    "network_interface": "auto",
    # "auto" = show the Claude Code panel only when Claude Code is installed
    "claude": "auto",
    "claude_plan": "",
    # control: keys/clicks from the page; terminal: a shell in the browser (no password!)
    "web": {"enabled": False, "port": 8095, "fps": 5, "control": False, "terminal": False,
            "allow": ["auto"]},
    "claude_limits_file": "~/.claude/statusline-last.json",
    "screen_off": {"enabled": False, "from": "00:00", "to": "07:00"},
    # notifications of the header alerts (docs/INTEGRACOES.md): minutes before sending, reminder
    # interval (0 = never), quiet hours, and the channels telegram / discord / ntfy / webhook
    "alerts": {"delay": 2, "repeat": 60, "quiet": {"enabled": False, "from": "23:00", "to": "07:00"}},
}


def merge_config(path: Path) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
            for key, value in user.items():
                if key.startswith("_"):
                    continue
                if isinstance(value, dict) and isinstance(config.get(key), dict):
                    config[key].update(value)
                else:
                    config[key] = value
        except Exception as exc:
            print(f"Could not read {path}: {exc}", file=sys.stderr)
    return autodetect.resolve(config)


def save_user_config(path: Path, mutate: Callable[[dict[str, Any]], Any], create: bool = True):
    """Apply `mutate` to the JSON in config.json and write it back; only keys it touches change.

    With create=False a missing file is an error (OSError), as for settings that only make
    sense once the file exists."""
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() or not create else {}
    mutate(raw)
    write_json(path, raw, indent=2)
