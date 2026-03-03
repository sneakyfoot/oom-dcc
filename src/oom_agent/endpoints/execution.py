"""
Hython execution endpoint.
Sandboxed code execution via hython subprocess.
"""

import asyncio
import os
import shlex
from typing import Any, Dict

from fastapi import HTTPException

from oom_agent.session_manager import get_session_manager
from oom_agent.protocol import register_method
from oom_agent.guardrails import log_operation, pre_check_session, pre_check_code, log_success, log_error
from oom_agent.logging_config import get_logger

logger = get_logger(__name__)


def _get_hython_path() -> str:
    """Get path to hython executable."""
    hfs = os.environ.get("HFS")
    if not hfs:
        raise HTTPException(status_code=500, detail="HFS environment variable not set")
    return f"{hfs}/bin/hython"


async def _run_hython_script(code: str, timeout: float = 30.0) -> tuple[Any, str, str]:
    """
    Execute code via hython subprocess.
    
    Args:
        code: Python code to execute
        timeout: Timeout in seconds
    
    Returns:
        Tuple of (result, stdout, stderr)
    """
    loop = asyncio.get_event_loop()
    hython_path = _get_hython_path()
    
    def _execute():
        import subprocess
        import tempfile
        
        # Prepare environment
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        
        # Write code to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            script_path = f.name
        
        try:
            # Run hython with indie license
            cmd = [hython_path, "--indie", "-c", code]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            return result.stdout, result.stderr, result.returncode
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass
    
    try:
        stdout, stderr, returncode = await loop.run_in_executor(None, _execute)
        
        if returncode != 0:
            return None, stdout, f"Exit code {returncode}: {stderr}"
        
        return None, stdout, stderr
    
    except asyncio.TimeoutError:
        return None, "", f"Execution timeout - code exceeded {timeout} second limit"
    except Exception as e:
        return None, "", f"Execution error: {str(e)}"


@register_method("agent.execute")
async def agent_execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute hython code in Houdini session.
    
    Parameters:
        session_id: Session ID
        code: Python code to execute
        timeout: Execution timeout in seconds (default: 30)
    
    Returns:
        Execution result and captured output
    """
    import time
    import hashlib
    
    start_time = time.time()
    
    session_id = params.get("session_id")
    code = params.get("code")
    timeout = params.get("timeout", 30.0)
    
    if not session_id or not code:
        raise HTTPException(
            status_code=400,
            detail="session_id and code are required",
        )
    
    if not pre_check_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    if not pre_check_code(code):
        raise HTTPException(status_code=400, detail="Invalid code detected")
    
    try:
        # Execute via hython
        result, stdout, stderr = await _run_hython_script(code, timeout)
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Determine status
        if stderr and ("Error:" in stderr or "Traceback" in stderr):
            status = "failed"
        else:
            status = "success"
        
        # Log operation
        log_operation(
            session_id=session_id,
            method="agent.execute",
            params={"code_hash": hashlib.sha256(code.encode()).hexdigest()[:16]},
            status=status,
            duration_ms=duration_ms,
        )
        
        if status == "success":
            log_success(
                session_id=session_id,
                method="agent.execute",
                duration_ms=duration_ms,
            )
        
        # Build response
        response = {
            "success": status == "success",
            "result": str(result) if result is not None else None,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": duration_ms,
        }
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        log_error(
            session_id=session_id,
            method="agent.execute",
            error=str(e),
            duration_ms=duration_ms,
        )
        
        return {
            "success": False,
            "result": None,
            "stdout": "",
            "stderr": str(e),
            "duration_ms": duration_ms,
        }
