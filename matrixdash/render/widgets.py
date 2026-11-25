"""Small drawing helpers shared by the panels."""

from __future__ import annotations

from ..theme import AMBER, G1, G3, G4, G5, G6, RED
from .canvas import Canvas


def bar(c: Canvas, x: int, y: int, width: int, pct: float, t: float, style: int = G5, phase: float = 0.0):
    """Horizontal gauge with a sheen running over healthy (G5) bars."""
    width = max(4, width)
    pct = max(0.0, min(100.0, pct))
    exact = width * pct / 100
    filled = int(exact)
    frac = exact - filled
    c.put(x, y, "░" * width, G1)
    if filled:
        c.put(x, y, "█" * filled, style)
    if filled < width and frac >= 0.35:
        c.put(x + filled, y, "▒", style)
    if filled > 2 and style == G5:
        sheen = int((t * 18 + phase) % (width + 25))
        if sheen < filled:
            c.style_at(x + sheen, y, G6)


def section(c: Canvas, x: int, y: int, w: int, label: str, right: str = "", style: int = G4, gap: int = 2):
    """'━━ LABEL ───────── right' heading line inside a panel."""
    c.put(x, y, "━━ " + label + " ", style)
    fill = w - len(label) - 4 - (len(right) + gap if right else 0)
    c.put(x + len(label) + 4, y, "─" * max(0, fill), G1)
    if right:
        c.put(x + w - len(right), y, right, G3)


def level(value: float, threshold: float) -> int:
    """RED at the threshold, AMBER from 80% of it, G5 below."""
    if value >= threshold:
        return RED
    if value >= threshold * 0.8:
        return AMBER
    return G5
