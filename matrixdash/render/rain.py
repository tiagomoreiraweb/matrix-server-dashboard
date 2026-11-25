"""Matrix rain background."""

from __future__ import annotations

import random
from typing import Any

from ..theme import DIM_LUT, G1, G2, G3, G4, G5, G6, MATRIX_CHARS
from .canvas import Canvas


class MatrixRain:
    def __init__(self, width: int, height: int, density: float):
        self.width = width
        self.height = height
        self.density = max(0.05, min(1.0, density))
        self.columns: list[dict[str, Any]] = []
        self._build()

    def _new_column(self, x: int, initial: bool) -> dict[str, Any]:
        return {
            "x": x,
            "y": random.uniform(-self.height, self.height) if initial else random.uniform(-20, -1),
            "speed": random.uniform(0.3, 1.25),
            "trail": random.randint(6, 18),
            "glyphs": [random.choice(MATRIX_CHARS) for _ in range(self.height + 20)],
        }

    def _build(self):
        self.columns = [
            self._new_column(x, True)
            for x in range(0, self.width, 2)
            if random.random() <= self.density
        ]

    def resize(self, width: int, height: int):
        if width != self.width or height != self.height:
            self.width = width
            self.height = height
            self._build()

    def update(self):
        for i, col in enumerate(self.columns):
            col["y"] += col["speed"]
            glyphs = col["glyphs"]
            for _ in range(2):
                glyphs[random.randrange(len(glyphs))] = random.choice(MATRIX_CHARS)
            if col["y"] - col["trail"] > self.height:
                self.columns[i] = self._new_column(col["x"], False)

    def draw(self, canvas: Canvas, dim_rect: tuple[int, int, int, int] | None = None):
        h = canvas.h
        dx0, dy0, dx1, dy1 = dim_rect if dim_rect else (-1, -1, -1, -1)
        for col in self.columns:
            x = col["x"]
            if x >= canvas.w:
                continue
            dim_col = dx0 <= x < dx1
            head = int(col["y"])
            trail = col["trail"]
            glyphs = col["glyphs"]
            for t in range(trail):
                y = head - t
                if not (0 <= y < h):
                    continue
                ratio = t / trail
                if t == 0:
                    style = G6
                elif ratio < 0.15:
                    style = G5
                elif ratio < 0.35:
                    style = G4
                elif ratio < 0.6:
                    style = G3
                elif ratio < 0.8:
                    style = G2
                else:
                    style = G1
                if dim_col and dy0 <= y < dy1:
                    style = DIM_LUT[style]
                canvas.chars[y][x] = glyphs[y % len(glyphs)]
                canvas.styles[y][x] = style
