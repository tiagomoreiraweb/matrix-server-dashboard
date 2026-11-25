"""Every block of the screen is a Panel: it draws itself into a rectangle of the canvas.

Panels read the Snapshot and the dashboard state (self.d) and never collect data.
Full-screen layers (boot, header, key bar, overlays) get the whole canvas as rectangle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Snapshot
from ..render.canvas import Canvas
from ..theme import G2, G5

if TYPE_CHECKING:
    from ..dashboard import Dashboard


class Panel:
    def __init__(self, dash: Dashboard):
        self.d = dash

    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        raise NotImplementedError

    @staticmethod
    def frame(c: Canvas, x: int, y: int, w: int, h: int, title: str, right: str, pulse: float,
              border: int = G2, clear: bool = True) -> tuple[int, int, int]:
        """Rounded box with a title and a light running around it; returns (inner x, inner width, last row)."""
        c.box(x, y, w, h, title, right, border, G5, clear=clear)
        c.pulse(x, y, w, h, pulse)
        return x + 2, w - 4, y + h - 1
