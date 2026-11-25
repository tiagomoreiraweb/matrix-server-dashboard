"""Colors, terminal escape codes and glyph tables."""

from __future__ import annotations

RESET = "\x1b[0m"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
ALT_SCREEN = "\x1b[?1049h"
MAIN_SCREEN = "\x1b[?1049l"
CLEAR = "\x1b[2J"
WRAP_OFF = "\x1b[?7l"
WRAP_ON = "\x1b[?7h"

# Style ids. G0..G6 is the theme's main ramp, from almost black to the palest tone
# (green in the "matrix" theme). RED and AMBER are alerts, CYAN the accent color.
NONE, G0, G1, G2, G3, G4, G5, G6, RED, AMBER, CYAN, TEXT, WHITE, KEYCAP, KEYCAP_RED = range(15)
GREENS = (G0, G1, G2, G3, G4, G5, G6)

# --------------------------------------------------------------------- themes
#
# A theme gives an RGB color to each role. From it come the three outputs:
#   LINUX_PALETTE  the 16 colors reprogrammed on the Linux console (tty1), also used by the web page
#   SGR_256        xterm 256-color codes for SSH terminals
#   SGR_LINUX      fixed: which of the 16 console slots each style uses
# The dicts are changed in place by apply(), so modules that imported them see the new colors.

ROLES = ("g0", "g1", "g2", "g3", "g4", "g5", "g6", "text", "accent", "red", "amber", "red_bg", "white")

THEMES: dict[str, dict[str, str]] = {
    "matrix": {"g0": "06240f", "g1": "005a1e", "g2": "00902e", "g3": "00c040", "g4": "1fdc58", "g5": "39ff6a",
               "g6": "c6ffd2", "text": "9ec99e", "accent": "00e0ff", "red": "ff5f5f", "amber": "ffaf00",
               "red_bg": "ff3b3b", "white": "ffffff"},
    "ambar": {"g0": "2a1600", "g1": "5c3000", "g2": "8f4c00", "g3": "c26a00", "g4": "e68a00", "g5": "ffb000",
              "g6": "ffe2a8", "text": "e0b27a", "accent": "7fd4ff", "red": "ff5f5f", "amber": "fff07a",
              "red_bg": "e0302a", "white": "fff8ea"},
    "gelo": {"g0": "04172a", "g1": "0a3a66", "g2": "0f5ea3", "g3": "1f86d6", "g4": "3aa8f5", "g5": "6cc8ff",
             "g6": "d6f0ff", "text": "9fc3dd", "accent": "c792ff", "red": "ff5f5f", "amber": "ffaf00",
             "red_bg": "e0302a", "white": "ffffff"},
    "synthwave": {"g0": "1f0a2e", "g1": "4a1468", "g2": "7a1fa2", "g3": "b026d4", "g4": "d94cf0", "g5": "ff6ef5",
                  "g6": "ffd1fb", "text": "d3a6e0", "accent": "00e5ff", "red": "ff4d6d", "amber": "ffb347",
                  "red_bg": "e0204a", "white": "ffffff"},
    "mono": {"g0": "1c1c1c", "g1": "3a3a3a", "g2": "5e5e5e", "g3": "8a8a8a", "g4": "b0b0b0", "g5": "d6d6d6",
             "g6": "ffffff", "text": "bcbcbc", "accent": "5fd7ff", "red": "ff5f5f", "amber": "ffaf00",
             "red_bg": "d03030", "white": "ffffff"},
}
THEME_LABELS = {"matrix": "MATRIX (verde)", "ambar": "ÂMBAR (monitor antigo)", "gelo": "GELO (azul)",
                "synthwave": "SYNTHWAVE (magenta)", "mono": "MONO (cinza)"}
DEFAULT_THEME = "matrix"

# Console slot used by each role (see SGR_LINUX).
SLOTS = {"g3": 2, "amber": 3, "g1": 4, "g2": 5, "accent": 6, "text": 7, "g0": 8, "red": 9, "g5": 10,
         "g6": 12, "g4": 13, "white": 15, "red_bg": 1}

# The classic green theme keeps its hand-picked 256-color codes.
MATRIX_SGR_256 = {
    NONE: "0", G0: "38;5;22", G1: "38;5;28", G2: "38;5;34", G3: "38;5;40",
    G4: "38;5;46", G5: "38;5;83", G6: "38;5;157",
    RED: "38;5;196", AMBER: "38;5;214", CYAN: "38;5;51", TEXT: "38;5;151", WHITE: "38;5;231",
    KEYCAP: "38;5;16;48;5;40", KEYCAP_RED: "38;5;231;48;5;160",
}

SGR_256: dict[int, str] = dict(MATRIX_SGR_256)

