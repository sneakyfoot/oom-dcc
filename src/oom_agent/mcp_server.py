"""
MCP server for Houdini agent.
Exposes Houdini pipeline operations as MCP tools and resources.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from oom_agent.session_manager import get_session_manager
from oom_agent.context import bootstrap_context
from oom_agent.guardrails import (
    pre_check_runtime,
    pre_check_scene_path,
    log_error,
    log_success,
    log_operation,
    post_check_versioning,
)
from oom_agent.logging_config import get_logger

logger = get_logger(__name__)

mcp = FastMCP(
    "OOM Houdini Agent",
    instructions="""
You are an MCP server controlling a persistent Houdini runtime for VFX pipeline operations.

Available capabilities:
- Session management: Create/destroy Houdini sessions with ShotGrid context
- Scene operations: Load, save, and list HIP files
- Code execution: Run Houdini Python code (hython) in the session
- Tool wrappers: Farm submission, publish outputs, cache operations
- Resources: Access scene files and project context

Always verify session status before performing operations.
""")


# ============================================================================
# Session Management
# ============================================================================

@mcp.tool()
async def create_session(
    project: str,
    sequence: str | None = None,
    shot: str | None = None,
) -> dict[str, Any]:
    """
    Create a new Houdini session with ShotGrid context.

    Args:
        project: ShotGrid project name
        sequence: Sequence code (optional)
        shot: Shot code (requires sequence)

    Returns:
        Session state with project, sequence, shot, and paths
    """
    start_time = time.time()

    try:
        context_info = await asyncio.to_thread(
            bootstrap_context,
            project,
            sequence,
            shot,
        )
        manager = get_session_manager()
        state = await asyncio.to_thread(manager.initialize, context_info)

        # Bootstrap ShotGrid context inside Houdini
        bootstrap_code = f"""
import hou
import sgtk
import oom_sg_auth
from oom_bootstrap import bootstrap
import json

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

        bootstrap_result = await manager.execute(bootstrap_code, timeout=120.0)
        if not bootstrap_result["ok"]:
            await asyncio.to_thread(manager.shutdown, True)
            raise RuntimeError(
                f"Failed to bootstrap context inside hython: "
                f"{bootstrap_result['stderr'] or 'unknown error'}"
            )

        duration_ms = int((time.time() - start_time) * 1000)
        log_operation(
            session_id="mcp",
            method="create_session",
            params={"project": project, "sequence": sequence, "shot": shot},
            status="success",
            duration_ms=duration_ms,
        )
        log_success(
            session_id="mcp", method="create_session", duration_ms=duration_ms
        )

        return {
            "success": True,
            "initialized": state.initialized,
            "project": state.project,
            "sequence": state.sequence,
            "shot": state.shot,
            "paths": state.paths,
            "worker_pid": state.worker_pid,
        }

    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        log_error(
            session_id="mcp",
            method="create_session",
            error=str(exc),
            duration_ms=duration_ms,
        )
        return {
            "success": False,
            "error": str(exc),
        }


