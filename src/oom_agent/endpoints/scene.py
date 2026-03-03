"""
Scene management endpoints for the persistent runtime.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException

from oom_agent.guardrails import (
    log_error,
    log_success,
    post_check_versioning,
    pre_check_runtime,
    pre_check_scene_path,
)
from oom_agent.protocol import register_method
from oom_agent.session_manager import get_session_manager


@register_method("scene.load")
async def scene_load(params: Dict[str, Any]) -> Dict[str, Any]:
    start_time = time.time()
    hip_path = params.get("hip_path")

    if not hip_path:
        raise HTTPException(status_code=400, detail="hip_path is required")
    if not pre_check_runtime():
        raise HTTPException(status_code=404, detail="No active session")
    if not pre_check_scene_path(hip_path):
        raise HTTPException(status_code=400, detail="Invalid hip_path")

    manager = get_session_manager()
    code = f"import hou\nhou.hipFile.load({json.dumps(hip_path)})"

    try:
        result = await manager.execute(code, timeout=60.0)
        if not result["ok"]:
            raise RuntimeError(result["stderr"] or "Failed to load scene")

        manager.set_hip_state(hip_path=hip_path, loaded=True)
        duration_ms = int((time.time() - start_time) * 1000)
        log_success(session_id="server", method="scene.load", duration_ms=duration_ms)
        return {
            "success": True,
            "hip_path": hip_path,
            "loaded": True,
            "stdout": result["stdout"],
        }
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        log_error(
            session_id="server",
            method="scene.load",
            error=str(exc),
            duration_ms=duration_ms,
        )
        raise HTTPException(status_code=500, detail=f"Failed to load scene: {exc}")


@register_method("scene.save")
async def scene_save(params: Dict[str, Any]) -> Dict[str, Any]:
    start_time = time.time()
    if not pre_check_runtime():
        raise HTTPException(status_code=404, detail="No active session")

    manager = get_session_manager()
    state = manager.state
    if not state.hip_loaded:
        raise HTTPException(status_code=400, detail="No scene loaded")

    code = "import hou\nhou.hipFile.saveAndBackup()"
    try:
        result = await manager.execute(code, timeout=60.0)
        if not result["ok"]:
            raise RuntimeError(result["stderr"] or "Failed to save scene")

        post_check_versioning(state.hip_path or "")
        duration_ms = int((time.time() - start_time) * 1000)
        log_success(session_id="server", method="scene.save", duration_ms=duration_ms)
        return {
            "success": True,
            "hip_path": state.hip_path,
            "version": "current",
            "stdout": result["stdout"],
        }
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        log_error(
            session_id="server",
            method="scene.save",
            error=str(exc),
            duration_ms=duration_ms,
        )
        raise HTTPException(status_code=500, detail=f"Failed to save scene: {exc}")


@register_method("scene.get_current")
async def scene_get_current(params: Dict[str, Any]) -> Dict[str, Any]:
    if not pre_check_runtime():
        raise HTTPException(status_code=404, detail="No active session")

    manager = get_session_manager()
    state = manager.state
    return {
        "hip_loaded": state.hip_loaded,
        "hip_path": state.hip_path,
        "project_path": state.paths.get("project_path"),
    }


@register_method("scene.list")
async def scene_list(params: Dict[str, Any]) -> Dict[str, Any]:
    if not pre_check_runtime():
        raise HTTPException(status_code=404, detail="No active session")

    manager = get_session_manager()
    state = manager.state
    shot_path = state.paths.get("shot_path")
    if not shot_path:
        raise HTTPException(
            status_code=400,
            detail="No shot context active; create session with project+sequence+shot",
        )

    shot_root = Path(shot_path)
    tasks_root = shot_root / "tasks"
    if not tasks_root.exists():
        return {
            "shot_path": str(shot_root),
            "tasks_path": str(tasks_root),
            "count": 0,
            "scenes": [],
        }

    scene_files: list[dict[str, Any]] = []
    for extension in ("*.hip", "*.hiplc", "*.hipnc"):
        for hip_file in tasks_root.glob(f"*/houdini/{extension}"):
            if not hip_file.is_file():
                continue

            stat = hip_file.stat()
            scene_files.append(
                {
                    "path": str(hip_file),
                    "name": hip_file.name,
                    "step": hip_file.parent.parent.name,
                    "size_bytes": stat.st_size,
                    "modified_ts": stat.st_mtime,
                }
            )

    scene_files.sort(key=lambda item: float(item["modified_ts"]), reverse=True)
    return {
        "shot_path": str(shot_root),
        "tasks_path": str(tasks_root),
        "count": len(scene_files),
        "scenes": scene_files,
    }
