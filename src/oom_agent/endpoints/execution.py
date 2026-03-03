"""
Execution endpoint for persistent hython runtime.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict

from fastapi import HTTPException

from oom_agent.guardrails import (
    log_error,
    log_operation,
    log_success,
    pre_check_code,
    pre_check_runtime,
)
from oom_agent.protocol import register_method
from oom_agent.session_manager import get_session_manager


@register_method("agent.execute")
async def agent_execute(params: Dict[str, Any]) -> Dict[str, Any]:
    start_time = time.time()
    code = params.get("code")
    timeout = float(params.get("timeout", 30.0))

    if not code:
        raise HTTPException(status_code=400, detail="code is required")
    if not pre_check_runtime():
        raise HTTPException(status_code=404, detail="No active session")
    if not pre_check_code(code):
        raise HTTPException(status_code=400, detail="Invalid code detected")

    manager = get_session_manager()

    try:
        exec_result = await manager.execute(code, timeout)
        duration_ms = int((time.time() - start_time) * 1000)
        success = bool(exec_result["ok"])

        log_operation(
            session_id="server",
            method="agent.execute",
            params={"code_hash": hashlib.sha256(code.encode()).hexdigest()[:16]},
            status="success" if success else "failed",
            duration_ms=duration_ms,
        )
        if success:
            log_success(
                session_id="server", method="agent.execute", duration_ms=duration_ms
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
        log_error(
            session_id="server",
            method="agent.execute",
            error=str(exc),
            duration_ms=duration_ms,
        )
        return {
            "success": False,
            "result": None,
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": duration_ms,
        }
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        log_error(
            session_id="server",
            method="agent.execute",
            error=str(exc),
            duration_ms=duration_ms,
        )
        return {
            "success": False,
            "result": None,
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": duration_ms,
        }