@mcp.tool()
async def destroy_session() -> dict[str, Any]:
    """
    Destroy the current Houdini session and clean up resources.
    """
    manager = get_session_manager()
    if not manager.is_initialized():
        return {"success": False, "error": "No active session"}

    try:
        success = await asyncio.to_thread(manager.shutdown)
        return {"success": bool(success)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def get_status() -> dict[str, Any]:
    """
    Get the current session status and state.
    """
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


# ============================================================================
# Scene Operations
# ============================================================================

@mcp.tool()
async def scene_load(hip_path: str) -> dict[str, Any]:
    """
    Load a Houdini HIP file into the current session.

    Args:
        hip_path: Absolute path to the HIP file
    """
    start_time = time.time()

    if not pre_check_runtime():
        return {"success": False, "error": "No active session"}

    if not pre_check_scene_path(hip_path):
        return {"success": False, "error": f"Invalid hip_path: {hip_path}"}

    manager = get_session_manager()
    code = f"import hou\nhou.hipFile.load({json.dumps(hip_path)})"

    try:
        result = await manager.execute(code, timeout=60.0)
        if not result["ok"]:
            raise RuntimeError(result["stderr"] or "Failed to load scene")

        manager.set_hip_state(hip_path=hip_path, loaded=True)
        duration_ms = int((time.time() - start_time) * 1000)
        log_success(session_id="mcp", method="scene.load", duration_ms=duration_ms)

        return {
            "success": True,
            "hip_path": hip_path,
            "loaded": True,
            "stdout": result["stdout"],
        }

    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        log_error(
            session_id="mcp",
            method="scene.load",
            error=str(exc),
            duration_ms=duration_ms,
        )
        return {"success": False, "error": f"Failed to load scene: {exc}"}


@mcp.tool()
async def scene_save() -> dict[str, Any]:
    """
    Save the current scene with backup.
    """
    start_time = time.time()

    if not pre_check_runtime():
        return {"success": False, "error": "No active session"}

    manager = get_session_manager()
    state = manager.state
    if not state.hip_loaded:
        return {"success": False, "error": "No scene loaded"}

    code = "import hou\nhou.hipFile.saveAndBackup()"
    try:
        result = await manager.execute(code, timeout=60.0)
        if not result["ok"]:
            raise RuntimeError(result["stderr"] or "Failed to save scene")

        post_check_versioning(state.hip_path or "")
        duration_ms = int((time.time() - start_time) * 1000)
        log_success(session_id="mcp", method="scene.save", duration_ms=duration_ms)

        return {
            "success": True,
            "hip_path": state.hip_path,
            "version": "current",
            "stdout": result["stdout"],
        }

    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        log_error(
            session_id="mcp",
            method="scene.save",
            error=str(exc),
            duration_ms=duration_ms,
        )
        return {"success": False, "error": f"Failed to save scene: {exc}"}


@mcp.tool()
async def scene_get_current() -> dict[str, Any]:
    """
    Get information about the currently loaded scene.
    """
    if not pre_check_runtime():
        return {"error": "No active session"}

    manager = get_session_manager()
    state = manager.state

    return {
        "hip_loaded": state.hip_loaded,
        "hip_path": state.hip_path,
        "project_path": state.paths.get("project_path"),
    }


@mcp.tool()
async def scene_list() -> dict[str, Any]:
    """
    List all HIP files in the current shot's tasks directory.
    """
    if not pre_check_runtime():
        return {"error": "No active session"}

    manager = get_session_manager()
    state = manager.state
    shot_path = state.paths.get("shot_path")
    if not shot_path:
        return {
            "error": "No shot context active; create session with project+sequence+shot",
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
    return {
        "shot_path": str(shot_root),
        "tasks_path": str(tasks_root),
        "count": len(scene_files),
        "scenes": scene_files,
    }


# ============================================================================
# Code Execution
# ============================================================================

@mcp.tool()
async def execute_code(code: str, timeout: float = 30.0) -> dict[str, Any]:
    """
    Execute Houdini Python code (hython) in the current session.

    Args:
        code: Python code to execute
        timeout: Execution timeout in seconds

    Returns:
        Execution result with stdout, stderr, and success status
    """
    start_time = time.time()

    if not code:
        return {"success": False, "error": "code is required"}

    if not pre_check_runtime():
        return {"success": False, "error": "No active session"}

    # Basic security checks
    if "import os" in code or "import subprocess" in code:
        return {"success": False, "error": "Forbidden imports detected"}
    if "__import__" in code or "eval(" in code or "exec(" in code:
        return {"success": False, "error": "Dangerous constructs detected"}

    manager = get_session_manager()

    try:
        exec_result = await manager.execute(code, timeout)
        duration_ms = int((time.time() - start_time) * 1000)
        success = bool(exec_result["ok"])

        log_operation(
            session_id="mcp",
            method="execute_code",
            params={"code_length": len(code)},
            status="success" if success else "failed",
            duration_ms=duration_ms,
        )

        return {
            "success": success,
            "result": None,
            "stdout": exec_result["stdout"],
            "stderr": exec_result["stderr"],
            "duration_ms": duration_ms,
        }

    except TimeoutError as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False,
            "error": str(exc),
            "duration_ms": duration_ms,
        }

    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False,
            "error": str(exc),
            "duration_ms": duration_ms,
        }


