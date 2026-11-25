"""Help window, confirmation dialog and toast."""

from __future__ import annotations

import time

from ..models import Snapshot
from ..render.canvas import Canvas
from ..theme import AMBER, G2, G3, G4, G6, KEYCAP, KEYCAP_RED, RED, TEXT, WHITE
from .base import Panel


class Overlays(Panel):
    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        now = time.monotonic()
        if self.d.menu.active:
            self.d.menu.draw(c, t)
        if self.d.help_open:
            rows = [
                ("C", "configurações: rede, painel, containers"),
                ("B", "pausar / retomar o backup do Google Drive"),
                ("S", "sincronizar o backup agora"),
                ("V", "liberar / limitar a banda do backup (turbo)"),
                ("P", "pausar / retomar o download do iCloud"),
                ("U", "relatório de uso do Claude: auto / retrato / relatório"),
                ("A", "Argo CD: sync e saúde de todas as applications"),
                ("W", "mapa da rede: LAN (cabo / wi-fi), Tailscale, Docker"),
                ("X", "abrir terminal (exit volta ao painel; na web abre no navegador)"),
                ("N", "teste de velocidade da internet (~35 MB)"),
                ("E", "modo economia: 4 fps e sem chuva"),
                ("T", "apagar a tela (qualquer tecla liga de novo)"),
                ("M", "ligar / desligar a chuva Matrix"),
                ("I", "mostrar / esconder o retrato"),
                ("G", "disparar um glitch no retrato"),
                ("L", "redesenhar a tela"),
                ("", ""),
                ("D", "DESLIGAR o servidor (pede confirmação)"),
                ("R", "REINICIAR o servidor (pede confirmação)"),
                ("Q", "fechar o painel (pede confirmação)"),
            ]
            have = {k for k, _ in self.d.available_hotkeys()}
            owned = {k for integ in self.d.integrations for k in integ.hotkeys}
            rows = [r for r in rows if r[0] not in owned or r[0] in have]
            bw, bh = 64, len(rows) + 6
            bx, by = (c.w - bw) // 2, max(1, (c.h - bh) // 2)
            c.box(bx, by, bw, bh, "▸ ATALHOS DO TECLADO", "H fecha", G4, G6)
            c.pulse(bx, by, bw, bh, t * 30, 10)
            for i, (key, text) in enumerate(rows):
                if not key:
                    continue
                danger = key in ("D", "R", "Q")
                c.put(bx + 3, by + 2 + i, f" {key} ", KEYCAP_RED if danger else KEYCAP)
                c.put(bx + 8, by + 2 + i, text, AMBER if danger else TEXT)
            c.put(bx + 3, by + bh - 2, "qualquer tecla fecha esta janela", G2)
        if self.d.modal:
            left = self.d.modal["deadline"] - now
            if left <= 0:
                self.d.modal = None
                self.d.notify("cancelado (tempo esgotado)", G4, 2)
            else:
                lines = self.d.modal["lines"]
                bw = max(56, max(len(l) for l in lines) + 8)
                bh = len(lines) + 7
                bx, by = (c.w - bw) // 2, max(1, (c.h - bh) // 2)
                border = RED if int(t * 3) % 2 else AMBER
                c.box(bx, by, bw, bh, f"!! {self.d.modal['title']} !!", "", border, RED)
                for i, line in enumerate(lines):
                    c.put(bx + 3, by + 2 + i, line, TEXT)
                yy = by + 3 + len(lines)
                c.put(bx + 3, yy, " S ", KEYCAP_RED)
                c.put(bx + 7, yy, "confirmar", WHITE)
                c.put(bx + 19, yy, "qualquer outra tecla cancela", G3)
                c.put(bx + bw - 8, yy, f"{left:4.0f}s", AMBER)
        if self.d.toast:
            text, style, until = self.d.toast
            if now > until:
                self.d.toast = None
            else:
                bw = len(text) + 6
                bx, by = (c.w - bw) // 2, c.h - 14
                c.box(bx, by, bw, 3, "", "", style, style)
                c.put(bx + 3, by + 1, text, style if style != G4 else TEXT)
