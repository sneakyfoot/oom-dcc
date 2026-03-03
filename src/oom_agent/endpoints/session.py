"""
Session management endpoints.
Create, destroy, and query agent sessions.
"""

import logging
import time
from typing import Any, Dict, Optional

from fastapi import HTTPException

from oom_agent.session_manager import get_session_manager, SessionState
from oom_agent.protocol import register_method
from oom_agent.guardrails import log_operation, pre_check_session, log_success, log_error
from oom_agent.logging_config import get_logger

logger = get_logger(__name__)


@register_method("agent.create_session")
async def create_session(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new agent session.
    
    Parameters:
        project: Project name
        sequence: Sequence name (optional)
        shot: Shot name (optional)
    
    Returns:
        Session ID and resolved paths
    """
    start_time = time.time()
    project = params.get("project")
    sequence = params.get("sequence")
    shot = params.get("shot")
    
    if not project:
        raise HTTPException(status_code=400, detail="Project is required")
    
    try:
        from oom_agent.context import bootstrap_session
        
        # Import scene endpoint to get _ensure_houdini_initialized
        from oom_agent.endpoints import scene
        
        # Create session
        manager = get_session_manager()
        session = manager.create(project=project, sequence=sequence, shot=shot)
        
        # Bootstrap context
        context_info = bootstrap_session(
            session.session_id, project, sequence, shot
        )
        
        # Initialize Houdini immediately
        scene._ensure_houdini_initialized(session)
        
        # Log success
        duration_ms = int((time.time() - start_time) * 1000)
        log_operation(
            session_id=session.session_id,
            method="agent.create_session",
            params={"project": project, "sequence": sequence, "shot": shot},
            status="success",
            duration_ms=duration_ms,
        )
        log_success(
            session_id=session.session_id,
            method="agent.create_session",
            duration_ms=duration_ms,
        )
        
        return {
            "session_id": session.session_id,
            "project": context_info["project"],
            "sequence": context_info.get("sequence"),
            "shot": context_info.get("shot"),
            "paths": context_info["paths"],
        }
    
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        log_error(
            session_id=params.get("session_id", "unknown"),
            method="agent.create_session",
            error=str(e),
            duration_ms=duration_ms,
        )
        raise HTTPException(status_code=500, detail=f"Failed to create session: {e}")


@register_method("agent.destroy_session")
async def destroy_session(params: Dict[str, Any]) -> Dict[str, bool]:
    """
    Destroy an agent session.
    
    Parameters:
        session_id: Session ID to destroy
    
    Returns:
        Success status
    """
    session_id = params.get("session_id")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    
    if not pre_check_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        manager = get_session_manager()
        success = manager.destroy(session_id)
        
        return {"success": success}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to destroy session: {e}")


@register_method("agent.get_status")
async def get_status(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get status of an agent session.
    
    Parameters:
        session_id: Session ID
        hfs: Houdini filesystem path (optional)
    
    Returns:
        Session status and current scene info
    """
    session_id = params.get("session_id")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    
    if not pre_check_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        manager = get_session_manager()
        session = manager.get(session_id)
        
        return {
            "session_id": session.session_id,
            "project": session.project,
            "sequence": session.sequence,
            "shot": session.shot,
            "hip_loaded": session.hip_loaded,
            "hip_path": session.hip_path,
            "project_path": session.project_path,
            "created_at": session.created_at,
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {e}")
