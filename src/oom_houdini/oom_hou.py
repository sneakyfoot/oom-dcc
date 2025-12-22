"""
Ensures that Houdini's Python API (hou module) is available for import
in external Python scripts by configuring the Houdini installation paths.
"""

import sys
import os
from pathlib import Path

# --- Legacy custom Houdini env configuration commented out. ---
# # Allow legacy HOUDINI_PACKAGE_DIR to drive Houdini packages (maps to HOUDINI_PACKAGE_PATH)
# package_dir = os.environ.get("HOUDINI_PACKAGE_DIR")
# if package_dir:
#     existing = os.environ.get("HOUDINI_PACKAGE_PATH", "")
#     # Prepend so the legacy package directory takes precedence
#     os.environ["HOUDINI_PACKAGE_PATH"] = (
#         package_dir + os.pathsep + existing if existing else package_dir
#     )
#
# # Path to the Houdini installation (HFS). Can be overridden by the HFS env var.
# DEFAULT_HFS = Path(os.environ.get("HFS", "/mnt/RAID/Assets/HQ/houdini_distros/hfs.linux-x86_64"))
#
# # Determine the Houdini Python libraries directory for the current Python version.
# python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
# HOUDINI_PYTHON_LIB = DEFAULT_HFS / "houdini" / f"python{python_version}libs"
#
# # Avoid duplicate inserts.
# if str(HOUDINI_PYTHON_LIB) not in sys.path:
#     # Prepend so it takes precedence over system-wide installations.
#     sys.path.insert(0, str(HOUDINI_PYTHON_LIB))
#
# # Fail fast if the path is missing (e.g., Houdini not installed or misconfigured).
# if not HOUDINI_PYTHON_LIB.exists():
#     raise RuntimeError(f"Houdini python libraries not found at {HOUDINI_PYTHON_LIB}")
#
# ## Ensure HFS is set so Houdini knows its install location.
# os.environ.setdefault("HFS", str(DEFAULT_HFS))
# # Suppress jemalloc test warnings in Houdini.
# os.environ.setdefault("HOUDINI_DISABLE_JEMALLOCTEST", "1")
# # For PDG localscheduler: set HH and HHP to mimic houdini_setup_bash
# os.environ.setdefault("HH", str(DEFAULT_HFS / "houdini"))
# os.environ.setdefault("HHP", str(HOUDINI_PYTHON_LIB))

# --- Official Houdini setup via houdini_setup.sh ---
import subprocess


def _capture_houdini_env(hfs_path: str) -> None:
    """Source houdini_setup.sh and import all resulting env vars into os.environ."""
    # Change to HFS root so houdini_setup_bash correctly detects its install directory
    bash_cmd = ["bash", "-lc", f"cd {hfs_path} && source houdini_setup_bash && env -0"]
    out = subprocess.check_output(bash_cmd)
    for kv in out.split(b"\0"):
        if not kv:
            continue
        key, val = kv.split(b"=", 1)
        os.environ[key.decode()] = val.decode()


# Determine HFS root (fall back to default if necessary)
_default_hfs = os.environ.get(
    "HFS", "/mnt/RAID/Assets/HQ/houdini_distros/hfs.linux-x86_64"
)
os.environ.setdefault("HFS", _default_hfs)

# Source the official Houdini setup and import resulting env
_setup_script = Path(os.environ["HFS"]) / "houdini_setup_bash"
if not _setup_script.exists():
    raise RuntimeError(f"Houdini setup script not found at {_setup_script}")
try:
    _capture_houdini_env(os.environ["HFS"])
except subprocess.CalledProcessError as _err:
    raise RuntimeError(
        f"Failed to source houdini_setup from HFS={os.environ['HFS']}: {_err}"
    ) from _err

# Insert Houdini's Python libraries directory (HHP) into sys.path for importing hou
_houdini_py_lib = os.environ.get("HHP")
if _houdini_py_lib and _houdini_py_lib not in sys.path:
    sys.path.insert(0, _houdini_py_lib)

# Update sys.path from PYTHONPATH so that additional hou-related libs are on the path
for _path in os.environ.get("PYTHONPATH", "").split(os.pathsep):
    if _path and _path not in sys.path:
        sys.path.insert(0, _path)
