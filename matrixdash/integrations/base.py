"""Optional features (Claude Code, backup, iCloud, Tailscale...) behind one interface.

An integration owns everything about its feature: collecting data in the
collector threads, putting it in the Snapshot, the events it emits, header
alerts and ticker items, boot lines, hotkeys and their actions, and its section
of the settings menu. When it is not configured, `enabled()` is False and none
of that shows up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models import Snapshot

if TYPE_CHECKING:
    from ..collector import Collector
    from ..dashboard import Dashboard
    from ..settings_menu import MenuBuilder


class Integration:
    #: short id, also the Snapshot field it fills
    key = ""
    #: hotkeys it owns (shown, and handled, only while enabled)
    hotkeys: tuple[str, ...] = ()

    def __init__(self, collector: Collector):
        self.collector = collector
        self.config: dict[str, Any] = collector.config

    def enabled(self) -> bool:
        return False

    def emit(self, tag: str, text: str, style: int):
        self.collector.emit(tag, text, style)

    # --- collection (collector threads)

    def prime(self):
        """First read, before the dashboard starts."""

    def collect_fast(self, tick: int):
        """Called every second by the fast loop."""

    def collect_slow(self):
        """Called every ~12 s by the slow loop."""

    def fill(self, s: Snapshot):
        """Copy the latest data into a new snapshot."""

    def detect_events(self, s: Snapshot):
        """Compare with the previous snapshot and emit console events."""

    def probe_lines(self, s: Snapshot) -> list[str]:
        """Extra lines for the periodic PROBE event."""
        return []

    # --- screen (render thread)

    def status_items(self, s: Snapshot) -> list[str]:
        """Header ticker items shown before the link latency."""
        return []

    def ticker(self, s: Snapshot) -> list[str]:
        """Header ticker items shown after the link latency."""
        return []

    def alerts(self, s: Snapshot) -> list[str]:
        """Red header alerts."""
        return []

    def unit_view(self, unit: str, s: Snapshot) -> tuple[bool, str, int, str, int] | None:
        """How the HOST row of one of its systemd units looks when the unit is active:
        (ok, state label, state style, detail, detail style). None = plain unit row."""
        return None

    def boot_lines(self, s: Snapshot) -> list[tuple[str, str]]:
        """(OK | WARN | FAIL | SYS, text) lines of the boot sequence."""
        return []

    def key_label(self, key: str, s: Snapshot, dash: Dashboard) -> str | None:
        """Label of one of its hotkeys in the key bar, when it depends on the state."""
        return None

    def handle_key(self, key: str, dash: Dashboard) -> bool:
        """Run a hotkey; True when it was one of ours."""
        return False

    def menu(self, menu: MenuBuilder):
        """Add its section to the settings menu."""

    def menu_load(self, values: dict[str, str]):
        """Fill the editable values of its menu section."""
