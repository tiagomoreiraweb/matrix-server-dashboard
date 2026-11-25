"""Container runtimes behind one interface (see base.ContainerRuntime)."""

from __future__ import annotations

from typing import Any

from .base import ContainerRuntime, Endpoint, Network
from .docker import DockerRuntime
from .k3s import K3sRuntime

__all__ = ["ContainerRuntime", "DockerRuntime", "Endpoint", "K3sRuntime", "Network", "from_config"]

RUNTIMES: dict[str, type[ContainerRuntime]] = {DockerRuntime.name: DockerRuntime, K3sRuntime.name: K3sRuntime}


def from_config(config: dict[str, Any] | None = None) -> list[ContainerRuntime]:
    """Runtimes listed in config["runtimes"].

    "auto" (the default) takes every runtime installed here; Docker stays in the list when nothing
    is found, so the screen still says why there are no containers."""
    config = config or {}
    names = config.get("runtimes") or ["auto"]
    if isinstance(names, str):
        names = [names]
    chosen: list[str] = []
    for name in names:
        if name == "auto":
            found = [n for n, cls in RUNTIMES.items() if cls.installed()] or [DockerRuntime.name]
            chosen += [n for n in found if n not in chosen]
        elif name in RUNTIMES and name not in chosen:
            chosen.append(name)
    return [RUNTIMES[n](config) for n in chosen]
