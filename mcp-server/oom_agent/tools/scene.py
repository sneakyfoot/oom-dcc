"""Scene operation tool: scene(action)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from oom_agent._app import mcp
from oom_agent.guardrails import (
    log_error,
    log_success,
    post_check_versioning,
    pre_check_scene_path,
)
from oom_agent.logging_config import get_logger
from oom_agent.session_manager import get_session_manager
from oom_agent.tools._helpers import remote_exec, require_session

logger = get_logger(__name__)


async def _scene_load(hip_path: str) -> dict[str, Any]:
    start_time = time.time()
    if not pre_check_scene_path(hip_path):
        return {"success": False, "error": f"Invalid hip_path: {hip_path}"}
    manager = get_session_manager()
    try:
        hou = manager.get_hou()
        await asyncio.to_thread(hou.hipFile.load, hip_path)
        manager.set_hip_state(hip_path=hip_path, loaded=True)
        duration_ms = int((time.time() - start_time) * 1000)
        log_success(session_id="mcp", method="scene.load", duration_ms=duration_ms)
        return {"success": True, "hip_path": hip_path, "loaded": True}
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        log_error(
            session_id="mcp",
            method="scene.load",
            error=str(exc),
            duration_ms=duration_ms,
        )
        return {"success": False, "error": f"Failed to load scene: {exc}"}


async def _scene_save() -> dict[str, Any]:
    start_time = time.time()
    manager = get_session_manager()
    state = manager.state
    if not state.hip_loaded:
        return {"success": False, "error": "No scene loaded"}
    try:
        hou = manager.get_hou()
        await asyncio.to_thread(hou.hipFile.saveAndBackup)
        post_check_versioning(state.hip_path or "")
        duration_ms = int((time.time() - start_time) * 1000)
        log_success(session_id="mcp", method="scene.save", duration_ms=duration_ms)
        return {"success": True, "hip_path": state.hip_path, "version": "current"}
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        log_error(
            session_id="mcp",
            method="scene.save",
            error=str(exc),
            duration_ms=duration_ms,
        )
        return {"success": False, "error": f"Failed to save scene: {exc}"}


async def _scene_version_up() -> dict[str, Any]:
    code = """
import json
import hou

old_path = hou.hipFile.path()
hou.hipFile.saveAndIncrementFileName()
new_path = hou.hipFile.path()
print(json.dumps({"old_path": old_path, "new_path": new_path}))
"""
    try:
        # Minimum 60s: saveAndIncrementFileName writes to disk and may be slow.
        result = await remote_exec(code, timeout=60.0)
        if not result["ok"]:
            return {
                "success": False,
                "error": (result.get("stderr") or "").strip()
                or "scene version_up failed",
            }
        import json as _json

        stdout = (result.get("stdout") or "").strip()
        last = stdout.rfind("{")
        data = _json.loads(stdout[last:]) if last != -1 else {}
        old_path = data.get("old_path", "")
        new_path = data.get("new_path", "")
        manager = get_session_manager()
        manager.set_hip_state(hip_path=new_path or None, loaded=bool(new_path))
        return {"success": True, "old_path": old_path, "new_path": new_path}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _scene_info() -> dict[str, Any]:
    manager = get_session_manager()
    state = manager.state
    return {
        "hip_loaded": state.hip_loaded,
        "hip_path": state.hip_path,
        "project_path": state.paths.get("project_path"),
    }


def _scene_list(max_results: int = 200) -> dict[str, Any]:
    manager = get_session_manager()
    state = manager.state
    shot_path = state.paths.get("shot_path")
    if not shot_path:
        return {
            "error": "No shot context active; create session with project+sequence+shot"
        }

    shot_root = Path(shot_path)
    tasks_root = shot_root / "tasks"
    if not tasks_root.exists():
        return {
            "shot_path": str(shot_root),
            "tasks_path": str(tasks_root),
            "count": 0,
            "scenes": [],
        }

    scene_files = []
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

    truncated = len(scene_files) > max_results
    if truncated:
        scene_files = scene_files[:max_results]

    result: dict[str, Any] = {
        "shot_path": str(shot_root),
        "tasks_path": str(tasks_root),
        "count": len(scene_files),
        "scenes": scene_files,
    }
    if truncated:
        result["truncated"] = True
        result["truncation_message"] = (
            f"Results truncated at {max_results} items; "
            "increase max_results or use a more specific path."
        )
    return result


@mcp.tool()
async def scene(
    action: str,
    hip_path: str | None = None,
    max_results: int = 200,
) -> dict[str, Any]:
    """
    Scene file operations.

    Args:
        action: "load" — load a HIP file (requires hip_path);
                "save" — save current scene with backup;
                "version_up" — save with incremented version number;
                "info" — return current scene path and load state;
                "list" — list HIP files in the shot's tasks directory
        hip_path: Absolute path to HIP file (required for action="load")
        max_results: Maximum number of scene files returned by action="list"
            (default: 200). When the limit is hit the response includes
            truncated=true and a truncation_message.

    Returns:
        Operation result dict
    """
    ok, err = require_session()
    if not ok:
        return err  # type: ignore[return-value]

    if action == "load":
        if not hip_path:
            return {"success": False, "error": "hip_path is required for action='load'"}
        return await _scene_load(hip_path)

    elif action == "save":
        return await _scene_save()

    elif action == "version_up":
        return await _scene_version_up()

    elif action == "info":
        return _scene_info()

    elif action == "list":
        return _scene_list(max_results=max_results)

    else:
        return {
            "success": False,
            "error": f"Unknown action: {action!r}; use 'load', 'save', 'version_up', 'info', or 'list'",
        }
