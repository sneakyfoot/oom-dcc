# oom_sg_auth.py
"""
Make sure tk-core is on sys.path for ShotGrid bootstrap.

Prefers env overrides (OOM_SGTK_CORE or SGTK_CORE_PATH); falls back to the
legacy /mnt/RAID path for compatibility.
"""

import os
import sys
from pathlib import Path


def _resolve_core_path() -> Path:
    env_path = (
        os.environ.get("SGTK_PATH")
        or "/mnt/RAID/Assets/shotgun/tk-core/python"
    )
    return Path(env_path)


CORE_PATH = _resolve_core_path()

# Avoid duplicate inserts
if str(CORE_PATH) not in sys.path:
    # Prepend so it wins over any system‑wide install
    sys.path.insert(0, str(CORE_PATH))

# Optional: fail fast if the path is missing (farm node mis‑mount etc.)
if not CORE_PATH.exists():
    raise RuntimeError(f"ShotGrid tk‑core not found at {CORE_PATH}")
