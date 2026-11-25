"""
Web mirror of the Matrix dashboard.

The dashboard publishes every rendered canvas here; each browser connected to
/stream (Server-Sent Events) gets its own diff renderer, so only changed cells
travel over the network. The page draws them with xterm.js using the same
green console palette. Access is limited to the networks in config
("web.allow"), by default localhost, the home LAN and Tailscale.

With "web.control" (default off) the page can also send keys: POST /key
queues them for the dashboard loop, which handles them like the local
keyboard (D, R and Q still ask for confirmation). The request must carry the
X-Matrix-Key header, which a cross-site form cannot set, so other web pages
open in a LAN browser cannot press keys.

"web.terminal" (default off, needs "control") enables a web terminal: /term/stream?id=... starts a login
shell on a pseudo-terminal and streams its output; /term/input and
/term/resize feed it. The shell dies when its stream disconnects.
"""

from __future__ import annotations

import base64
import fcntl
import ipaddress
import json
import os
import pty
import pwd
import secrets
import select
import signal
import socket
import struct
import termios
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import ROOT

WEB_DIR = ROOT / "web"
STATIC = {
    "/static/xterm.js": ("xterm.js", "application/javascript"),
    "/static/xterm.css": ("xterm.css", "text/css"),
}
SETUP = "\x1b[?25l\x1b[?7l"  # hide cursor, no autowrap
NAMED_KEYS = {"esc", "enter", "up", "down", "left", "right", "backspace", " "}


MAX_SHELLS = 4


