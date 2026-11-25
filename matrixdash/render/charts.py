"""Text charts built only from the glyphs of the console font."""

from __future__ import annotations


def graph_rows(values: list[float], width: int, height: int, vmax: float | None = None) -> list[str]:
    """Multi-row bar graph using only █▒░, top row first."""
    vals = values[-width:]
    vals = [0.0] * (width - len(vals)) + vals
    top = vmax if vmax else max(max(vals, default=0.0), 1e-9)
    rows = []
    for r in range(height - 1, -1, -1):
        line = []
        for v in vals:
            f = max(0.0, v) / top * height - r
            if f >= 0.75:
                line.append("█")
            elif f >= 0.45:
                line.append("▒")
            elif f >= 0.12:
                line.append("░")
            else:
                line.append(" ")
        rows.append("".join(line))
    return rows


def heat_strip(values: list[float], width: int, vmax: float | None = None) -> str:
    vals = values[-width:]
    top = vmax if vmax else max(max(vals, default=0.0), 1e-9)
    out = []
    for v in vals:
        f = max(0.0, v) / top
        out.append("█" if f > 0.75 else "▒" if f > 0.4 else "░" if f > 0.1 else "·")
    return "·" * (width - len(out)) + "".join(out)