# The Linux console only has 16 colors, so its palette is reprogrammed
# (OSC P) with the theme and the styles are mapped onto those slots.
# Every SGR starts with 0 because bright colors on the console set the bold
# attribute, which would otherwise leak into the next color.
LINUX_PALETTE: dict[int, str] = {
    0: "000000", 1: "ff3b3b", 2: "00c040", 3: "ffaf00",
    4: "005a1e", 5: "00902e", 6: "00e0ff", 7: "9ec99e",
    8: "06240f", 9: "ff5f5f", 10: "39ff6a", 11: "ffd75f",
    12: "c6ffd2", 13: "1fdc58", 14: "8cffff", 15: "ffffff",
}
SGR_LINUX = {
    NONE: "0", G0: "90", G1: "34", G2: "35", G3: "32", G4: "95", G5: "92", G6: "94",
    RED: "91", AMBER: "33", CYAN: "36", TEXT: "37", WHITE: "97",
    KEYCAP: "30;42", KEYCAP_RED: "97;41",
}

_CUBE = (0, 95, 135, 175, 215, 255)


def xterm256(rgb: str) -> int:
    """Nearest xterm-256 color (6x6x6 cube or gray ramp) to a 'rrggbb' color."""
    r, g, b = (int(rgb[i:i + 2], 16) for i in (0, 2, 4))

    def near(v: int) -> int:
        return min(range(6), key=lambda i: abs(_CUBE[i] - v))

    ci = (near(r), near(g), near(b))
    cube = (_CUBE[ci[0]], _CUBE[ci[1]], _CUBE[ci[2]])
    gray_i = max(0, min(23, round((((r + g + b) / 3) - 8) / 10)))
    gray = 8 + gray_i * 10

    def dist(c: tuple[int, int, int]) -> int:
        return (c[0] - r) ** 2 + (c[1] - g) ** 2 + (c[2] - b) ** 2

    if dist((gray, gray, gray)) < dist(cube):
        return 232 + gray_i
    return 16 + 36 * ci[0] + 6 * ci[1] + ci[2]


def colors(name: str, overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Role -> 'rrggbb' of a theme, with valid overrides ({"accent": "#ff00ff"}) on top."""
    base = dict(THEMES.get(name) or THEMES[DEFAULT_THEME])
    for role, value in (overrides or {}).items():
        value = str(value).lstrip("#").lower()
        if role in ROLES and len(value) == 6 and all(ch in "0123456789abcdef" for ch in value):
            base[role] = value
    return base


def apply(name: str = DEFAULT_THEME, overrides: dict[str, str] | None = None) -> str:
    """Switch every color table to a theme; returns the name actually used."""
    name = name if name in THEMES else DEFAULT_THEME
    c = colors(name, overrides)
    for role, slot in SLOTS.items():
        LINUX_PALETTE[slot] = c[role]
    if name == DEFAULT_THEME and not overrides:
        SGR_256.update(MATRIX_SGR_256)
        return name
    code = {role: xterm256(c[role]) for role in ROLES}
    SGR_256.update({
        G0: f"38;5;{code['g0']}", G1: f"38;5;{code['g1']}", G2: f"38;5;{code['g2']}", G3: f"38;5;{code['g3']}",
        G4: f"38;5;{code['g4']}", G5: f"38;5;{code['g5']}", G6: f"38;5;{code['g6']}",
        RED: f"38;5;{code['red']}", AMBER: f"38;5;{code['amber']}", CYAN: f"38;5;{code['accent']}",
        TEXT: f"38;5;{code['text']}", WHITE: f"38;5;{code['white']}",
        KEYCAP: f"38;5;16;48;5;{code['g3']}", KEYCAP_RED: f"38;5;231;48;5;{code['red_bg']}",
    })
    return name

# Rain glyphs dimmed when they fall behind the portrait (indexed by style id).
DIM_LUT = [NONE, G0, G0, G0, G1, G1, G1, G2, G1, G1, G1, G1, G2, G1, G1]

MATRIX_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ$+-*/=%#&<>[]{}|:;~^¦§¤¥£ÆØÞßµ"
GLITCH_CHARS = "01#$%@&*<>/\\|=+"
SCRAMBLE_CHARS = "0123456789ABCDEF#$%&*+=<>"
BORDER_CHARS = set("─│╭╮╰╯═║╔╗╚╝┄")
SPINNER = "-\\|/"

DAYS_PT = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]
MONTHS_PT = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]

BIG_DIGITS = {
    "0": ("┏━┓", "┃ ┃", "┗━┛"),
    "1": ("╺┓ ", " ┃ ", "╺┻╸"),
    "2": ("╺━┓", "┏━┛", "┗━╸"),
    "3": ("╺━┓", " ━┫", "╺━┛"),
    "4": ("╻ ╻", "┗━┫", "  ╹"),
    "5": ("┏━╸", "┗━┓", "╺━┛"),
    "6": ("┏━╸", "┣━┓", "┗━┛"),
    "7": ("╺━┓", "  ┃", "  ╹"),
    "8": ("┏━┓", "┣━┫", "┗━┛"),
    "9": ("┏━┓", "┗━┫", "╺━┛"),
}
