"""Shared utilities for MCP tool modules."""

from __future__ import annotations

import json
from typing import Any

from oom_agent.session_manager import get_session_manager


def require_session() -> tuple[bool, dict[str, Any] | None]:
    """Check session is initialized.

    Returns ``(True, None)`` when a session is active, or
    ``(False, error_dict)`` otherwise.
    """
    manager = get_session_manager()
    if not manager.is_initialized():
        return False, {"success": False, "error": "No active session"}
    return True, None


async def remote_exec(code: str, timeout: float = 60.0) -> dict[str, Any]:
    """Execute *code* in the remote hython/live session."""
    manager = get_session_manager()
    return await manager.execute(code, timeout)


def parse_remote_json(result: dict[str, Any]) -> dict[str, Any]:
    """Parse JSON printed to stdout by a remote exec snippet.

    The remote snippet should end with ``print(json.dumps({...}))``.
    If parsing fails the raw output is returned under ``"output"``.
    """
    if not result["ok"]:
        stderr = (result.get("stderr") or "").strip()
        return {"success": False, "error": stderr or "Remote execution failed"}

    stdout = (result.get("stdout") or "").strip()
    if not stdout:
        return {"success": True}

    # Find last JSON object in stdout (there may be debug prints before it)
    last_brace = stdout.rfind("{")
    if last_brace != -1:
        candidate = stdout[last_brace:]
        try:
            data = json.loads(candidate)
            data.setdefault("success", True)
            return data
        except json.JSONDecodeError:
            pass

    return {"success": True, "output": stdout}
