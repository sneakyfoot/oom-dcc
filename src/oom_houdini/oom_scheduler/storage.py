import os
from pathlib import Path


def ensure_dirs(cook_id: str):
    hip = os.environ.get("HIP", "").strip()
    dir_name = f"pdgtemp_{cook_id}"
    base = os.path.join(hip, dir_name)
    scripts = os.path.join(base, "scripts")
    Path(base).mkdir(parents=True, exist_ok=True)
    Path(scripts).mkdir(parents=True, exist_ok=True)
    return base, scripts
