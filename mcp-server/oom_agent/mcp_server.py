"""
MCP server for Houdini agent.
Exposes Houdini pipeline operations as MCP tools and resources.

Tool implementations live in ``oom_agent/tools/``.  Importing the submodules
registers each tool on the shared ``mcp`` FastMCP instance defined in
``oom_agent/_app.py``.
"""

import asyncio
import json
from pathlib import Path

from oom_agent._app import mcp
from oom_agent.context import bootstrap_context

# Import tool modules — each module registers its tools via @mcp.tool()
import oom_agent.tools.session  # noqa: F401
import oom_agent.tools.scene  # noqa: F401
import oom_agent.tools.nodes  # noqa: F401
import oom_agent.tools.pipeline  # noqa: F401


# ============================================================================
# Code Execution (kept here — not pipeline-specific)
# ============================================================================


from oom_agent.guardrails import log_operation, pre_check_runtime
from oom_agent.session_manager import get_session_manager
from typing import Any
import time


@mcp.tool()
async def execute_code(code: str, timeout: float = 60.0) -> dict[str, Any]:
    """
    Execute Houdini Python code (hython) in the current session.

    Args:
        code: Python code to execute
        timeout: Execution timeout in seconds (minimum 60s)

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
# Resources (for LLM access to files and context)
# ============================================================================


_LIST_SCENES_LIMIT = 200


@mcp.resource("houdini://{project}/{sequence}/{shot}/scenes")
async def list_scenes(project: str, sequence: str, shot: str) -> str:
    """
    List available scene files for a shot.

    Provides structured access to scene files in the VFX pipeline.
    Returns at most 200 paths; use the scene(action="list") tool with
    max_results for finer control.
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

        truncated = len(scenes) > _LIST_SCENES_LIMIT
        if truncated:
            scenes = scenes[:_LIST_SCENES_LIMIT]

        result: dict = {"shot_path": shot_path, "scenes": scenes}
        if truncated:
            result["truncated"] = True
            result["truncation_message"] = (
                f"Results truncated at {_LIST_SCENES_LIMIT} items; "
                "use scene(action='list') with max_results for finer control."
            )
        return json.dumps(result)

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


def main() -> None:
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
