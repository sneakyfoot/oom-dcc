"""
Oom context bootstrap helpers for agent runtime initialization.
"""

from __future__ import annotations

import os
import socket
from typing import Any, Optional

import oom_sg_auth
import sgtk
from oom_bootstrap import bootstrap


def _configure_environment() -> None:
    hostname = socket.gethostname()
    os.environ["SHOTGUN_HOME"] = os.path.expanduser(f"~/.shotgun-{hostname}")
    ssl_cert = (
        os.environ.get("SSL_CERT_FILE")
        or os.environ.get("OOM_SSL_CERT_FILE")
        or "/mnt/RAID/Assets/shotgun/certs/cacert.pem"
    )
    os.environ["SSL_CERT_FILE"] = ssl_cert


def _resolve_project_path(
    tk_instance: Any, project_entity: dict[str, Any]
) -> Optional[str]:
    tank_name = (project_entity.get("tank_name") or "").strip()
    if not tank_name:
        return None

    data_roots = tk_instance.pipeline_configuration.get_data_roots() or {}
    for root_path in data_roots.values():
        if not root_path:
            continue

        normalized = os.path.normpath(root_path)
        if os.path.basename(normalized) == tank_name:
            return normalized

        candidate = os.path.join(normalized, tank_name)
        if os.path.isdir(candidate):
            return candidate
        return candidate

    return None


def bootstrap_context(
    project_name: str,
    sequence_name: Optional[str] = None,
    shot_name: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve SG/TK context and return runtime environment metadata."""
    _configure_environment()

    user = oom_sg_auth.oom_auth()
    sg = user.create_sg_connection()

    project = sg.find_one(
        "Project", [["name", "is", project_name]], ["id", "tank_name"]
    )
    if project is None:
        raise ValueError(f"Project not found: {project_name}")

    engine = sgtk.platform.current_engine()
    if engine is not None:
        tk = engine.sgtk
        sg = tk.shotgun
    else:
        try:
            engine, tk, sg = bootstrap(project)
        except Exception as exc:
            if "already running" not in str(exc).lower():
                raise
            engine = sgtk.platform.current_engine()
            if engine is None:
                raise
            tk = engine.sgtk
            sg = tk.shotgun

    sequence = None
    if sequence_name:
        sequence = sg.find_one(
            "Sequence",
            [["project", "is", project], ["code", "is", sequence_name]],
            ["id", "code"],
        )
        if sequence is None:
            raise ValueError(f"Sequence not found: {sequence_name}")

    shot = None
    if shot_name:
        if sequence is None:
            raise ValueError("Sequence is required when specifying shot")

        shot = sg.find_one(
            "Shot",
            [
                ["project", "is", project],
                ["sg_sequence", "is", sequence],
                ["code", "is", shot_name],
            ],
            ["id", "code", "sg_cut_in", "sg_cut_out"],
        )
        if shot is None:
            raise ValueError(f"Shot not found: {shot_name}")

    if shot:
        context = tk.context_from_entity("Shot", shot["id"])
    else:
        context = tk.context_from_entity("Project", project["id"])
    engine.change_context(context)

    tk.synchronize_filesystem_structure()
    if shot:
        tk.create_filesystem_structure("Shot", shot["id"])
    else:
        tk.create_filesystem_structure("Project", project["id"])

    project_path = _resolve_project_path(tk, project)
    shot_path = None
    if shot:
        template = tk.templates.get("shot_dir")
        if template:
            shot_path = template.apply_fields(
                {
                    "Project": project_name,
                    "Sequence": sequence_name,
                    "Shot": shot_name,
                }
            )

    paths: dict[str, str] = {"project_path": project_path or ""}
    if shot_path:
        paths["shot_path"] = shot_path

    env_vars: dict[str, str] = {
        "OOM_PROJECT_ID": str(project["id"]),
        "OOM_PROJECT_PATH": project_path or "",
    }
    if sequence:
        env_vars["OOM_SEQUENCE_ID"] = str(sequence["id"])
    if shot:
        env_vars["OOM_SHOT_ID"] = str(shot["id"])
        if shot_path:
            env_vars["OOM_SHOT_PATH"] = shot_path
        cut_in = shot.get("sg_cut_in")
        cut_out = shot.get("sg_cut_out")
        if cut_in is not None and cut_out is not None:
            env_vars["CUT_IN"] = str(cut_in)
            env_vars["CUT_OUT"] = str(cut_out)

    for key, value in env_vars.items():
        if value:
            os.environ[key] = value

    return {
        "project": project_name,
        "sequence": sequence_name,
        "shot": shot_name,
        "paths": {k: v for k, v in paths.items() if v},
        "env_vars": {k: v for k, v in env_vars.items() if v},
    }
