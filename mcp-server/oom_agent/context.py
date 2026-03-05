"""
Oom context bootstrap helpers — delegates to OOM_PYTHON subprocess.

Calls oom_context.main() via the python311 binary (OOM_PYTHON env var), which
bootstraps sgtk and writes /tmp/oom.env. The MCP server process (python313)
never imports sgtk or oom_bootstrap directly.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Optional


def bootstrap_context(
    project_name: str,
    sequence_name: Optional[str] = None,
    shot_name: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve SG/TK context via OOM_PYTHON subprocess and return runtime env metadata."""
    oom_python = os.environ.get("OOM_PYTHON")
    oom_pythonpath = os.environ.get("OOM_PYTHONPATH")
    if not oom_python or not oom_pythonpath:
        raise RuntimeError("OOM_PYTHON and OOM_PYTHONPATH must be set")

    # oom_context.parse_args supports 1 arg (project) or 3 args (project seq shot)
    inline = "from oom_context import main; main()"
    if sequence_name and shot_name:
        cmd = [oom_python, "-c", inline, project_name, sequence_name, shot_name]
    else:
        cmd = [oom_python, "-c", inline, project_name]

    env = os.environ.copy()
    env["PYTHONPATH"] = oom_pythonpath

    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"oom_context failed: {result.stderr}")

    # Parse /tmp/oom.env (lines like: export KEY="value")
    env_vars: dict[str, str] = {}
    env_file = Path("/tmp/oom.env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("export "):
                key, _, value = line[7:].partition("=")
                env_vars[key.strip()] = value.strip().strip('"')

    paths: dict[str, str] = {}
    if "OOM_PROJECT_PATH" in env_vars:
        paths["project_path"] = env_vars["OOM_PROJECT_PATH"]
    if "OOM_SHOT_PATH" in env_vars:
        paths["shot_path"] = env_vars["OOM_SHOT_PATH"]

    return {
        "project": project_name,
        "sequence": sequence_name,
        "shot": shot_name,
        "paths": paths,
        "env_vars": env_vars,
    }
