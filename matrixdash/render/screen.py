"""Diff-based terminal output."""

from __future__ import annotations

from ..theme import CLEAR, G3, RESET
from .canvas import Canvas


class Screen:
    """Turns canvases into terminal output, sending only the cells that changed."""

    def __init__(self, sgr: dict[int, str]):
        self.sgr = {k: f"\x1b[{v}m" if v == "0" else f"\x1b[0;{v}m" for k, v in sgr.items()}
        self.prev: Canvas | None = None

    def invalidate(self):
        self.prev = None

    def plain(self, c: Canvas) -> str:
        out = []
        for y in range(c.h):
            cur = None
            for ch, st in zip(c.chars[y], c.styles[y]):
                if st != cur:
                    out.append(self.sgr.get(st, self.sgr[G3]))
                    cur = st
                out.append(ch)
            out.append(RESET)
            if y < c.h - 1:
                out.append("\n")
        return "".join(out)

    def frame(self, c: Canvas) -> str:
        prev = self.prev
        self.prev = c
        if prev is None or prev.w != c.w or prev.h != c.h:
            out = [RESET, CLEAR]
            for y in range(c.h):
                out.append(f"\x1b[{y + 1};1H")
                cur = None
                for ch, st in zip(c.chars[y], c.styles[y]):
                    if st != cur:
                        out.append(self.sgr.get(st, self.sgr[G3]))
                        cur = st
                    out.append(ch)
            return "".join(out)

        out = []
        cur = None
        sgr = self.sgr
        for y in range(c.h):
            rc, rs = c.chars[y], c.styles[y]
            pc, ps = prev.chars[y], prev.styles[y]
            if rc == pc and rs == ps:
                continue
            changed = [i for i, (a, b, sa, sb) in enumerate(zip(rc, pc, rs, ps)) if a != b or sa != sb]
            runs = []
            start = end = changed[0]
            for i in changed[1:]:
                if i - end > 5:
                    runs.append((start, end))
                    start = i
                end = i
            runs.append((start, end))
            for start, end in runs:
                out.append(f"\x1b[{y + 1};{start + 1}H")
                for i in range(start, end + 1):
                    st = rs[i]
                    if st != cur:
                        out.append(sgr.get(st, sgr[G3]))
                        cur = st
                    out.append(rc[i])
        return "".join(out)
