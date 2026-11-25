"""Running external commands."""

from __future__ import annotations

import subprocess


def run_cmd(args: list[str], timeout: float = 2.0, strip: bool = True) -> tuple[int, str]:
    """(exit code, stdout) of a command; (1, "") when it cannot run or times out. stderr is dropped."""
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout.strip() if strip else result.stdout
    except Exception:
        return 1, ""
