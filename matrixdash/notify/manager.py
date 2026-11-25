"""Turns the active alerts into notifications without spamming.

- a problem is only sent after it lasts `delay` minutes (flapping does not notify)
- while it lasts, a reminder every `repeat` minutes (0 = never)
- when it ends, a "resolvido" message, if the problem had been sent
- everything found in the same check goes in one message
- quiet hours and "silenciar por 1 hora" hold messages; what is still active goes out afterwards
Sending runs in its own thread, so a slow channel never delays data collection.
"""

from __future__ import annotations

import fcntl
import json
import queue
import secrets
import socket
import threading
import time
import urllib.request
from typing import TYPE_CHECKING, Any

from .. import ROOT, alerts, validators
from ..config import save_user_config
from ..theme import AMBER, CYAN, G5, RED
from .channels import PROBLEM, REMINDER, RESOLVED, TEST, Message, Notifier, from_config

if TYPE_CHECKING:
    from ..collector import Collector

LOCK_PATH = ROOT / ".alerts.lock"

# A problem must stay away this long before "resolvido" is sent (it may come right back).
SETTLE = 30


def in_window(now: str, start: str, end: str) -> bool:
    """'HH:MM' inside [start, end), the window may cross midnight."""
    return start <= now < end if start <= end else (now >= start or now < end)


