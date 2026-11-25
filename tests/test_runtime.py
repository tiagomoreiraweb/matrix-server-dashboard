"""DockerRuntime parsing, the collector merge and the probes built from published ports.

The docker CLI is replaced by canned output (captured from a real server), so
these tests run anywhere, with or without Docker.
"""

from __future__ import annotations

import unittest
from unittest import mock

import scenes  # noqa: F401  (sets sys.path and freezes the clock)

from matrixdash import autodetect
from matrixdash.models import Container
from matrixdash.runtime import docker as docker_rt
from matrixdash.runtime.base import ContainerRuntime
from matrixdash.runtime.docker import DockerRuntime, short_age, short_ports

PS_ALL = "\n".join([
    "authentik-worker\trunning\tUp 11 minutes (healthy)\tghcr.io/goauthentik/server:2025.2.4\t",
    "authentik-server\trunning\tUp 11 minutes (health: starting)\tghcr.io/goauthentik/server:2025.2.4\t9000/tcp",
    "redis\trunning\tUp 5 weeks (unhealthy)\tredis:alpine\t6379/tcp",
    "sync\texited\tExited (137) About an hour ago\talpine/git:latest\t",
    "traefik\trunning\tUp 7 weeks\ttraefik:v3\t0.0.0.0:80->80/tcp, :::80->80/tcp, 0.0.0.0:443->443/tcp, :::443->443/tcp",
    "portainer\trunning\tUp Less than a second\tportainer/portainer-ee\t"
    "0.0.0.0:8000->8000/tcp, :::8000->8000/tcp, 127.0.0.1:9443->9443/tcp, 9000/tcp",
    "broken line",
])
PS_PORTS = "\n".join([
    "authentik-server\tghcr.io/goauthentik/server:2025.2.4\t9000/tcp\tauthentik-internal,proxy",
    "traefik\ttraefik:v3\t0.0.0.0:80->80/tcp, :::80->80/tcp, 0.0.0.0:443->443/tcp\tproxy",
    "portainer\tportainer/portainer-ee\t0.0.0.0:8000->8000/tcp, 127.0.0.1:9443->9443/tcp\tproxy",
    "homeassistant\tghcr.io/home-assistant/home-assistant:stable\t\thost",
    "jellyfin\tjellyfin/jellyfin:latest\t0.0.0.0:8097->8096/tcp\tbridge",
    "app\tmy/app:1\t0.0.0.0:9100->3000/tcp, 0.0.0.0:9000->9001/tcp\tbridge",
])
STATS = "\n".join([
    "authentik-worker\t0.04%\t364.3MiB / 11.65GiB",
    "authentik-server\t1.06%\t495.8MiB / 11.65GiB",
    "traefik\t--\t33.3MiB / 11.65GiB",
])
NET_INSPECT = "\n".join([
    "bridge|bridge|172.17.0.0/16 |jellyfin=172.17.0.2/16,app=172.17.0.3/16,",
    "host|host||homeassistant=,",
    "none|null||",
    "proxy|bridge|172.20.0.0/16 |traefik=172.20.0.2/16,portainer=172.20.0.3/16,",
])


def fake_cli(responses: dict[tuple[str, ...], tuple[int, str]]):
    """run_cmd replacement answering by the first words of the command."""
    def run(args, timeout=2.0, strip=True):
        for prefix, (code, out) in responses.items():
            if tuple(args[:len(prefix)]) == prefix:
                return code, out.strip() if strip else out
        return 1, ""
    return run


