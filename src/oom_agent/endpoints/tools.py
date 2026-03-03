"""
Tool wrappers endpoints.
Controlled operations for common pipeline workflows.
"""

from typing import Any, Dict

from fastapi import HTTPException

from oom_agent.protocol import register_method
from oom_agent.guardrails import pre_check_runtime
from oom_agent.logging_config import get_logger

logger = get_logger(__name__)


@register_method("tools.farm_submit")
async def tools_farm_submit(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Submit a TOP node to the farm.

    Parameters:
        hip_path: Path to HIP file
        node_path: TOP node path to submit
        gpu: Whether to request GPU (default: false)

    Returns:
        Submission status and job ID
    """
    if not pre_check_runtime():
        raise HTTPException(status_code=404, detail="No active session")

    # TODO: Implement farm submission logic
    # This should integrate with oom_houdini.submit_pdg_cook
    # For now, return placeholder response

    logger.info("Farm submit requested")

    return {
        "status": "not_implemented",
        "message": "Farm submission not yet implemented",
        "session": "server",
    }


@register_method("tools.publish_output")
async def tools_publish_output(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Publish work item output.

    Parameters:
        node_path: Node path to publish

    Returns:
        Publish status and output paths
    """
    if not pre_check_runtime():
        raise HTTPException(status_code=404, detail="No active session")

    # TODO: Implement publish logic
    # This should integrate with oom_cache or oom_lop_publish

    logger.info("Publish requested")

    return {
        "status": "not_implemented",
        "message": "Publish operation not yet implemented",
        "session": "server",
    }


@register_method("tools.cache_refresh")
async def tools_cache_refresh(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Refresh cache versions for nodes.

    Parameters:
        node_path: Node path to refresh

    Returns:
        Refresh status and available versions
    """
    if not pre_check_runtime():
        raise HTTPException(status_code=404, detail="No active session")

    # TODO: Implement cache refresh logic
    # This should integrate with oom_cache.get_versions and store_versions

    logger.info("Cache refresh requested")

    return {
        "status": "not_implemented",
        "message": "Cache refresh not yet implemented",
        "session": "server",
    }
