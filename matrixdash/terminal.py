"""The local terminal: raw keyboard input, alternate screen, console palette and a login shell."""

from __future__ import annotations

import os
import select
import signal
import subprocess
import sys
import termios
import tty

from .theme import (
    ALT_SCREEN,
    CLEAR,
    HIDE_CURSOR,
    LINUX_PALETTE,
    MAIN_SCREEN,
    RESET,
    SHOW_CURSOR,
    WRAP_OFF,
    WRAP_ON,
)

ARROWS = {"A": "up", "B": "down", "C": "right", "D": "left"}


class Terminal:
    def __init__(self, use_palette: bool):
        # The Linux console only has 16 colors: its palette is reprogrammed with greens while we run.
        self.use_palette = use_palette
        self.old_term = None

    @staticmethod
    def interactive() -> bool:
        return sys.stdin.isatty()

    def setup(self):
        if sys.stdin.isatty():
            try:
                self.old_term = termios.tcgetattr(sys.stdin.fileno())
                tty.setcbreak(sys.stdin.fileno())
            except Exception:
                self.old_term = None
        self.write(ALT_SCREEN + CLEAR + HIDE_CURSOR + WRAP_OFF)
        self.load_palette()

    def load_palette(self):
        """Program the Linux console's 16 colors with the current theme (no-op on other terminals)."""
        if self.use_palette:
            self.write("".join(f"\x1b]P{n:X}{rgb}" for n, rgb in LINUX_PALETTE.items()))

    def restore(self):
        if self.old_term is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.old_term)
            except Exception:
                pass
        out = [RESET, WRAP_ON, SHOW_CURSOR]
        if self.use_palette:
            out.append("\x1b]R")
        out.append(MAIN_SCREEN)
        self.write("".join(out))

    @staticmethod
    def write(data: str):
        sys.stdout.write(data)
        sys.stdout.flush()

    def keys(self):
        """Keys typed since the last call, decoded: letters, 'enter', 'esc', 'backspace', arrows."""
        if not sys.stdin.isatty():
            return
        fd = sys.stdin.fileno()
        while select.select([fd], [], [], 0)[0]:
            data = os.read(fd, 64).decode("utf-8", errors="ignore")
            i = 0
            while i < len(data):
                ch = data[i]
                if ch == "\x1b":
                    if i == len(data) - 1 and select.select([fd], [], [], 0.03)[0]:
                        data += os.read(fd, 64).decode("utf-8", errors="ignore")
                    # Arrow/function keys arrive as escape sequences.
                    j = i + 1
                    if j < len(data) and data[j] in "[O":
                        j += 1
                        while j < len(data) and not data[j].isalpha() and data[j] != "~":
                            j += 1
                        final = data[j] if j < len(data) else ""
                        j += 1
                        yield ARROWS.get(final, "")
                    else:
                        yield "esc"
                    i = j
                    continue
                if ch in ("\r", "\n"):
                    yield "enter"
                elif ch in ("\x7f", "\x08"):
                    yield "backspace"
                else:
                    yield ch
                i += 1

    def shell(self):
        """Hand the console to a login shell until it exits. Raises OSError when the shell cannot start."""
        self.restore()
        self.write("\x1b[2J\x1b[H\x1b[32m== TERMINAL · digite exit (ou Ctrl+D) para voltar ao painel ==\x1b[0m\n\n")
        shell = os.environ.get("SHELL") or "/bin/bash"
        try:
            subprocess.call([shell, "-l"], cwd=os.path.expanduser("~"),
                            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        finally:
            self.setup()