def minutes(seconds: float) -> str:
    mins = int(seconds // 60)
    return f"{mins // 60}h{mins % 60:02d}" if mins >= 60 else f"{mins} min"


class AlertManager:
    def __init__(self, collector: Collector):
        self.collector = collector
        self.config = collector.config
        self.state: dict[str, dict[str, Any]] = {}
        self.mute_until = 0.0
        self.last_result = ""
        self.queue: queue.Queue[Message] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.host = socket.gethostname()
        self.lock_file = None

    @property
    def cfg(self) -> dict[str, Any]:
        return self.config.setdefault("alerts", {})

    def sender(self) -> bool:
        """Only one running dashboard sends (the service and a copy opened over SSH would double every
        message): the one holding a lock on .alerts.lock. Retried every check, so when the sender
        stops, another instance takes over."""
        if self.lock_file is not None:
            return True
        try:
            handle = open(LOCK_PATH, "a+")
        except OSError:
            return True  # cannot lock (read-only folder): better twice than never
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.lock_file = handle
        return True

    def channels(self) -> list[Notifier]:
        return from_config(self.cfg)

    def delay(self) -> float:
        return max(0.0, float(self.cfg.get("delay", 2))) * 60

    def repeat(self) -> float:
        return max(0.0, float(self.cfg.get("repeat", 60))) * 60

    def silenced(self, now: float) -> bool:
        if now < self.mute_until:
            return True
        quiet = self.cfg.get("quiet") or {}
        if not quiet.get("enabled"):
            return False
        hhmm = time.strftime("%H:%M", time.localtime(now))
        return in_window(hhmm, str(quiet.get("from", "23:00")), str(quiet.get("to", "07:00")))

    # --- checks (collector thread, every second)

    def check(self, s, now: float | None = None):
        now = time.time() if now is None else now
        current = {a.key: a for a in alerts.active(s, self.collector.thresholds, self.collector.integrations)}
        for key, alert in current.items():
            st = self.state.setdefault(key, {"text": alert.text, "since": now, "sent": 0.0})
            st["text"], st["gone"] = alert.text, 0.0
        for key, st in self.state.items():
            if key not in current and not st.get("gone"):
                st["gone"] = now
        if not self.channels() or self.silenced(now) or not self.sender():
            # Nothing sent now; problems that are still active go out when the silence ends.
            self.state = {k: st for k, st in self.state.items() if k in current or st["sent"]}
            return

        new, remind, resolved = [], [], []
        for key, st in list(self.state.items()):
            if key in current:
                if not st["sent"] and now - st["since"] >= self.delay():
                    new.append(st)
                elif st["sent"] and self.repeat() and now - st["sent"] >= self.repeat():
                    remind.append(st)
            elif now - st["gone"] >= SETTLE or not st["sent"]:
                if st["sent"]:
                    resolved.append(st)
                del self.state[key]
        if not (new or remind or resolved):
            return
        for st in new + remind:
            st["sent"] = now
        self.enqueue(self.compose(new, remind, resolved, now))

    def compose(self, new, remind, resolved, now: float) -> Message:
        lines, items = [], []
        for st in new:
            lines.append(f"🔴 {st['text']}")
            items.append({"key": "", "text": st["text"], "state": "problem", "since": st["since"]})
        for st in remind:
            lines.append(f"🟠 {st['text']} (há {minutes(now - st['since'])})")
            items.append({"key": "", "text": st["text"], "state": "problem", "since": st["since"]})
        for st in resolved:
            lines.append(f"✅ {st['text']} (durou {minutes(st['gone'] - st['since'])})")
            items.append({"key": "", "text": st["text"], "state": "resolved", "since": st["since"]})
        parts = []
        if new:
            parts.append(f"{len(new)} alerta{'s' if len(new) > 1 else ''} novo{'s' if len(new) > 1 else ''}")
        if remind:
            parts.append(f"{len(remind)} ainda ativo{'s' if len(remind) > 1 else ''}")
        if resolved:
            parts.append(f"{len(resolved)} resolvido{'s' if len(resolved) > 1 else ''}")
        kind = PROBLEM if new else REMINDER if remind else RESOLVED
        return Message(self.host, kind, f"{self.host}: " + " · ".join(parts), lines, items)

    # --- sending (own thread)

    def enqueue(self, msg: Message):
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._work, daemon=True)
            self.worker.start()
        self.queue.put(msg)

    def _work(self):
        while True:
            msg = self.queue.get()
            self.deliver(msg)

    def deliver(self, msg: Message) -> list[str]:
        ok, failed = [], []
        for ch in self.channels():
            try:
                ch.send(msg)
                ok.append(ch.name)
            except Exception as exc:
                failed.append(f"{ch.name}: {exc}")
        if ok:
            self.collector.emit("ALERTA", f"{msg.title} → {', '.join(ok)}"[:80], CYAN)
        for err in failed:
            self.collector.emit("ERROR", f"alerta não enviado {err}"[:80], RED)
        self.last_result = (f"enviado {time.strftime('%H:%M')} → {', '.join(ok)}" if ok else "") + \
                           (f" · falhou: {', '.join(f.split(':')[0] for f in failed)}" if failed else "")
        return failed

    def send_test(self, wait: bool = False) -> list[str]:
        """Test message to every channel; with wait=True, sends now and returns the failures."""
        active = alerts.active(self.collector.snap, self.collector.thresholds, self.collector.integrations)
        lines = [f"Canais: {', '.join(ch.name for ch in self.channels())}",
                 f"Alertas ativos agora: {len(active)}"] + [f"• {a.text}" for a in active[:10]]
        msg = Message(self.host, TEST, f"🔔 {self.host}: teste do Matrix Dashboard", lines)
        if wait:
            return self.deliver(msg)
        self.enqueue(msg)
        return []

    def mute(self, seconds: float):
        self.mute_until = time.time() + seconds if seconds else 0.0

    # --- settings menu

    # (config channel, config field) behind each menu field
    CHANNEL_FIELDS = {
        "tg_token": ("telegram", "token"), "tg_chat": ("telegram", "chat_id"),
        "dc_webhook": ("discord", "webhook"),
        "nf_topic": ("ntfy", "topic"), "nf_server": ("ntfy", "server"), "nf_token": ("ntfy", "token"),
        "wh_url": ("webhook", "url"),
    }

    def menu_load(self, values: dict[str, str]):
        quiet = self.cfg.get("quiet") or {}
        values["al_delay"] = str(int(float(self.cfg.get("delay", 2))))
        values["al_repeat"] = str(int(float(self.cfg.get("repeat", 60))))
        values["al_quiet"] = "LIGADO" if quiet.get("enabled") else "DESLIGADO"
        values["al_quiet_from"] = str(quiet.get("from", "23:00"))
        values["al_quiet_to"] = str(quiet.get("to", "07:00"))
        for key, (channel, fld) in self.CHANNEL_FIELDS.items():
            values[key] = str((self.cfg.get(channel) or {}).get(fld) or "")
        values["nf_server"] = values["nf_server"] or "https://ntfy.sh"

    def save(self, menu, update: dict[str, Any], message: str = "alertas salvos"):
        """Merge `update` into config["alerts"] (in memory and in config.json)."""
        def merge(target: dict[str, Any]):
            for key, value in update.items():
                if isinstance(value, dict):
                    section = target.setdefault(key, {})
                    for k, v in value.items():
                        if v in ("", None):
                            section.pop(k, None)
                        else:
                            section[k] = v
                else:
                    target[key] = value
        merge(self.cfg)
        try:
            save_user_config(menu.d.config_path, lambda raw: merge(raw.setdefault("alerts", {})))
            menu.message = (message, G5)
        except (OSError, ValueError) as exc:
            menu.message = (f"erro ao salvar: {exc}"[:70], RED)

    def save_channel_field(self, menu, key: str):
        channel, fld = self.CHANNEL_FIELDS[key]
        value = menu.values[key].strip()
        self.save(menu, {channel: {fld: value}},
                  f"{channel}: {'apagado' if not value else 'salvo'}" + (" · pronto para enviar" if any(
                      c.name == channel for c in self.channels()) else ""))
        menu.build()

    def discover_chat(self, menu):
        """Latest chat that wrote to the bot (getUpdates), saved as chat_id."""
        token = str((self.cfg.get("telegram") or {}).get("token") or "")
        if not token:
            menu.message = ("informe o token do bot primeiro", AMBER)
            return

        def run():
            try:
                req = urllib.request.Request(f"https://api.telegram.org/bot{token}/getUpdates",
                                             headers={"User-Agent": "matrix-dashboard"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    updates = json.loads(resp.read()).get("result") or []
            except Exception as exc:
                menu.message = (f"telegram: {exc}"[:70], RED)
                return
            chat = None
            for upd in reversed(updates):
                for kind in ("message", "channel_post", "my_chat_member", "edited_message"):
                    chat = (upd.get(kind) or {}).get("chat")
                    if chat:
                        break
                if chat:
                    break
            if not chat:
                menu.message = ("nenhuma mensagem: mande um oi para o bot e tente de novo", AMBER)
                return
            menu.values["tg_chat"] = str(chat["id"])
            who = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
            self.save(menu, {"telegram": {"chat_id": str(chat["id"])}}, f"chat encontrado: {who} ({chat['id']})")
            menu.build()
        menu.run_bg("consultando o telegram", run)

    def random_topic(self, menu):
        topic = f"matrix-{self.host.lower()}-{secrets.token_hex(6)}"
        menu.values["nf_topic"] = topic
        self.save(menu, {"ntfy": {"topic": topic}}, f"tópico: {topic} · assine no app ntfy")
        menu.build()

    def menu(self, m):
        menu = m.menu
        names = [ch.name for ch in self.channels()]
        status = "silenciado até " + time.strftime("%H:%M", time.localtime(self.mute_until)) \
            if time.time() < self.mute_until else self.last_result or (" · ".join(names) if names else "")
        m.header("ALERTAS", status or "nenhum canal ainda: configure um abaixo")

        def save():
            v = menu.values
            quiet = {"enabled": v["al_quiet"] == "LIGADO", "from": v["al_quiet_from"], "to": v["al_quiet_to"]}
            self.save(menu, {"delay": int(v["al_delay"]), "repeat": int(v["al_repeat"]), "quiet": quiet})

        def test():
            def run():
                failed = self.send_test(wait=True)
                menu.message = (("falhou: " + "; ".join(failed))[:90], RED) if failed else \
                    (f"teste entregue: {', '.join(names)}", G5)
            menu.run_bg("enviando teste", run)

        def toggle_mute():
            muted = time.time() < self.mute_until
            self.mute(0 if muted else 3600)
            menu.message = ("alertas reativados", G5) if muted else ("alertas silenciados por 1 hora", AMBER)
            menu.build()

        m.field("al_delay", "Avisar depois de (min)", "o problema precisa durar isso · 0 = na hora",
                validators.int_range(0, 60), save)
        m.field("al_repeat", "Lembrar a cada (min)", "enquanto durar · 0 = só uma vez", validators.int_range(0, 1440), save)
        m.field("al_quiet", "Horário de silêncio", "segura os avisos no horário abaixo; os ativos saem depois",
                None, save, "choice", ["DESLIGADO", "LIGADO"])
        m.field("al_quiet_from", "  silêncio das", "HH:MM", validators.clock, save)
        m.field("al_quiet_to", "  até as", "HH:MM", validators.clock, save)
        if names:
            m.action("Enviar mensagem de teste", f"manda um teste para {', '.join(names)} e mostra o resultado",
                     test, CYAN)
            muted = time.time() < self.mute_until
            m.action("Reativar alertas" if muted else "Silenciar por 1 hora", "vale até reiniciar o painel",
                     toggle_mute, G5 if muted else AMBER)

        def field(key, label, hint, check, secret=False, max_len=40):
            m.field(key, label, hint + " · Enter vazio mantém · - apaga" if secret else hint + " · - apaga",
                    check, lambda: self.save_channel_field(menu, key), secret=secret, max_len=max_len)

        def state(name: str) -> str:
            return "ligado" if name in names else "desligado"

        m.header("  TELEGRAM", state("telegram"))
        field("tg_token", "  Token do bot", "do @BotFather (/newbot) · pode colar pelo SSH", validators.telegram_token,
              secret=True, max_len=80)
        field("tg_chat", "  Chat ID", "ou use 'Descobrir' abaixo", validators.chat_id)
        m.action("  Descobrir chat ID", "mande um oi para o bot no Telegram e aperte OK",
                 lambda: self.discover_chat(menu), CYAN)
        m.header("  DISCORD", state("discord"))
        field("dc_webhook", "  URL do webhook", "canal → Editar → Integrações → Webhooks → Copiar URL",
              validators.discord_webhook, secret=True, max_len=200)
        m.header("  NTFY", state("ntfy"))
        field("nf_topic", "  Tópico", "assine o mesmo tópico no app ntfy", validators.ntfy_topic, max_len=64)
        m.action("  Gerar tópico aleatório", "nome difícil de adivinhar (no ntfy.sh público quem sabe o nome lê)",
                 lambda: self.random_topic(menu), CYAN)
        field("nf_server", "  Servidor", "https://ntfy.sh ou o seu", validators.http_url, max_len=120)
        field("nf_token", "  Token (opcional)", "só em servidor com login", None, secret=True, max_len=120)
        m.header("  WEBHOOK", state("webhook"))
        field("wh_url", "  URL", "recebe POST com JSON (n8n, Home Assistant...)", validators.http_url,
              secret=True, max_len=200)
