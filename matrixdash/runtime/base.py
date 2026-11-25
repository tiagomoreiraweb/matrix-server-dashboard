"""What the dashboard needs from a container runtime.

The collector, the settings menu, the network map and the auto-detection only
talk to this interface, so a new runtime (k3s, Podman...) is one new class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..models import Container


@dataclass
class Endpoint:
    """Ports a running container publishes, used to build its HTTP/TCP probe."""
    name: str
    image: str
    # container port -> (host ip, host port)
    ports: dict[int, tuple[str, int]] = field(default_factory=dict)
    host_network: bool = False


@dataclass
class Network:
    name: str
    driver: str
    subnet: str
    # (container name, ip)
    members: list[tuple[str, str]] = field(default_factory=list)


class ContainerRuntime(ABC):
    """One source of containers. Methods never raise: failures come back as empty results."""

    #: short id, also stored in Container.runtime
    name = ""
    #: label shown on screen
    label = ""
    #: shown by --detect when containers() returns None
    unavailable_hint = "not available"
    #: verbs accepted by action()
    ACTIONS: tuple[str, ...] = ("start", "stop", "restart")
    #: boot screen line: "<what>  //  x/y <unit> running"
    boot_label = "containers"
    boot_unit = "containers"

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @staticmethod
    def installed() -> bool:
        """Whether this runtime exists on the machine (used by "runtimes": ["auto"])."""
        return False

    @abstractmethod
    def containers(self) -> list[Container] | None:
        """Every container (running or not), or None when the runtime is not reachable."""

    def stats(self) -> dict[str, tuple[float | None, str]] | None:
        """name -> (cpu %, memory in use) for running containers; None when the runtime does not answer."""
        return None

    def state(self, name: str) -> tuple[str, str]:
        """(status, started at) of one container; status is "missing" when it does not exist."""
        return "missing", ""

    def logs(self, name: str, since: str = "", tail: int = 0, timeout: float = 8.0) -> list[str]:
        return []

    def supports(self, name: str, verb: str) -> bool:
        """Whether action(name, verb) can work for this container."""
        return verb in self.ACTIONS

    def action(self, name: str, verb: str, timeout: float = 90.0) -> bool:
        """start / stop / restart one container."""
        return False

    def restart_policies(self) -> dict[str, str]:
        return {}

    def endpoints(self) -> list[Endpoint]:
        """Running containers with their published ports."""
        return []

    def networks(self) -> list[Network]:
        return []

    def pids(self, skip: set[str] | None = None) -> dict[str, int] | None:
        """name -> main process id of running containers (to read their network counters).

        None when nothing could be read, so the caller keeps what it had."""
        return None

    def run_sidecar(self, name: str, image: str, script: str, timeout: float = 30.0) -> bool:
        """Run a throwaway container inside another one's network namespace (traffic shaping)."""
        return False
