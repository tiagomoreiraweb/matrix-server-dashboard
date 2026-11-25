"""Where alert messages go: one Notifier per channel (Telegram, Discord, ntfy, generic webhook)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .. import VERSION

PROBLEM, RESOLVED, REMINDER, TEST = "problem", "resolved", "reminder", "test"


@dataclass
class Message:
    host: str
    kind: str                      # PROBLEM, RESOLVED, REMINDER or TEST
    title: str
    lines: list[str] = field(default_factory=list)
    # [{"key", "text", "state": "problem" | "resolved", "since": epoch}] for machines (webhook)
    alerts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join([self.title, *self.lines])


class Notifier:
    """One destination. send() raises on failure so the caller can report it."""

    name = ""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg

    def configured(self) -> bool:
        return False

    def send(self, msg: Message):
        raise NotImplementedError

    @staticmethod
    def post(url: str, payload: Any, headers: dict[str, str] | None = None, timeout: float = 10.0):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": f"matrix-dashboard/{VERSION}", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:200].decode("utf-8", "replace")
            raise RuntimeError(f"HTTP {exc.code} {detail}".strip()) from None


class Telegram(Notifier):
    name = "telegram"

    def configured(self) -> bool:
        return bool(self.cfg.get("token") and self.cfg.get("chat_id"))

    def send(self, msg: Message):
        self.post(f"https://api.telegram.org/bot{self.cfg['token']}/sendMessage",
                  {"chat_id": self.cfg["chat_id"], "text": msg.text[:4000], "disable_web_page_preview": True})


class Discord(Notifier):
    name = "discord"
    COLORS = {PROBLEM: 0xE0302A, REMINDER: 0xFFAF00, RESOLVED: 0x39FF6A, TEST: 0x00E0FF}

    def configured(self) -> bool:
        return str(self.cfg.get("webhook", "")).startswith("https://")

    def send(self, msg: Message):
        self.post(str(self.cfg["webhook"]), {
            "username": str(self.cfg.get("username") or "Matrix Dashboard"),
            "embeds": [{"title": msg.title[:250], "description": "\n".join(msg.lines)[:4000],
                        "color": self.COLORS.get(msg.kind, 0x00E0FF)}],
        })


class Ntfy(Notifier):
    name = "ntfy"
    PRIORITY = {PROBLEM: 4, REMINDER: 3, RESOLVED: 3, TEST: 3}
    TAGS = {PROBLEM: ["rotating_light"], REMINDER: ["warning"], RESOLVED: ["white_check_mark"], TEST: ["bell"]}

    def configured(self) -> bool:
        return bool(self.cfg.get("topic"))

    def send(self, msg: Message):
        # JSON publishing (POST to the server root) avoids HTTP-header encoding limits on accents.
        server = str(self.cfg.get("server") or "https://ntfy.sh").rstrip("/")
        headers = {"Authorization": f"Bearer {self.cfg['token']}"} if self.cfg.get("token") else {}
        self.post(server, {"topic": str(self.cfg["topic"]), "title": msg.title, "message": "\n".join(msg.lines) or msg.title,
                           "priority": self.PRIORITY.get(msg.kind, 3), "tags": self.TAGS.get(msg.kind, [])}, headers)


class Webhook(Notifier):
    name = "webhook"

    def configured(self) -> bool:
        return str(self.cfg.get("url", "")).startswith(("http://", "https://"))

    def send(self, msg: Message):
        headers = {str(k): str(v) for k, v in (self.cfg.get("headers") or {}).items()}
        self.post(str(self.cfg["url"]), {"host": msg.host, "kind": msg.kind, "title": msg.title,
                                         "text": msg.text, "alerts": msg.alerts}, headers)


CHANNELS: list[type[Notifier]] = [Telegram, Discord, Ntfy, Webhook]


def from_config(alerts_cfg: dict[str, Any]) -> list[Notifier]:
    found = []
    for cls in CHANNELS:
        cfg = alerts_cfg.get(cls.name)
        if isinstance(cfg, dict):
            notifier = cls(cfg)
            if notifier.configured():
                found.append(notifier)
    return found
