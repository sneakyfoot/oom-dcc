"""
Scene management endpoints.
Load, save, and manage Houdini scenes.
"""

import logging
import os
from typing import Any, Dict
from pathlib import Path

from fastapi import HTTPException

from oom_agent.session_manager import get_session_manager, SessionState
from oom_agent.protocol import register_method
from oom_agent.guardrails import (
    log_operation,
    pre_check_session,
    pre_check_scene_path,
    post_check_versioning,
    log_success,
    log_error,
)
from oom_agent.logging_config import get_logger

logger = get_logger(__name__)


def _get_hython_path() -> str:
    """Get path to hython executable."""
    import os
    hfs = os.environ.get("HFS")
    if hfs:
        return f"{hfs}/bin/hython"
    raise HTTPException(status_code=500, detail="HFS environment variable not set")


def _ensure_houdini_initialized(session: SessionState) -> None:
    """Ensure Houdini module is available via hython."""
    # Verify hython is available
    hython_path = _get_hython_path()
    if not os.path.exists(hython_path):
        raise HTTPException(status_code=500, detail=f"Houdini not found at {hython_path}")
    logger.info(f"Houdini initialized for session {session.session_id}")


@register_method("scene.load")
async def scene_load(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Load a Houdini scene into session.
    
    Parameters:
        session_id: Session ID
        hip_path: Path to .hip file
    
    Returns:
        Load status and scene info
    """
    start_time = __import__("time").time()
    session_id = params.get("session_id")
    hip_path = params.get("hip_path")
    
    if not session_id or not hip_path:
        raise HTTPException(status_code=400, detail="session_id and hip_path are required")
    
    if not pre_check_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    if not pre_check_scene_path(session_id, hip_path):
        raise HTTPException(status_code=400, detail="Invalid hip_path")
    
    try:
        manager = get_session_manager()
        session = manager.get(session_id)
        
        # Initialize Houdini if needed
        _ensure_houdini_initialized(session)
        
        # Load scene
        if session.hou:
            session.hou.hipFile.load(hip_path)
            session.hip_loaded = True
            session.hip_path = hip_path
        
        duration_ms = int((__import__("time").time() - start_time) * 1000)
        log_success(
            session_id=session_id,
            method="scene.load",
            duration_ms=duration_ms,
        )
        
        return {
            "success": True,
            "hip_path": hip_path,
            "loaded": True,
        }
    
    except Exception as e:
        duration_ms = int((__import__("time").time() - start_time) * 1000)
        log_error(
            session_id=session_id,
            method="scene.load",
            error=str(e),
            duration_ms=duration_ms,
        )
        raise HTTPException(status_code=500, detail=f"Failed to load scene: {e}")


@register_method("scene.save")
async def scene_save(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save current scene in session.
    
    Parameters:
        session_id: Session ID
        auto_version: Whether to version (default: true)
    
    Returns:
        Save status and version info
    """
    start_time = __import__("time").time()
    session_id = params.get("session_id")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    
    if not pre_check_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        manager = get_session_manager()
        session = manager.get(session_id)
        
        # Initialize Houdini if needed
        _ensure_houdini_initialized(session)
        
        if session.hou and session.hip_loaded:
            # Save with backup
            session.hou.hipFile.saveAndBackup()
            session.hip_loaded = True
        
        # Post-check for versioning
        post_check_versioning(session_id, session.hip_path or "")
        
        duration_ms = int((__import__("time").time() - start_time) * 1000)
        log_success(
            session_id=session_id,
            method="scene.save",
            duration_ms=duration_ms,
        )
        
        return {
            "success": True,
            "hip_path": session.hip_path,
            "version": "current",
        }
    
    except Exception as e:
        duration_ms = int((__import__("time").time() - start_time) * 1000)
        log_error(
            session_id=session_id,
            method="scene.save",
            error=str(e),
            duration_ms=duration_ms,
        )
        raise HTTPException(status_code=500, detail=f"Failed to save scene: {e}")


@register_method("scene.get_current")
async def scene_get_current(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get current scene info for session.
    
    Parameters:
        session_id: Session ID
    
    Returns:
        Current scene path and status
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
            "session_id": session_id,
            "hip_loaded": session.hip_loaded,
            "hip_path": session.hip_path,
            "project_path": session.project_path,
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get current scene: {e}")
