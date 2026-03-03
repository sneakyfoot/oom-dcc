"""
Tool wrappers endpoints.
Controlled operations for common pipeline workflows.
"""

import logging
from typing import Any, Dict

from fastapi import HTTPException

from oom_agent.session_manager import get_session_manager
from oom_agent.protocol import register_method
from oom_agent.guardrails import log_operation, pre_check_session
from oom_agent.logging_config import get_logger

logger = get_logger(__name__)


@register_method("tools.farm_submit")
async def tools_farm_submit(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Submit a TOP node to the farm.
    
    Parameters:
        session_id: Session ID
        hip_path: Path to HIP file
        node_path: TOP node path to submit
        gpu: Whether to request GPU (default: false)
    
    Returns:
        Submission status and job ID
    """
    session_id = params.get("session_id")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    
    if not pre_check_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    # TODO: Implement farm submission logic
    # This should integrate with oom_houdini.submit_pdg_cook
    # For now, return placeholder response
    
    logger.info(f"Farm submit requested for session {session_id}")
    
    return {
        "status": "not_implemented",
        "message": "Farm submission not yet implemented",
        "session_id": session_id,
    }


@register_method("tools.publish_output")
async def tools_publish_output(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Publish work item output.
    
    Parameters:
        session_id: Session ID
        node_path: Node path to publish
    
    Returns:
        Publish status and output paths
    """
    session_id = params.get("session_id")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    
    if not pre_check_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    # TODO: Implement publish logic
    # This should integrate with oom_cache or oom_lop_publish
    
    logger.info(f"Publish requested for session {session_id}")
    
    return {
        "status": "not_implemented",
        "message": "Publish operation not yet implemented",
        "session_id": session_id,
    }


@register_method("tools.cache_refresh")
async def tools_cache_refresh(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Refresh cache versions for nodes.
    
    Parameters:
        session_id: Session ID
        node_path: Node path to refresh
    
    Returns:
        Refresh status and available versions
    """
    session_id = params.get("session_id")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    
    if not pre_check_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    # TODO: Implement cache refresh logic
    # This should integrate with oom_cache.get_versions and store_versions
    
    logger.info(f"Cache refresh requested for session {session_id}")
    
    return {
        "status": "not_implemented",
        "message": "Cache refresh not yet implemented",
        "session_id": session_id,
    }
