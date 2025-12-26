import ast
import os
import subprocess
import sys
import time

import hou

from oom_houdini import cook_top

hip_path = hou.hipFile.path()
try:
    node_path = hou.selectedNodes()[0].path()
except Exception:
    hou.ui.displayMessage("No TOP node was selected.")
    sys.exit()


def _pick_python_bin():
    """Pick facility python using env var or standard PVC mount, else current."""

    candidates = [
        os.environ.get("OOM_VENV"),
        os.environ.get("UV_PROJECT_ENVIRONMENT"),
        "/var/uv/venvs/oom-dcc",
    ]

    for base in candidates:
        if not base:
            continue
        base = base.strip()
        candidate = os.path.join(base, "bin", "python")
        if os.path.exists(candidate):
            return candidate

    # fallback to current interpreter
    return sys.executable


def submit_controller_job(hip: str, node: str):
    """Submit a headless PDG cook as a Kubernetes controller Job.

    Uses the facility venv Python if available; falls back to the
    current interpreter. Returns (success_bool, message_str).
    """
    # Try in-process submit using current Houdini Python
    try:
        from oom_houdini.submit_pdg_cook import submit_controller_job as _do_submit

        ok, msg = _do_submit(hip, node)
        return ok, msg
    except ImportError as e:
        # Fall back to facility python if deps (e.g. kubernetes) are missing
        python_bin = _pick_python_bin()
        cmd = [
            python_bin,
            "-m",
            "oom_houdini.submit_pdg_cook",
            "--hip",
            hip,
            "--node",
            node,
        ]
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            return True, out.strip()
        except subprocess.CalledProcessError as e2:
            return False, e2.output.strip() if e2.output else str(e2)


def cook_in_session(node_path):
    """Cook the TOP node inside the running Houdini session via core module."""

    try:
        # Delegate full pre-update logic and cook to core wrapper
        cook_top.agent_cook(node_path)
    except Exception as e:
        hou.ui.displayMessage(f"Failed to cook in session: {e}")


choice = hou.ui.displayMessage(
    "Cook TOP network?",
    buttons=("Headless (Farm)", "In Session", "Cancel"),
    default_choice=0,
    close_choice=2,
)

# headless farm cook (controller Job)
if choice == 0:
    # Run pre-update and save via core helpers
    upstream_nodes = cook_top.find_all_upstream_nodes(node_path)
    cook_top.pre_update_cache(upstream_nodes)
    hou.hipFile.saveAndBackup()

    ok, msg = submit_controller_job(hip_path, node_path)
    if ok:
        print(f"[oom] {msg}")
        hou.ui.displayMessage(f"{msg}")
    else:
        print(f"[oom] Controller submit failed:\n{msg}")
        hou.ui.displayMessage(f"Controller submit failed:\n{msg}")

# live cook
elif choice == 1:
    # agent_cook handles pre-update and save internally
    cook_in_session(node_path)

    hou.ui.displayMessage("TOP network submitted")
