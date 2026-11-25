"""Small JSON files written atomically (config, state, snapshot export)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any, indent: int | None = None, **dump_kw: Any):
    """Write to <path>.tmp and rename, so readers never see half a file. Indented files end with a newline."""
    text = json.dumps(data, indent=indent, ensure_ascii=False, **dump_kw)
    if indent:
        text += "\n"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        # Keep the permissions of the file being replaced (config.json may hold tokens: chmod 600).
        os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
    except OSError:
        pass
    os.replace(tmp, path)
