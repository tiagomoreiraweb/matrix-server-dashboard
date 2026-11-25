"""Checks for values typed in the settings menu: each returns an error text or None."""

from __future__ import annotations

import ipaddress
import re
from typing import Callable

RATE_RE = re.compile(r"^(off|\d+(\.\d+)?[KMG]?)$", re.I)
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

Validator = Callable[[str], "str | None"]


def ipv4(value: str) -> str | None:
    try:
        ipaddress.IPv4Address(value.strip())
        return None
    except ValueError:
        return "IP inválido"


def prefix(value: str) -> str | None:
    return None if value.isdigit() and 8 <= int(value) <= 30 else "use um número de 8 a 30"


def dns(value: str) -> str | None:
    parts = [x.strip() for x in value.split(",") if x.strip()]
    if not 1 <= len(parts) <= 4:
        return "informe de 1 a 4 servidores"
    for part in parts:
        try:
            ipaddress.ip_address(part)
        except ValueError:
            return f"DNS inválido: {part}"
    return None


def rate(value: str) -> str | None:
    return None if RATE_RE.match(value.strip()) else "use algo como 3M, 500K ou off"


def clock(value: str) -> str | None:
    return None if TIME_RE.match(value.strip()) else "use HH:MM, ex.: 23:00"


def name(value: str) -> str | None:
    return None if 1 <= len(value.strip()) <= 20 else "de 1 a 20 caracteres"


def int_range(lo: int, hi: int) -> Validator:
    return lambda value: None if value.strip().isdigit() and lo <= int(value) <= hi else f"número de {lo} a {hi}"


def float_range(lo: float, hi: float) -> Validator:
    def check(value: str) -> str | None:
        try:
            return None if lo <= float(value) <= hi else f"número de {lo} a {hi}"
        except ValueError:
            return f"número de {lo} a {hi}"
    return check


def telegram_token(value: str) -> str | None:
    return None if re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", value.strip()) else "token do BotFather: 123456:ABC..."


def chat_id(value: str) -> str | None:
    return None if re.fullmatch(r"-?\d+|@\w{4,}", value.strip()) else "número (ex.: 123456789) ou @canal"


def http_url(value: str) -> str | None:
    return None if re.fullmatch(r"https?://\S+", value.strip()) else "URL começando com http:// ou https://"


def discord_webhook(value: str) -> str | None:
    ok = re.fullmatch(r"https://(\w+\.)?discord(app)?\.com/api/webhooks/\d+/\S+", value.strip())
    return None if ok else "URL do webhook: https://discord.com/api/webhooks/..."


def ntfy_topic(value: str) -> str | None:
    return None if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value.strip()) else "letras, números, - e _ (até 64)"
