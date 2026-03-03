"""
OomContext integration for Houdini session bootstrap.
Extracts and wraps context resolution logic.
"""

import os
from typing import Optional, Dict, Any


def extract_context_paths(
    project: str, sequence: Optional[str] = None, shot: Optional[str] = None
) -> Dict[str, str]:
    """
    Extract project/sequence/shot paths based on oom context logic.
    
    This is a simplified version that sets environment variables for the session.
    The full ShotGrid/SGTK bootstrap logic can be added later.
    
    Args:
        project: Project name
        sequence: Optional sequence name
        shot: Optional shot name
    
    Returns:
        Dictionary of resolved paths
    """
    # Base paths - adjust for your actual project structure
    base_path = os.environ.get("OOM_BASE_PATH", "/mnt/RAID/Assets")
    
    result = {
        "project": project,
        "project_path": f"{base_path}/{project}",
    }
    
    if sequence:
        result["sequence"] = sequence
        result["sequence_path"] = f"{base_path}/{project}/sequences/{sequence}"
    
    if shot:
        result["shot"] = shot
        result["shot_path"] = f"{base_path}/{project}/shots/{shot}"
        result["hip_directory"] = f"{base_path}/{project}/shots/{shot}/HIPs"
    
    return result


def set_session_environment(
    session_id: str, paths: Dict[str, str]
) -> Dict[str, str]:
    """
    Set environment variables for a session.
    
    Args:
        session_id: Session identifier
        paths: Resolved paths from extract_context_paths
    
    Returns:
        Dictionary of set environment variables
    """
    env_vars = {}
    
    # Build session-specific environment
    session_root = f"/tmp/{session_id}"
    
    for key, value in paths.items():
        if value:
            env_name = f"OOM_SESSION_{session_id.upper()}_{key.upper()}"
            os.environ[env_name] = value
            env_vars[env_name] = value
    
    # Set standard OOM variables
    os.environ["OOM_SESSION_ROOT"] = session_root
    
    # Add to common vars if in scope
    if "project_path" in paths:
        os.environ["OOM_PROJECT_PATH"] = paths["project_path"]
        env_vars["OOM_PROJECT_PATH"] = paths["project_path"]
    
    if "sequence_path" in paths:
        os.environ["OOM_SEQUENCE_PATH"] = paths["sequence_path"]
        env_vars["OOM_SEQUENCE_PATH"] = paths["sequence_path"]
    
    if "shot_path" in paths:
        os.environ["OOM_SHOT_PATH"] = paths["shot_path"]
        env_vars["OOM_SHOT_PATH"] = paths["shot_path"]
    
    return env_vars


def bootstrap_session(
    session_id: str, project: str, sequence: Optional[str], shot: Optional[str]
) -> Dict[str, Any]:
    """
    Full session bootstrap combining path extraction and environment setup.
    
    Args:
        session_id: Session identifier
        project: Project name
        sequence: Sequence name (optional)
        shot: Shot name (optional)
    
    Returns:
        Dictionary with paths, env_vars, and project metadata
    """
    # Extract paths
    paths = extract_context_paths(project, sequence, shot)
    
    # Set environment
    env_vars = set_session_environment(session_id, paths)
    
    # Build result
    result = {
        "session_id": session_id,
        "project": paths.get("project"),
        "sequence": paths.get("sequence"),
        "shot": paths.get("shot"),
        "paths": paths,
        "env_vars": env_vars,
    }
    
    return result