# ============================================================================
# Tool Wrappers
# ============================================================================

@mcp.tool()
async def farm_submit(
    hip_path: str,
    node_path: str,
    gpu: bool = False,
) -> dict[str, Any]:
    """
    Submit a TOP node to the farm.

    Args:
        hip_path: Path to HIP file
        node_path: TOP node path to submit (e.g., "/out/geo1")
        gpu: Whether to request GPU workers

    Returns:
        Submission status and job ID
    """
    if not pre_check_runtime():
        return {"success": False, "error": "No active session"}

    # TODO: Implement farm submission logic
    # This should integrate with oom_houdini.submit_pdg_cook
    logger.info(f"Farm submit requested: {node_path}")

    return {
        "success": False,
        "status": "not_implemented",
        "message": "Farm submission not yet implemented",
    }


@mcp.tool()
async def publish_output(node_path: str) -> dict[str, Any]:
    """
    Publish work item output for a node.

    Args:
        node_path: Node path to publish

    Returns:
        Publish status and output paths
    """
    if not pre_check_runtime():
        return {"success": False, "error": "No active session"}

    # TODO: Implement publish logic
    # This should integrate with oom_cache or oom_lop_publish
    logger.info(f"Publish requested for {node_path}")

    return {
        "success": False,
        "status": "not_implemented",
        "message": "Publish operation not yet implemented",
    }


@mcp.tool()
async def cache_refresh(node_path: str) -> dict[str, Any]:
    """
    Refresh cache versions for a node.

    Args:
        node_path: Node path to refresh

    Returns:
        Refresh status and available versions
    """
    if not pre_check_runtime():
        return {"success": False, "error": "No active session"}

    # TODO: Implement cache refresh logic
    # This should integrate with oom_cache.get_versions and store_versions
    logger.info(f"Cache refresh requested for {node_path}")

    return {
        "success": False,
        "status": "not_implemented",
        "message": "Cache refresh not yet implemented",
    }


# ============================================================================
# Resources (for LLM access to files and context)
# ============================================================================

@mcp.resource("houdini://{project}/{sequence}/{shot}/scenes")
async def list_scenes(project: str, sequence: str, shot: str) -> str:
    """
    List available scene files for a shot.

    Provides structured access to scene files in the VFX pipeline.
    """
    try:
        context_info = await asyncio.to_thread(
            bootstrap_context,
            project,
            sequence,
            shot,
        )
        shot_path = context_info.get("paths", {}).get("shot_path")
        if not shot_path:
            return json.dumps({"error": "Could not resolve shot path"})

        shot_root = Path(shot_path)
        tasks_root = shot_root / "tasks"

        scenes = []
        for extension in ("*.hip", "*.hiplc", "*.hipnc"):
            for hip_file in tasks_root.glob(f"*/houdini/{extension}"):
                if hip_file.is_file():
                    scenes.append(str(hip_file))

        return json.dumps({"shot_path": shot_path, "scenes": scenes})

    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.resource("houdini://{project}/{sequence}/{shot}/context")
async def get_shot_context(project: str, sequence: str, shot: str) -> str:
    """
    Get ShotGrid context information for a shot.
    """
    try:
        context_info = await asyncio.to_thread(
            bootstrap_context,
            project,
            sequence,
            shot,
        )
        return json.dumps(context_info, indent=2)

    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ============================================================================
# Server Entry Point
# ============================================================================

if __name__ == "__main__":
    mcp.run()
