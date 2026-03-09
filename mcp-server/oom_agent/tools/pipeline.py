"""Pipeline operation tools: cook, farm submit, cache, publishes.

These tools run pipeline code *inside* Houdini (via ``manager.execute()``)
because they import ``oom_houdini`` modules that depend on ``hou``.

The one exception is ``farm_submit``: ``submit_controller_job`` does not
import ``hou`` and runs fine in the MCP server's Python 3.13 environment.
"""

from __future__ import annotations

import json
import time
from typing import Any

from oom_agent._app import mcp
from oom_agent.guardrails import log_error, log_success
from oom_agent.logging_config import get_logger
from oom_agent.tools._helpers import parse_remote_json, remote_exec, require_session

logger = get_logger(__name__)


@mcp.tool()
async def cook_node(node_path: str, mode: str = "session") -> dict[str, Any]:
    """
    Cook a TOP/PDG node in the current session.

    Args:
        node_path: Absolute path to the TOP node (e.g. "/obj/topnet1/cook_geo")
        mode: "session" — cook without loading a new hip (cook_in_session);
              "agent" — walk upstream, bump cache versions, save, then cook (agent_cook)

    Returns:
        success status and any output/errors from the cook
    """
    ok, err = require_session()
    if not ok:
        return err  # type: ignore[return-value]

    if mode not in ("session", "agent"):
        return {"success": False, "error": f"Invalid mode {mode!r}; use 'session' or 'agent'"}

    if mode == "agent":
        func = "agent_cook"
        code = f"""
import json
from oom_houdini.cook_top import agent_cook
result = agent_cook({json.dumps(node_path)})
print(json.dumps({{"cook_result": str(result) if result else "ok"}}))
"""
    else:
        func = "cook_in_session"
        code = f"""
import json
from oom_houdini.cook_top import cook_in_session
cook_in_session({json.dumps(node_path)})
print(json.dumps({{"cook_result": "started"}}))
"""

    start_time = time.time()
    try:
        result = await remote_exec(code, timeout=300.0)
        duration_ms = int((time.time() - start_time) * 1000)
        parsed = parse_remote_json(result)
        if parsed.get("success"):
            log_success(session_id="mcp", method=f"cook_node.{func}", duration_ms=duration_ms)
        else:
            log_error(
                session_id="mcp",
                method=f"cook_node.{func}",
                error=parsed.get("error", ""),
                duration_ms=duration_ms,
            )
        return parsed
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def farm_submit(
    hip_path: str,
    node_path: str,
    gpu: bool = False,
) -> dict[str, Any]:
    """
    Submit a TOP node cook to the farm via a Kubernetes controller job.

    Args:
        hip_path: Absolute path to the HIP file
        node_path: TOP node path to cook (e.g. "/obj/topnet1/cook_geo")
        gpu: Deprecated — service jobs do not request GPUs; always ignored

    Returns:
        success, job_name, and status message
    """
    _ = gpu  # service jobs do not support GPU; accepted for API compat
    ok, err = require_session()
    if not ok:
        return err  # type: ignore[return-value]

    try:
        from oom_houdini.submit_pdg_cook import submit_controller_job
    except ImportError as exc:
        return {"success": False, "error": f"submit_pdg_cook not available: {exc}"}

    try:
        success, message = submit_controller_job(hip_path, node_path)
        return {
            "success": bool(success),
            "message": str(message),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def cache(
    action: str,
    cache_name: str | None = None,
    publish_type: str = "oom_houdini_cache",
    node_path: str | None = None,
) -> dict[str, Any]:
    """
    Cache operations against ShotGrid and cache HDA nodes.

    Args:
        action: "get_versions" — query SG for published versions of a named cache
                    (requires cache_name);
                "refresh" — refresh version list on a cache HDA node from ShotGrid
                    (requires node_path)
        cache_name: Cache publish name — value of the HDA's ``name`` parm
                    (required for get_versions)
        publish_type: ShotGrid PublishedFileType code (default: "oom_houdini_cache")
        node_path: Absolute path to the cache HDA node (required for refresh)

    Returns:
        Operation result dict
    """
    ok, err = require_session()
    if not ok:
        return err  # type: ignore[return-value]

    if action == "get_versions":
        if not cache_name:
            return {"success": False, "error": "cache_name is required for action='get_versions'"}
        code = f"""
import json
from oom_houdini.oom_cache import get_versions
versions = get_versions({json.dumps(cache_name)}, {json.dumps(publish_type)})
print(json.dumps({{"versions": versions, "cache_name": {json.dumps(cache_name)}}}))
"""
        try:
            result = await remote_exec(code, timeout=30.0)
            return parse_remote_json(result)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    elif action == "refresh":
        if not node_path:
            return {"success": False, "error": "node_path is required for action='refresh'"}
        code = f"""
import json
import hou
from oom_houdini.oom_cache import get_versions, store_versions, restore_selected, cache_versions_update, CACHE_PUBLISHED_TYPE_CODE

node = hou.node({json.dumps(node_path)})
if node is None:
    print(json.dumps({{"success": False, "error": "Node not found: " + {json.dumps(node_path)}}}))
else:
    cache_name = node.parm("name").eval()
    versions = get_versions(cache_name, CACHE_PUBLISHED_TYPE_CODE)
    store_versions(node, versions)
    cache_versions_update(cache_name, versions)
    restore_selected(node)
    print(json.dumps({{"cache_name": cache_name, "versions": versions}}))
"""
        try:
            result = await remote_exec(code, timeout=30.0)
            return parse_remote_json(result)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    else:
        return {
            "success": False,
            "error": f"Unknown action: {action!r}; use 'get_versions' or 'refresh'",
        }


@mcp.tool()
async def publish(
    action: str,
    publish_type: str | None = None,
    step: str | None = None,
    node_path: str | None = None,
) -> dict[str, Any]:
    """
    Publish operations for the current shot context.

    Args:
        action: "list" — list published files grouped by name (optional filters:
                    publish_type, step);
                "load_latest" — load the latest publish onto a loader node
                    (requires node_path + publish_type)
        publish_type: ShotGrid PublishedFileType code filter (e.g. "oom_houdini_cache",
                      "oom_usd_publish_wedged", "oom_renderpass").
                      Required for load_latest; optional filter for list.
        step: Pipeline step code filter for list (e.g. "FX", "LIGHTING")
        node_path: Absolute path to the loader HDA node (required for load_latest)

    Returns:
        For list: {publishes: {code: [{version_number, path, created_at, entity, publish_type}]}, count}
        For load_latest: {node_path, old_path, new_path}
    """
    ok, err = require_session()
    if not ok:
        return err  # type: ignore[return-value]

    if action == "list":
        code = f"""
import json
import hou

tk = hou.session.oom_tk
sg = tk.shotgun
context = hou.session.oom_context

filters = [
    ["project", "is", context.project],
    ["entity", "is", context.entity],
]

publish_type = {json.dumps(publish_type)}
step = {json.dumps(step)}

if publish_type:
    filters.append(["published_file_type.PublishedFileType.code", "is", publish_type])

if step:
    step_entity = sg.find_one("Step", [["code", "is", step]], ["id", "code"])
    if step_entity:
        filters.append(["task.Task.step", "is", step_entity])

fields = ["code", "version_number", "path", "created_at", "entity",
          "published_file_type", "task"]
pubs = sg.find(
    "PublishedFile",
    filters,
    fields,
    order=[{{"field_name": "version_number", "direction": "desc"}}],
)

grouped = {{}}
for p in pubs:
    key = p.get("code") or ""
    entry = {{
        "version_number": p.get("version_number"),
        "path": (p.get("path") or {{}}).get("local_path"),
        "created_at": str(p.get("created_at") or ""),
        "entity": p.get("entity"),
        "publish_type": (p.get("published_file_type") or {{}}).get("name"),
    }}
    grouped.setdefault(key, []).append(entry)

print(json.dumps({{"publishes": grouped, "count": len(pubs)}}))
"""
        try:
            result = await remote_exec(code, timeout=30.0)
            return parse_remote_json(result)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    elif action == "load_latest":
        if not node_path:
            return {"success": False, "error": "node_path is required for action='load_latest'"}
        if not publish_type:
            return {"success": False, "error": "publish_type is required for action='load_latest'"}
        code = f"""
import json
import hou
from oom_houdini.sg_load import update_to_latest

node = hou.node({json.dumps(node_path)})
if node is None:
    print(json.dumps({{"success": False, "error": "Node not found: " + {json.dumps(node_path)}}}))
else:
    old_path = ""
    fname_parm = node.parm("filename")
    if fname_parm:
        old_path = fname_parm.eval() or ""

    update_to_latest({json.dumps(node_path)}, {json.dumps(publish_type)}, is_path=True)

    new_path = ""
    if fname_parm:
        new_path = fname_parm.eval() or ""

    print(json.dumps({{"node_path": {json.dumps(node_path)}, "old_path": old_path, "new_path": new_path}}))
"""
        try:
            result = await remote_exec(code, timeout=30.0)
            return parse_remote_json(result)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    else:
        return {
            "success": False,
            "error": f"Unknown action: {action!r}; use 'list' or 'load_latest'",
        }
