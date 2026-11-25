#!/usr/bin/env python3
"""
Matrix Server Dashboard
Terminal dashboard for a Linux server's local monitor (tty1), SSH or browser, with:
- Animated boot sequence and wipe transition into the dashboard
- Matrix rain background that also falls behind the portrait
- ASCII portrait shaded by character density, with decode reveal,
  scan band, shimmer and glitch bursts
- CPU (total, per core, history), RAM, swap, temperature, load, disks
- Every container: state, uptime, health, CPU/MEM, HTTP endpoint probe
- Host systemd units
- Claude Code agent (when installed): processes, sessions, remote-control, version, CPU/MEM
- Auto-discovery of disks, host services, containers and their endpoints (matrixdash/autodetect.py)
- Network throughput graphs and latency
- Live event console with typing effect
- Data collection in background threads and diff-based rendering

Only glyphs present in the console font (Uni2-Fixed16) are used.
Keyboard shortcuts (H shows them on screen): C settings menu, W network map, X terminal,
N speed test, E eco mode, T screen off, M rain, I portrait, G glitch, L redraw,
D power off, R reboot, Q quit. D, R and Q ask for confirmation.

The code lives in the matrixdash package; this file is the entry point used by
run.sh, the systemd service and the installer.
"""

from matrixdash.cli import main

if __name__ == "__main__":
    main()
