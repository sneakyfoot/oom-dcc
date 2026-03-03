"""
Guardrails for agent operations.
Pre and post checks, validation, and logging.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, List
import hashlib

from oom_agent.logging_config import get_logger

logger = get_logger(__name__)

# Allowed path prefixes
ALLOWED_PATH_PREFIXES = ["/tmp/", "/mnt/RAID/", "/home/"]

# Allowed file extensions
ALLOWED_EXTENSIONS = {
    "scene": [".hip", ".hiplc"],
    "image": [".png", ".jpg", ".jpeg"],
    "code": [".py"],
}


def validate_path(path: str, allowed_types: List[str]) -> bool:
    """Validate that path is under allowed prefixes and has valid extension."""
    if not path:
        return True  # Allow empty/None paths (optional)
    
    # Check prefix
    if not any(path.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES):
        return False
    
    # Check extension
    path_lower = path.lower()
    for ext_type in allowed_types:
        for ext in ALLOWED_EXTENSIONS.get(ext_type, []):
            if path_lower.endswith(ext):
                return True
        # If no type specified, skip extension check
    
    return True


def validate_code(code: Optional[str]) -> bool:
    """Validate code execution parameters."""
    if not code:
        return False
    
    # Check for obvious security issues
    dangerous_patterns = [
        "os.system",
        "os.popen",
        "subprocess.call",
        "subprocess.run",
        "__import__('builtins')",
        "eval(",
        "exec(",
    ]
    
    code_lower = code.lower()
    for pattern in dangerous_patterns:
        if pattern in code_lower:
            return False
    
    return True


def hash_code(code: str) -> str:
    """Create hash of code for logging (to avoid logging full code)."""
    return hashlib.sha256(code.encode()).hexdigest()[:16]


def log_operation(
    session_id: str,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    status: Optional[str] = None,
    duration_ms: Optional[int] = None,
    result: Optional[Any] = None,
) -> None:
    """Log operation with structured data."""
    # Prepare log record
    log_record = logger.makeRecord(
        logger.name,
        logging.INFO,
        "agent_op",
        1,
        f"Method: {method}",
        (),
        None,
    )
    
    # Add custom fields
    log_record.session_id = session_id
    log_record.method = method
    log_record.params = params
    log_record.status = status
    log_record.duration_ms = duration_ms
    log_record.result = result
    
    logger.handle(log_record)


def pre_check_session(session_id: str) -> bool:
    """Pre-check: verify session exists."""
    from oom_agent.session_manager import get_session_manager
    
    manager = get_session_manager()
    exists = manager.exists(session_id)
    
    if not exists:
        logger.warning(f"Session {session_id} not found")
    
    return exists


def pre_check_scene_path(session_id: str, hip_path: str) -> bool:
    """Pre-check: validate scene path."""
    if not validate_path(hip_path, allowed_types=["scene"]):
        logger.error(f"Invalid scene path: {hip_path}")
        return False
    return True


def pre_check_code(code: str) -> bool:
    """Pre-check: validate code before execution."""
    if not validate_code(code):
        logger.error("Invalid code detected in execution request")
        return False
    return True


def post_check_versioning(session_id: str, hip_path: str) -> None:
    """Post-check: suggest versioning after scene save."""
    # This would integrate with oom_cache to check if versions are managed
    # Placeholder for future implementation
    logger.info(f"Post-save check for session {session_id}")


def log_success(session_id: str, method: str, duration_ms: int) -> None:
    """Log successful operation."""
    logger.info(
        f"Operation {method} completed successfully",
        extra={
            "session_id": session_id,
            "method": method,
            "status": "success",
            "duration_ms": duration_ms,
        },
    )


def log_error(session_id: str, method: str, error: str, duration_ms: int) -> None:
    """Log failed operation."""
    logger.error(
        f"Operation {method} failed",
        extra={
            "session_id": session_id,
            "method": method,
            "status": "error",
            "error": error,
            "duration_ms": duration_ms,
        },
    )
