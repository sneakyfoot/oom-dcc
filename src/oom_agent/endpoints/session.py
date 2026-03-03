"""
Runtime session endpoints.
Single session per server instance.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict

from fastapi import HTTPException

from oom_agent.context import bootstrap_context
from oom_agent.guardrails import log_error, log_operation, log_success
from oom_agent.protocol import register_method
from oom_agent.session_manager import get_session_manager


def _build_hython_context_bootstrap_code(
    project: str,
    sequence: str | None,
    shot: str | None,
) -> str:
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


@register_method("agent.create_session")
async def create_session(params: Dict[str, Any]) -> Dict[str, Any]:
    start_time = time.time()
    project = params.get("project")
    sequence = params.get("sequence")
    shot = params.get("shot")

    if not project:
        raise HTTPException(status_code=400, detail="project is required")

    manager = get_session_manager()
    if manager.is_initialized():
        raise HTTPException(
            status_code=409,
            detail="Session already active; call agent.destroy_session first",
        )

    try:
        context_info = await asyncio.to_thread(
            bootstrap_context,
            project,
            sequence,
            shot,
        )
        state = await asyncio.to_thread(manager.initialize, context_info)

        bootstrap_code = _build_hython_context_bootstrap_code(
            project=project,
            sequence=sequence,
            shot=shot,
        )
        bootstrap_result = await manager.execute(bootstrap_code, timeout=120.0)
        if not bootstrap_result["ok"]:
            await asyncio.to_thread(manager.shutdown, True)
            raise RuntimeError(
                "Failed to bootstrap context inside hython: "
                f"{bootstrap_result['stderr'] or 'unknown error'}"
            )

        duration_ms = int((time.time() - start_time) * 1000)

        log_operation(
            session_id="server",
            method="agent.create_session",
            params={"project": project, "sequence": sequence, "shot": shot},
            status="success",
            duration_ms=duration_ms,
        )
        log_success(
            session_id="server", method="agent.create_session", duration_ms=duration_ms
        )

        return {
            "initialized": state.initialized,
            "project": state.project,
            "sequence": state.sequence,
            "shot": state.shot,
            "paths": state.paths,
            "worker_pid": state.worker_pid,
        }
    except HTTPException:
        raise
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        log_error(
            session_id="server",
            method="agent.create_session",
            error=str(exc),
            duration_ms=duration_ms,
        )
        raise HTTPException(status_code=500, detail=f"Failed to create session: {exc}")


@register_method("agent.destroy_session")
async def destroy_session(params: Dict[str, Any]) -> Dict[str, bool]:
    manager = get_session_manager()
    if not manager.is_initialized():
        raise HTTPException(status_code=404, detail="No active session")

    try:
        success = await asyncio.to_thread(manager.shutdown)
        return {"success": bool(success)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to destroy session: {exc}")


@register_method("agent.get_status")
async def get_status(params: Dict[str, Any]) -> Dict[str, Any]:
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
        "worker_pid": state.worker_pid,
        "last_error": state.last_error,
    }
