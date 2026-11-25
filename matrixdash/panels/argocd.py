"""Argo CD: a block in the services panel and a full-screen list of the applications (hotkey A)."""

from __future__ import annotations

import math

from ..fmt import ago
from ..integrations.argocd import BAD_HEALTH, FAILED_OPS, problem, summary
from ..models import Snapshot
from ..render.canvas import Canvas
from ..render.widgets import section
from ..theme import AMBER, CYAN, G0, G1, G2, G3, G4, G5, G6, RED, SPINNER, TEXT
from .base import Panel
from .services import ServiceRows, ServicesSection

SYNC_STYLE = {"Synced": G5, "OutOfSync": AMBER}
HEALTH_STYLE = {"Healthy": G5, "Progressing": CYAN, "Suspended": G3, "Degraded": RED, "Missing": RED}


def health_style(app: dict) -> int:
    return HEALTH_STYLE.get(app["health"], AMBER)


def dot_style(app: dict, t: float, blink: bool) -> int:
    if app["health"] in BAD_HEALTH or app["operation"] in FAILED_OPS:
        return RED if blink else G0
    if problem(app):
        return AMBER
    return G6 if (math.sin(t * 2.2 + len(app["name"])) + 1) / 2 > 0.7 else G5


class ArgoSection(ServicesSection):
    """Problem apps one per row, then one line with the names of the healthy ones."""

    MAX_ROWS = 4

    def reserve(self, s: Snapshot) -> int:
        apps = (s.argocd or {}).get("apps") or []
        return 2 + min(self.MAX_ROWS, sum(1 for a in apps if problem(a))) + (1 if apps else 0)

    def draw(self, rows: ServiceRows, s: Snapshot, t: float):
        apps = (s.argocd or {}).get("apps")
        if apps is None:
            return
        c, ix, iw, bottom = rows.c, rows.ix, rows.iw, rows.bottom
        blink = int(t * 2) % 2 == 0
        n, healthy, synced = summary(apps)
        rows.row += 1 if bottom - rows.row > 4 else 0
        rows.heading("GITOPS // ARGO CD", f"{healthy}/{n} healthy · {synced}/{n} synced  A lista", CYAN)
        bad = [a for a in apps if problem(a)]
        for a in bad[: self.MAX_ROWS]:
            if rows.row >= bottom:
                return
            row = rows.row
            c.put(ix, row, "●", dot_style(a, t, blink))
            c.put(ix + 2, row, a["name"][: rows.name_w], TEXT)
            c.put(rows.col_state, row, a["health"].upper()[:11], health_style(a))
            sync = a["sync"] if a["operation"] not in FAILED_OPS else "FAILED"
            c.put(rows.col_up + 4, row, sync[:10], SYNC_STYLE.get(a["sync"], AMBER) if sync == a["sync"] else RED)
            detail = a["message"] or f"{a['revision']} · {ago(a['synced_at'])}"
            dx = rows.col_up + 16
            c.put(dx, row, detail[: max(0, ix + iw - dx)], G3)
            rows.row += 1
        if len(bad) > self.MAX_ROWS and rows.row < bottom:
            c.put(ix + 2, rows.row, f"+{len(bad) - self.MAX_ROWS} com problema · A abre a lista", AMBER)
            rows.row += 1
        good = [a["name"] for a in apps if not problem(a)]
        if good and rows.row < bottom:
            c.put(ix, rows.row, "●", G5)
            label = f"{len(good)} ok: "
            c.put(ix + 2, rows.row, label, G4)
            c.put(ix + 2 + len(label), rows.row, " ".join(good)[: max(0, iw - len(label) - 2)], G3)
            rows.row += 1


class ArgoPanel(Panel):
    """Full list of applications, in place of the system and services panels."""

    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        data = s.argocd or {}
        apps = data.get("apps")
        read = f"lido {ago(data['at'])}" if data.get("at") else "lendo..."
        ix, iw, bottom = self.frame(c, x, y, w, h, "▸ GITOPS // ARGO CD · APPLICATIONS", f"A fecha · {read}",
                                    t * 18 + 30)
        row = y + 1
        if apps is None:
            c.put(ix, row + 1, f"{SPINNER[int(t * 8) % 4]} lendo as applications do cluster...", G4)
            return
        n, healthy, synced = summary(apps)
        failed = sum(1 for a in apps if a["operation"] in FAILED_OPS)
        stats = [(f"{n} apps", G6), (f"healthy {healthy}/{n}", G5 if healthy == n else RED),
                 (f"synced {synced}/{n}", G5 if synced == n else AMBER),
                 (f"auto-sync {sum(1 for a in apps if a['auto'])}/{n}", G4)]
        if failed:
            stats.append((f"sync falhou {failed}", RED))
        xx = ix
        for text, style in stats:
            c.put(xx, row, text, style)
            xx += len(text) + 4
        row += 2

        wide = iw >= 140
        cols = [("APPLICATION", 26), ("NAMESPACE", 18), ("SYNC", 11), ("HEALTH", 12), ("REVISÃO", 8),
                ("ALVO", 10), ("SYNC HÁ", 8)]
        if not wide:
            cols = [col for col in cols if col[0] not in ("ALVO", "NAMESPACE")]
        used = sum(cw + 1 for _, cw in cols) + 2
        cols.append(("MENSAGEM", max(0, iw - used)))
        section(c, ix, row, iw, "APPLICATIONS", f"{len([a for a in apps if problem(a)])} com problema", CYAN)
        row += 1
        xx = ix + 2
        for label, cw in cols:
            c.put(xx, row, label[:cw], G2)
            xx += cw + 1
        row += 1
        blink = int(t * 2) % 2 == 0
        for a in apps:
            if row >= bottom - 1:
                c.put(ix + 2, row, f"+{n - apps.index(a)} applications não cabem na tela", G2)
                break
            c.put(ix, row, "●", dot_style(a, t, blink))
            xx = ix + 2
            for label, cw in cols:
                if label == "APPLICATION":
                    c.put(xx, row, a["name"][:cw], TEXT)
                elif label == "NAMESPACE":
                    c.put(xx, row, a["namespace"][:cw], G3)
                elif label == "SYNC":
                    text = "FAILED" if a["operation"] in FAILED_OPS else a["sync"]
                    c.put(xx, row, text[:cw], RED if text == "FAILED" else SYNC_STYLE.get(a["sync"], AMBER))
                elif label == "HEALTH":
                    c.put(xx, row, a["health"][:cw], health_style(a))
                elif label == "REVISÃO":
                    c.put(xx, row, a["revision"][:cw] or "-", G4)
                elif label == "ALVO":
                    c.put(xx, row, a["target"][:cw], G3)
                elif label == "SYNC HÁ":
                    c.put(xx, row, ago(a["synced_at"])[:cw], G3)
                elif cw > 0:
                    msg = a["message"] or ("auto-sync" if a["auto"] else "sync manual")
                    c.put(xx, row, msg[:cw], AMBER if a["message"] and problem(a) else G1)
                xx += cw + 1
            row += 1
        note = "lido do cluster com a conta matrix-dashboard (só leitura) · atualiza a cada ~12 s"
        c.put(ix, bottom - 1, note[:iw], G1)