class DockerParsing(unittest.TestCase):
    def test_short_age(self):
        self.assertEqual(short_age("Up 11 minutes (healthy)"), "11m")
        self.assertEqual(short_age("Up About an hour"), "1h")
        self.assertEqual(short_age("Up Less than a second"), "<1s")
        self.assertEqual(short_age("Exited (0) 2 weeks ago"), "2w")
        self.assertEqual(short_age("Created"), "-")

    def test_short_ports(self):
        self.assertEqual(short_ports("0.0.0.0:80->80/tcp, :::80->80/tcp, 0.0.0.0:443->443/tcp"), ":80,:443")
        self.assertEqual(short_ports("127.0.0.1:9443->9443/tcp"), "lo:9443")
        self.assertEqual(short_ports("9000/tcp"), "-")

    def test_containers(self):
        with mock.patch.object(docker_rt, "run_cmd", fake_cli({("docker", "ps", "-a"): (0, PS_ALL)})):
            found = DockerRuntime().containers()
        self.assertEqual([c.name for c in found],
                         ["authentik-worker", "authentik-server", "redis", "sync", "traefik", "portainer"])
        by = {c.name: c for c in found}
        self.assertEqual((by["authentik-worker"].health, by["authentik-worker"].age), ("healthy", "11m"))
        self.assertEqual(by["authentik-server"].health, "starting")
        self.assertEqual(by["redis"].health, "unhealthy")
        self.assertEqual((by["sync"].state, by["sync"].exit_code, by["sync"].age), ("exited", "137", "1h"))
        self.assertEqual(by["traefik"].ports, ":80,:443")
        self.assertEqual(by["portainer"].ports, ":8000,lo:9443")
        self.assertTrue(all(c.runtime == "docker" and c.cpu is None for c in found))

    def test_unreachable(self):
        with mock.patch.object(docker_rt, "run_cmd", fake_cli({})):
            rt = DockerRuntime()
            self.assertIsNone(rt.containers())
            self.assertIsNone(rt.stats())
            self.assertIsNone(rt.pids())
            self.assertEqual(rt.networks(), [])
            self.assertEqual(rt.endpoints(), [])
            self.assertEqual(rt.state("x"), ("missing", ""))

    def test_stats(self):
        with mock.patch.object(docker_rt, "run_cmd", fake_cli({("docker", "stats"): (0, STATS)})):
            stats = DockerRuntime().stats()
        self.assertEqual(stats, {"authentik-worker": (0.04, "364M"), "authentik-server": (1.06, "496M"),
                                 "traefik": (None, "33M")})

    def test_networks_and_pids(self):
        cli = fake_cli({
            ("docker", "network", "ls"): (0, "a1\nb2\nc3\nd4\n"),
            ("docker", "network", "inspect"): (0, NET_INSPECT),
            ("docker", "ps", "-q"): (0, "x1\nx2\nx3\n"),
            ("docker", "inspect"): (0, "/traefik 101\n/homeassistant 202\n/stopped 0\n"),
        })
        with mock.patch.object(docker_rt, "run_cmd", cli):
            rt = DockerRuntime()
            nets = rt.networks()
            pids = rt.pids({"homeassistant"})
        self.assertEqual([n.name for n in nets], ["bridge", "host", "proxy"])
        self.assertEqual(nets[0].members, [("app", "172.17.0.3"), ("jellyfin", "172.17.0.2")])
        self.assertEqual(nets[1].members, [("homeassistant", "")])
        self.assertEqual(pids, {"traefik": 101})

    def test_checks_from_published_ports(self):
        with mock.patch.object(docker_rt, "run_cmd", fake_cli({("docker", "ps", "--format"): (0, PS_PORTS)})):
            checks = autodetect.container_checks([DockerRuntime()])
        by = {c["container"]: c for c in checks}
        self.assertNotIn("authentik-server", by)  # nothing published
        self.assertEqual(by["traefik"], {"name": "TRAEFIK", "container": "traefik", "auto": True,
                                         "tcp_host": "127.0.0.1", "tcp_port": 80})
        self.assertEqual(by["portainer"]["tcp_port"], 8000)
        self.assertEqual(by["homeassistant"]["url"], "http://127.0.0.1:8123/")
        self.assertEqual(by["jellyfin"]["url"], "http://127.0.0.1:8097/health")  # known port, published elsewhere
        self.assertEqual(by["app"], {"name": "APP", "container": "app", "auto": True,
                                     "tcp_host": "127.0.0.1", "tcp_port": 9000})


class FakeRuntime(ContainerRuntime):
    name, label = "fake", "FAKE"

    def __init__(self, containers, stats=None):
        self._containers, self._stats = containers, stats

    def containers(self):
        return None if self._containers is None else [Container(**c) for c in self._containers]

    def stats(self):
        return self._stats


class CollectorMerge(unittest.TestCase):
    def make(self, runtimes, hidden=()):
        from matrixdash.collector import Collector
        col = Collector.__new__(Collector)
        col.runtimes, col.hidden, col.owner = runtimes, set(hidden), {}
        col.container_stats, col.containers, col.docker_ok = {}, [], False
        return col

    def ct(self, name, state="running"):
        return {"name": name, "state": state, "health": "", "age": "1d", "exit_code": "", "image": "i", "ports": "-"}

    def test_merges_runtimes_stats_and_hidden(self):
        a = FakeRuntime([self.ct("web"), self.ct("db", "exited"), self.ct("Secret")], {"web": (3.0, "10M"), "db": (1.0, "5M")})
        b = FakeRuntime([self.ct("pod-1")], {"pod-1": (0.5, "1M")})
        col = self.make([a, b], hidden={"secret"})
        for rt in col.runtimes:
            col.container_stats.update(rt.stats())
        col.refresh_containers()
        self.assertTrue(col.docker_ok)
        self.assertEqual([(c.name, c.cpu, c.mem) for c in col.containers],
                         [("web", 3.0, "10M"), ("db", None, ""), ("pod-1", 0.5, "1M")])
        self.assertIs(col.runtime_for("pod-1"), b)
        self.assertIs(col.runtime_for("unknown"), a)

    def test_unreachable_runtime(self):
        col = self.make([FakeRuntime(None)])
        col.refresh_containers()
        self.assertFalse(col.docker_ok)
        self.assertEqual(col.containers, [])


if __name__ == "__main__":
    unittest.main()