class Shell:
    """A login shell on its own pseudo-terminal."""

    def __init__(self, cols: int = 120, rows: int = 32):
        user = pwd.getpwuid(os.getuid())
        env = {
            "HOME": user.pw_dir, "USER": user.pw_name, "LOGNAME": user.pw_name, "SHELL": user.pw_shell or "/bin/bash",
            "TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        }
        pid, fd = pty.fork()
        if pid == 0:
            try:
                os.chdir(user.pw_dir)
                shell = user.pw_shell or "/bin/bash"
                os.execvpe(shell, [shell, "-l"], env)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        self.resize(cols, rows)

    def resize(self, cols: int, rows: int):
        cols, rows = max(20, min(400, cols)), max(5, min(200, rows))
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def write(self, data: bytes):
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def close(self):
        try:
            os.killpg(self.pid, signal.SIGHUP)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        for _ in range(20):
            try:
                if os.waitpid(self.pid, os.WNOHANG)[0]:
                    return
            except ChildProcessError:
                return
            time.sleep(0.05)
        try:
            os.killpg(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        except (OSError, ChildProcessError):
            pass


class WebMirror:
    def __init__(self, config: dict[str, Any], screen_factory: Callable[[], Any], palette: dict[int, str],
                 title: str):
        self.port = int(config.get("port", 8095))
        self.allow = [ipaddress.ip_network(n, strict=False) for n in config.get("allow", [])]
        self.fps = max(1, min(10, int(config.get("fps", 5))))
        self.screen_factory = screen_factory
        self.palette = palette
        self.palette_id = 0
        self.title = title
        self.canvas = None
        self.frame_id = 0
        self.cond = threading.Condition()
        self.clients = 0
        self.last_publish = 0.0
        self.control = bool(config.get("control", False))
        # A browser shell has no password of its own: only on trusted networks.
        self.terminal = self.control and bool(config.get("terminal", False))
        self.keys: deque[str] = deque(maxlen=32)
        self.shells: dict[str, Shell] = {}
        self.shell_lock = threading.Lock()

    def palette_changed(self):
        """The theme changed: open pages get the new colors and a full redraw."""
        with self.cond:
            self.palette_id += 1
            self.cond.notify_all()

    def pop_keys(self) -> list[str]:
        out = []
        while self.keys:
            out.append(self.keys.popleft())
        return out

    # --- called from the dashboard render loop

    def publish(self, canvas):
        now = time.monotonic()
        if now - self.last_publish < 1.0 / self.fps:
            return
        self.last_publish = now
        with self.cond:
            self.canvas = canvas
            self.frame_id += 1
            self.cond.notify_all()

    # --- server

    def allowed(self, host: str) -> bool:
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            return False
        if getattr(addr, "ipv4_mapped", None):
            addr = addr.ipv4_mapped
        return any(addr in net for net in self.allow if addr.version == net.version)

    def start(self):
        mirror = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def deny(self):
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"forbidden\n")

            def do_GET(self):
                if not mirror.allowed(self.client_address[0]):
                    return self.deny()
                if self.path in ("/", "/index.html"):
                    return self.serve_index()
                if self.path in STATIC:
                    name, ctype = STATIC[self.path]
                    return self.serve_file(WEB_DIR / "static" / name, ctype)
                if self.path == "/stream":
                    return self.stream()
                if self.path.startswith("/term/stream") and mirror.terminal:
                    return self.term_stream()
                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                if not mirror.allowed(self.client_address[0]):
                    return self.deny()
                if not mirror.control or self.headers.get("X-Matrix-Key") != "1":
                    return self.deny()
                if self.path in ("/term/input", "/term/resize"):
                    return self.term_post() if mirror.terminal else self.deny()
                if self.path != "/key":
                    return self.deny()
                try:
                    length = min(int(self.headers.get("Content-Length") or 0), 256)
                    key = str(json.loads(self.rfile.read(length) or b"{}").get("key", ""))
                except (ValueError, AttributeError):
                    key = ""
                if key in NAMED_KEYS or (len(key) == 1 and key.isprintable()):
                    mirror.keys.append(key)
                    self.send_response(204)
                else:
                    self.send_response(400)
                self.end_headers()

            def term_post(self):
                try:
                    length = min(int(self.headers.get("Content-Length") or 0), 65536)
                    body = json.loads(self.rfile.read(length) or b"{}")
                    shell = mirror.shells.get(str(body.get("id", "")))
                except (ValueError, AttributeError):
                    shell = None
                if shell is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if self.path == "/term/input":
                    shell.write(str(body.get("data", "")).encode("utf-8", "surrogateescape"))
                else:
                    shell.resize(int(body.get("cols", 120)), int(body.get("rows", 32)))
                self.send_response(204)
                self.end_headers()

            def term_stream(self):
                query = parse_qs(urlparse(self.path).query)
                sid = (query.get("id") or [""])[0][:64] or secrets.token_hex(8)
                try:
                    cols, rows = int((query.get("cols") or ["120"])[0]), int((query.get("rows") or ["32"])[0])
                except ValueError:
                    cols, rows = 120, 32
                with mirror.shell_lock:
                    if sid in mirror.shells or len(mirror.shells) >= MAX_SHELLS:
                        self.send_response(429)
                        self.end_headers()
                        return
                    shell = Shell(cols, rows)
                    mirror.shells[sid] = shell
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                try:
                    self.send_event("ready", {"id": sid})
                    while True:
                        ready, _, _ = select.select([shell.fd], [], [], 15)
                        if not ready:
                            # Keepalive also detects a closed browser tab.
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                            continue
                        try:
                            data = os.read(shell.fd, 65536)
                        except OSError:
                            data = b""
                        if not data:
                            self.send_event("exit", {})
                            break
                        self.send_event("o", base64.b64encode(data).decode("ascii"))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with mirror.shell_lock:
                        mirror.shells.pop(sid, None)
                    shell.close()

            def serve_file(self, path: Path, ctype: str):
                try:
                    data = path.read_bytes()
                except OSError:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "max-age=86400")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def serve_index(self):
                html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
                html = html.replace("__PALETTE__", json.dumps(mirror.palette))
                html = html.replace("__TITLE__", mirror.title)
                html = html.replace("__CONTROL__", "true" if mirror.control else "false")
                html = html.replace("__TERMINAL__", "true" if mirror.terminal else "false")
                data = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def send_event(self, event: str, payload: Any):
                msg = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()

            def stream(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                screen = mirror.screen_factory()
                seen, size = -1, None
                palette_seen = mirror.palette_id
                with mirror.cond:
                    mirror.clients += 1
                try:
                    while True:
                        with mirror.cond:
                            if mirror.frame_id == seen and mirror.palette_id == palette_seen:
                                mirror.cond.wait(timeout=15)
                            canvas, seen_now = mirror.canvas, mirror.frame_id
                        # A theme change recolors the page right away, even when the screen is still.
                        recolor = mirror.palette_id != palette_seen
                        if canvas is None or (seen_now == seen and not recolor):
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                            continue
                        seen = seen_now
                        if recolor:
                            palette_seen = mirror.palette_id
                            self.send_event("palette", mirror.palette)
                            screen = mirror.screen_factory()
                            size = None
                        if (canvas.w, canvas.h) != size:
                            size = (canvas.w, canvas.h)
                            screen.invalidate()
                            self.send_event("size", {"cols": canvas.w, "rows": canvas.h})
                            self.send_event("frame", SETUP + screen.frame(canvas))
                            continue
                        data = screen.frame(canvas)
                        if data:
                            self.send_event("frame", data)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with mirror.cond:
                        mirror.clients -= 1

        class Server(ThreadingHTTPServer):
            address_family = socket.AF_INET6
            daemon_threads = True

            def server_bind(self):
                # Dual-stack: accept IPv4 (as mapped addresses) and IPv6.
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                super().server_bind()

        server = Server(("::", self.port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
