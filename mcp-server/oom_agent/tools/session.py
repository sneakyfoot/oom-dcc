"""Session management tool: session(action)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from oom_agent._app import mcp
from oom_agent.context import bootstrap_context
from oom_agent.guardrails import log_error, log_operation, log_success
from oom_agent.logging_config import get_logger
from oom_agent.session_manager import ConnectionMode, get_session_manager

logger = get_logger(__name__)


def _shotgrid_bootstrap_code(
    project: str,
    sequence: str | None,
    shot: str | None,
) -> str:
    """Return Python code to bootstrap ShotGrid context inside hython."""
    return f"""
import hou
import sgtk
import oom_sg_auth
from oom_bootstrap import bootstrap

_project_name = {json.dumps(project)}
_sequence_name = {json.dumps(sequence)}
_shot_name = {json.dumps(shot)}

_user = oom_sg_auth.oom_auth()
_sg = _user.create_sg_connection()
_project = _sg.find_one("Project", [["name", "is", _project_name]], ["id", "tank_name"])
if _project is None:
    raise RuntimeError(f"Project not found: {{_project_name}}")

_engine = sgtk.platform.current_engine()
if _engine is not None:
    _tk = _engine.sgtk
    _sg = _tk.shotgun
else:
    _engine, _tk, _sg = bootstrap(_project)

_sequence = None
if _sequence_name:
    _sequence = _sg.find_one(
        "Sequence",
        [["project", "is", _project], ["code", "is", _sequence_name]],
        ["id", "code"],
    )
    if _sequence is None:
        raise RuntimeError(f"Sequence not found: {{_sequence_name}}")

_shot = None
if _shot_name:
    if _sequence is None:
        raise RuntimeError("Sequence is required when specifying shot")
    _shot = _sg.find_one(
        "Shot",
        [
            ["project", "is", _project],
            ["sg_sequence", "is", _sequence],
            ["code", "is", _shot_name],
        ],
        ["id", "code", "sg_cut_in", "sg_cut_out"],
    )
    if _shot is None:
        raise RuntimeError(f"Shot not found: {{_shot_name}}")

if _shot:
    _context = _tk.context_from_entity("Shot", _shot["id"])
else:
    _context = _tk.context_from_entity("Project", _project["id"])

_engine.change_context(_context)
 hou.session.oom_tk = _tk
hou.session.oom_context = _context
""".strip()


@mcp.tool()
async def session(
    action: str,
    project: str | None = None,
    sequence: str | None = None,
    shot: str | None = None,
    mode: str = "hython",
    host: str = "localhost",
    port: int = 18811,
) -> dict[str, Any]:
    """
    Manage Houdini sessions.

    Args:
        action: "create" — start a new session with ShotGrid context (requires project);
                "destroy" — shut down and clean up the current session;
                "status" — return current session state
        project: ShotGrid project name (required for create)
        sequence: Sequence code (optional, create only)
        shot: Shot code (requires sequence, create only)
        mode: "hython" (spawn headless) or "live" (connect to existing GUI via hrpyc)
        host: hrpyc host for live mode (default: localhost)
        port: hrpyc port for live mode (default: 18811)

    Returns:
        Session state dict; "status" always succeeds even without an active session
    """
    if action == "create":
        if not project:
            return {"success": False, "error": "project is required for action='create'"}
        start_time = time.time()

        try:
            conn_mode = ConnectionMode(mode)
        except ValueError:
            return {
                "success": False,
                "error": f"Invalid mode: {mode!r}; use 'hython' or 'live'",
            }

        try:
            context_info = await asyncio.to_thread(
                bootstrap_context,
                project,
                sequence,
                shot,
            )
            manager = get_session_manager()
            state = await asyncio.to_thread(
                manager.initialize,
                context_info,
                conn_mode,
                host,
                port,
            )

            if conn_mode == ConnectionMode.HYTHON:
                bootstrap_timeout = float(os.environ.get("OOM_BOOTSTRAP_TIMEOUT", "600"))
                bootstrap_result = await manager.execute(
                    _shotgrid_bootstrap_code(project, sequence, shot),
                    timeout=bootstrap_timeout,
                )
                if not bootstrap_result["ok"]:
                    await asyncio.to_thread(manager.shutdown, True)
                    raise RuntimeError(
                        f"Failed to bootstrap context inside hython: "
                        f"{bootstrap_result['stderr'] or 'unknown error'}"
                    )

            duration_ms = int((time.time() - start_time) * 1000)
            log_operation(
                session_id="mcp",
                method="session.create",
                params={"project": project, "sequence": sequence, "shot": shot, "mode": mode},
                status="success",
                duration_ms=duration_ms,
            )
            log_success(session_id="mcp", method="session.create", duration_ms=duration_ms)

            return {
                "success": True,
                "initialized": state.initialized,
                "project": state.project,
                "sequence": state.sequence,
                "shot": state.shot,
                "paths": state.paths,
                "mode": state.mode,
                "worker_pid": state.worker_pid,
            }

        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            log_error(
                session_id="mcp",
                method="session.create",
                error=str(exc),
                duration_ms=duration_ms,
            )
            return {"success": False, "error": str(exc)}

    elif action == "destroy":
        manager = get_session_manager()
        if not manager.is_initialized():
            return {"success": False, "error": "No active session"}
        try:
            success = await asyncio.to_thread(manager.shutdown)
            return {"success": bool(success)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    elif action == "status":
        manager = get_session_manager()
        state = manager.state
        return {
            "initialized": state.initialized,
            "healthy": state.healthy,
            "created_at": state.created_at,
            "project": state.project,
            "sequence": state.sequence,
            "shot": state.shot,
            "paths": state.paths,
            "hip_loaded": state.hip_loaded,
            "hip_path": state.hip_path,
            "mode": state.mode,
            "worker_pid": state.worker_pid,
            "last_error": state.last_error,
        }

    else:
        return {"success": False, "error": f"Unknown action: {action!r}; use 'create', 'destroy', or 'status'"}
