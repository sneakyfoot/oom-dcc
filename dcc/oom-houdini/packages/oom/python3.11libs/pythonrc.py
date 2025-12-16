import os
import sys
from pathlib import Path


def _add(path: Path):
    if path.exists():
        p = str(path)
        if p not in sys.path:
            sys.path.insert(0, p)


def _repo_root_from_env_or_self() -> Path:
    env_path = os.environ.get("OOM")
    if env_path:
        return Path(env_path)
    # Walk up from this file: .../dcc/oom-houdini/packages/oom/python3.11libs/pythonrc.py
    return Path(__file__).resolve().parents[6]


# Prefer the uv-managed env (matches flake shell defaults).
_default_uv_env = Path.home() / ".cache" / "uv" / "venvs" / "oom-dcc"
uv_env = Path(os.environ.get("UV_PROJECT_ENVIRONMENT", str(_default_uv_env)))
_add(uv_env / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")

# Repo source tree (handy for dev overrides)
repo_root = _repo_root_from_env_or_self()
_add(repo_root / "src")
