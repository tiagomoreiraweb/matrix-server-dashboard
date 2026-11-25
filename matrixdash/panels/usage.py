"""Claude Code usage report (alternates with the portrait)."""

from __future__ import annotations

import time

from ..claude_usage import short_model
from ..fmt import fmt_tokens
from ..models import Snapshot
from ..render.canvas import Canvas
from ..render.widgets import bar, section
from ..theme import AMBER, CYAN, DAYS_PT, G1, G2, G3, G4, G5, G6, RED, TEXT, WHITE
from .base import Panel


def limit_style(pct: float) -> int:
    return RED if pct >= 90 else AMBER if pct >= 70 else G5


def reset_label(resets: float, key: str) -> str:
    """When a plan window renews: 'até 14:00', 'até sex 09:00' or 'renovado'."""
    if not resets:
        return ""
    if resets <= time.time():
        return "renovado"
    lt = time.localtime(resets)
    if key == "five_hour" or resets - time.time() < 20 * 3600:
        return time.strftime("até %H:%M", lt)
    return f"até {DAYS_PT[lt.tm_wday].lower()} {time.strftime('%H:%M', lt)}"


class UsagePanel(Panel):

    def draw_plan_limits(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, t: float) -> int:
        """Two wide bars like the claude.ai 'usage limits' card. Returns rows used."""
        plan = s.plan or {}
        windows = plan.get("windows") or {}
        name = f" · {plan['plan']}" if plan.get("plan") else ""
        age = time.time() - float(plan.get("updated") or 0)
        fresh = "agora" if age < 90 else f"há {int(age // 60)} min"
        label = "━━ LIMITES DO PLANO" + name + " "
        right = f" atualizado {fresh}" if windows else " aguardando dados do Claude Code"
        c.put(x, y, label, CYAN)
        c.put(x + len(label), y, "─" * max(0, w - len(label) - len(right)), G1)
        c.put(x + w - len(right), y, right, G3 if age < 600 else AMBER)
        row = y + 1
        for key, label in (("five_hour", "Limite de 5 horas"), ("seven_day", "Semanal · todos os modelos")):
            win = windows.get(key)
            if not win:
                continue
            style = limit_style(win["pct"])
            info = f"{reset_label(win['resets'], key):>14}  {win['pct']:3.0f}%"
            c.put(x, row, label, TEXT)
            c.put(x + w - len(info), row, info, style if style != G5 else G6)
            bar_x = x + 28
            bar(c, bar_x, row, max(8, w - 28 - len(info) - 2), win["pct"], t, style)
            row += 1
        return row - y

    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        u = s.usage or {}
        mode = "" if self.d.usage_mode == "auto" else " · fixo"
        ix, iw, bottom = self.frame(c, x, y, w, h, "▸ CLAUDE CODE // RELATÓRIO DE USO", f"U alterna{mode}", t * 18)
        row = y + 1
        # Bars grow in when the page appears.
        grow = min(1.0, ((t % 60) - 40) / 1.2) if self.d.usage_mode == "auto" else 1.0
        grow = max(0.05, grow)

        def heading(label: str, right: str = ""):
            nonlocal row
            if row < bottom:
                section(c, ix, row, iw, label, right, CYAN, gap=1)
                row += 1

        if s.plan:
            row += self.draw_plan_limits(c, s, ix, row, iw, t) + 1

        # Summary cards
        cards = [("HOJE", u.get("today")), ("ÚLTIMAS 5H", u.get("last5h")), ("ESTA SEMANA", u.get("week")),
                 ("30 DIAS", u.get("last30d")), ("TOTAL", u.get("total"))]
        card_w = iw // len(cards)
        for i, (label, d) in enumerate(cards):
            d = d or {}
            cx = ix + i * card_w
            c.put(cx, row, label, G4)
            c.put(cx, row + 1, f"${d.get('cost', 0):,.2f}", WHITE if i == 0 else G6)
            c.put(cx, row + 2, f"{fmt_tokens(d.get('tokens', 0))} tokens", TEXT)
            c.put(cx, row + 3, f"{int(d.get('messages', 0))} respostas", G3)
            c.put(cx, row + 4, f"saída {fmt_tokens(d.get('output', 0))}", G3)
        row += 6

        # Hourly chart
        hourly = u.get("hourly") or []
        heading("POR HORA · ÚLTIMAS 24H", "custo equivalente em US$")
        chart_h = 5 if h >= 38 else 3
        if hourly and row + chart_h + 1 < bottom:
            values = [d["cost"] * grow for _, d in hourly]
            vmax = max(max(values), 0.01)
            bar_w, gap = max(1, (iw - 8) // len(values) - 1), 1
            for r in range(chart_h):
                level = chart_h - r
                c.put(ix, row + r, f"{vmax * level / chart_h:6.2f}" if r in (0, chart_h - 1) else "", G2)
                for i, v in enumerate(values):
                    f = v / vmax * chart_h - (level - 1)
                    ch = "█" if f >= 0.75 else "▒" if f >= 0.45 else "░" if f >= 0.12 else ""
                    if ch:
                        style = CYAN if i == len(values) - 1 else G5 if r < 2 else G4
                        c.put(ix + 8 + i * (bar_w + gap), row + r, ch * bar_w, style)
            row += chart_h
            for i, (hour, _) in enumerate(hourly):
                if i % 3 == 0:
                    c.put(ix + 8 + i * (bar_w + gap), row, time.strftime("%Hh", time.localtime(hour)), G3)
            row += 2

        # Daily chart
        daily = u.get("daily") or []
        heading("POR DIA · ÚLTIMOS 14 DIAS")
        chart_h = 4 if h >= 38 else 3
        if daily and row + chart_h + 2 < bottom:
            values = [d["cost"] * grow for _, d in daily]
            vmax = max(max(values), 0.01)
            slot = (iw - 8) // len(values)
            bar_w = max(1, slot - 2)
            for r in range(chart_h):
                level = chart_h - r
                for i, v in enumerate(values):
                    f = v / vmax * chart_h - (level - 1)
                    ch = "█" if f >= 0.75 else "▒" if f >= 0.45 else "░" if f >= 0.12 else ""
                    if ch:
                        c.put(ix + 8 + i * slot, row + r, ch * bar_w, CYAN if i == len(values) - 1 else G5)
            row += chart_h
            for i, (day, d) in enumerate(daily):
                bx = ix + 8 + i * slot
                c.put(bx, row, time.strftime("%d/%m", time.localtime(day))[:slot - 1], G3)
                if d["cost"] > 0:
                    c.put(bx, row + 1, f"{d['cost']:.1f}"[:slot - 1], TEXT)
            row += 3

        # Weeks + models side by side
        if row + 2 < bottom:
            half = iw // 2
            top = row
            heading("SEMANAS")
            for start, d in u.get("weeks") or []:
                if row >= bottom:
                    break
                label = "esta semana" if start == (u.get("weeks") or [(0, 0)])[0][0] else time.strftime("sem %d/%m", time.localtime(start))
                c.put(ix, row, f"{label:<12}", G3)
                c.put(ix + 13, row, f"{'$' + format(d['cost'], ',.2f'):>10}", G6 if d["cost"] else G2)
                c.put(ix + 24, row, f"{fmt_tokens(d['tokens']):>7} tok", TEXT)
                row += 1
            row_after_weeks = row
            row = top
            mx = ix + half + 2
            c.put(mx, row, "━━ POR MODELO ", CYAN)
            c.put(mx + 14, row, "─" * max(0, half - 16), G1)
            row += 1
            models = u.get("models") or []
            total_cost = sum(m[1]["cost"] for m in models) or 1
            for model, d in models[:4]:
                if row >= bottom:
                    break
                share = d["cost"] / total_cost * 100
                c.put(mx, row, f"{short_model(model):<11}", WHITE)
                c.put(mx + 12, row, f"{'$' + format(d['cost'], ',.2f'):>10}", G6)
                c.put(mx + 23, row, f"{int(d['messages']):>5} resp", G3)
                bar(c, mx + 34, row, max(4, half - 42), share, t, CYAN)
                c.put(mx + 36 + max(4, half - 42), row, f"{share:3.0f}%", G4)
                row += 1
            row = max(row, row_after_weeks) + 1

        # Token breakdown for today
        today = u.get("today") or {}
        if row + 1 < bottom and today:
            heading("TOKENS DE HOJE")
            parts = [("entrada", today.get("input", 0)), ("saída", today.get("output", 0)),
                     ("escrita cache", today.get("cache_write", 0)), ("leitura cache", today.get("cache_read", 0))]
            xx = ix
            for label, val in parts:
                txt = f"{label} {fmt_tokens(val)}"
                c.put(xx, row, label, G3)
                c.put(xx + len(label) + 1, row, fmt_tokens(val), TEXT)
                xx += len(txt) + 4
            row += 1
            if row < bottom - 1:
                since = u.get("since")
                since_txt = time.strftime("%d/%m %H:%M", time.localtime(since)) if since else "-"
                c.put(ix, row, f"sessões: {u.get('active_sessions', 0)} ativa(s) · {u.get('sessions', 0)} no total"
                               f" · registros desde {since_txt}", G3)
            row += 2
        if row < bottom:
            note = "Custo estimado pelo preço de API. Assinatura não cobra por token; limites do plano não ficam no servidor."
            c.put(ix, bottom - 1, note[:iw], G2)
