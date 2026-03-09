"""Node inspection and manipulation tools.

All tools use the ``hou`` RPyC proxy directly (no remote exec) since they are
pure Houdini API calls.  Every value returned must be converted to a native
Python type (str/int/float/bool/list/dict) before returning — RPyC netrefs
are not JSON-serialisable.
"""

from __future__ import annotations

import asyncio
import fnmatch
from typing import Any

from oom_agent._app import mcp
from oom_agent.logging_config import get_logger
from oom_agent.session_manager import get_session_manager
from oom_agent.tools._helpers import require_session

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal synchronous helpers (run via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _node_pos(node: Any) -> list[float]:
    """Return node position as [x, y]."""
    try:
        pos = node.position()
        return [float(pos[0]), float(pos[1])]
    except Exception:
        return [0.0, 0.0]


def _node_color(node: Any) -> list[float]:
    """Return node color as [r, g, b]."""
    try:
        c = node.color()
        rgb = c.rgb()
        return [float(rgb[0]), float(rgb[1]), float(rgb[2])]
    except Exception:
        return [1.0, 1.0, 1.0]


def _parm_value(parm: Any) -> Any:
    """Return a JSON-safe evaluated parm value."""
    try:
        val = parm.eval()
        if isinstance(val, (int, float, str, bool)):
            return val
        return str(val)
    except Exception:
        return None


def _parm_raw_value(parm: Any) -> Any:
    """Return a JSON-safe unexpanded parm string (before expression eval)."""
    try:
        return str(parm.unexpandedString())
    except Exception:
        return None


def _parm_expression(parm: Any) -> str | None:
    """Return the expression on a parm, or None."""
    try:
        return str(parm.expression())
    except Exception:
        return None


def _parm_type_name(parm: Any) -> str:
    try:
        return str(parm.parmTemplate().type())
    except Exception:
        return "unknown"


def _parm_menu_items(parm: Any) -> list[str] | None:
    """Return menu token list for menu parms, else None."""
    try:
        tpl = parm.parmTemplate()
        items = tpl.menuItems()
        if items:
            return [str(i) for i in items]
    except Exception:
        pass
    return None


def _serialize_parm(parm: Any) -> dict[str, Any]:
    return {
        "name": str(parm.name()),
        "type": _parm_type_name(parm),
        "value": _parm_value(parm),
        "raw_value": _parm_raw_value(parm),
        "expression": _parm_expression(parm),
        "menu_items": _parm_menu_items(parm),
    }


def _serialize_node_brief(node: Any) -> dict[str, Any]:
    return {
        "path": str(node.path()),
        "name": str(node.name()),
        "type": str(node.type().name()),
    }


# ---------------------------------------------------------------------------
# Synchronous worker functions
# ---------------------------------------------------------------------------


def _do_node_info(hou: Any, node_path: str) -> dict[str, Any]:
    node = hou.node(node_path)
    if node is None:
        return {"success": False, "error": f"Node not found: {node_path}"}

    parms = {}
    try:
        for parm in node.parms():
            parms[str(parm.name())] = _parm_value(parm)
    except Exception:
        pass

    flags: dict[str, bool] = {}
    for flag_name in ("isDisplayFlagSet", "isRenderFlagSet", "isBypassed"):
        try:
            flags[flag_name] = bool(getattr(node, flag_name)())
        except Exception:
            pass

    return {
        "success": True,
        "path": str(node.path()),
        "name": str(node.name()),
        "type": str(node.type().name()),
        "position": _node_pos(node),
        "color": _node_color(node),
        "comment": str(node.comment()),
        "flags": flags,
        "parms": parms,
    }


def _do_node_query(
    hou: Any,
    parent_path: str,
    node_type: str | None,
    name_pattern: str | None,
    recurse: bool,
    include_connections: bool,
    include_positions: bool,
) -> dict[str, Any]:
    parent = hou.node(parent_path)
    if parent is None:
        return {"success": False, "error": f"Node not found: {parent_path}"}

    candidates = list(parent.allSubChildren()) if recurse else list(parent.children())

    nodes_info = []
    for node in candidates:
        try:
            ntype = str(node.type().name())
            nname = str(node.name())
        except Exception:
            continue

        if node_type and node_type not in ntype:
            continue
        if name_pattern and not fnmatch.fnmatch(nname, name_pattern):
            continue

        entry = _serialize_node_brief(node)
        if include_positions:
            entry["position"] = _node_pos(node)
        nodes_info.append(entry)

    result: dict[str, Any] = {
        "success": True,
        "parent_path": parent_path,
        "count": len(nodes_info),
        "nodes": nodes_info,
    }

    if include_connections:
        connections = []
        # Re-iterate to collect connections between matching nodes
        node_paths = {n["path"] for n in nodes_info}
        for node in candidates:
            try:
                npath = str(node.path())
            except Exception:
                continue
            if npath not in node_paths:
                continue
            try:
                for conn in node.outputConnections():
                    dest = conn.outputNode()
                    dest_path = str(dest.path())
                    if dest_path in node_paths:
                        connections.append(
                            {
                                "from": npath,
                                "from_output": int(conn.outputIndex()),
                                "to": dest_path,
                                "to_input": int(conn.inputIndex()),
                            }
                        )
            except Exception:
                continue
        result["connections"] = connections

    return result


def _do_parm_get(hou: Any, node_path: str, parm_name: str) -> dict[str, Any]:
    node = hou.node(node_path)
    if node is None:
        return {"success": False, "error": f"Node not found: {node_path}"}

    parm = node.parm(parm_name)
    if parm is None:
        return {"success": False, "error": f"Parm not found: {parm_name} on {node_path}"}

    return {"success": True, **_serialize_parm(parm)}


def _do_parm_set(hou: Any, node_path: str, parm_name: str, value: Any) -> dict[str, Any]:
    node = hou.node(node_path)
    if node is None:
        return {"success": False, "error": f"Node not found: {node_path}"}

    parm = node.parm(parm_name)
    if parm is None:
        return {"success": False, "error": f"Parm not found: {parm_name} on {node_path}"}

    try:
        parm.set(value)
        return {"success": True, "node_path": node_path, "parm_name": parm_name, "value": value}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _do_parm_set_expression(
    hou: Any, node_path: str, parm_name: str, expression: str, language: str
) -> dict[str, Any]:
    node = hou.node(node_path)
    if node is None:
        return {"success": False, "error": f"Node not found: {node_path}"}

    parm = node.parm(parm_name)
    if parm is None:
        return {"success": False, "error": f"Parm not found: {parm_name} on {node_path}"}

    try:
        lang_map = {
            "hscript": hou.exprLanguage.Hscript,
            "python": hou.exprLanguage.Python,
        }
        lang = lang_map.get(language.lower(), hou.exprLanguage.Hscript)
        parm.setExpression(expression, lang)
        return {
            "success": True,
            "node_path": node_path,
            "parm_name": parm_name,
            "expression": expression,
            "language": language,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _do_node_create(
    hou: Any, parent_path: str, node_type: str, name: str | None
) -> dict[str, Any]:
    parent = hou.node(parent_path)
    if parent is None:
        return {"success": False, "error": f"Parent node not found: {parent_path}"}

    try:
        node = parent.createNode(node_type, name)
        return {
            "success": True,
            "path": str(node.path()),
            "name": str(node.name()),
            "type": str(node.type().name()),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _do_node_delete(hou: Any, node_path: str) -> dict[str, Any]:
    node = hou.node(node_path)
    if node is None:
        return {"success": False, "error": f"Node not found: {node_path}"}
    try:
        node.destroy()
        return {"success": True, "deleted_path": node_path}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _do_node_connect(
    hou: Any, from_path: str, output_index: int, to_path: str, input_index: int
) -> dict[str, Any]:
    from_node = hou.node(from_path)
    if from_node is None:
        return {"success": False, "error": f"From-node not found: {from_path}"}

    to_node = hou.node(to_path)
    if to_node is None:
        return {"success": False, "error": f"To-node not found: {to_path}"}

    try:
        to_node.setInput(input_index, from_node, output_index)
        return {
            "success": True,
            "from_path": from_path,
            "output_index": output_index,
            "to_path": to_path,
            "input_index": input_index,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _do_node_set_flags(
    hou: Any,
    node_path: str,
    display: bool | None,
    render: bool | None,
    bypass: bool | None,
) -> dict[str, Any]:
    node = hou.node(node_path)
    if node is None:
        return {"success": False, "error": f"Node not found: {node_path}"}

    applied: dict[str, bool] = {}
    errors: list[str] = []

    for flag_val, setter_name, key in (
        (display, "setDisplayFlag", "display"),
        (render, "setRenderFlag", "render"),
        (bypass, "bypass", "bypass"),
    ):
        if flag_val is None:
            continue
        try:
            getattr(node, setter_name)(flag_val)
            applied[key] = flag_val
        except Exception as exc:
            errors.append(f"{key}: {exc}")

    if errors:
        return {"success": False, "error": "; ".join(errors), "applied": applied}
    return {"success": True, "node_path": node_path, "applied": applied}


def _do_parm_batch(hou: Any, node_path: str, parms: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute a list of parm operations and return aggregated results."""
    results = []
    for entry in parms:
        parm_action = entry.get("action", "get")
        parm_name = entry.get("parm_name") or entry.get("name")
        if not parm_name:
            results.append({"success": False, "error": "parm_name missing in batch entry"})
            continue
        if parm_action == "get":
            results.append(_do_parm_get(hou, node_path, parm_name))
        elif parm_action == "set":
            value = entry.get("value")
            results.append(_do_parm_set(hou, node_path, parm_name, value))
        elif parm_action == "set_expression":
            expression = entry.get("expression", "")
            language = entry.get("language", "hscript")
            results.append(_do_parm_set_expression(hou, node_path, parm_name, expression, language))
        else:
            results.append({"success": False, "error": f"Unknown batch parm action: {parm_action!r}"})
    return {"results": results}


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------


@mcp.tool()
async def node_info(node_path: str) -> dict[str, Any]:
    """
    Get detailed information about a Houdini node.

    Returns type, name, position, comment, color, flags, and all parameter
    values.

    Args:
        node_path: Absolute node path (e.g. "/obj/geo1")
    """
    ok, err = require_session()
    if not ok:
        return err  # type: ignore[return-value]

    manager = get_session_manager()
    hou = manager.get_hou()
    return await asyncio.to_thread(_do_node_info, hou, node_path)


@mcp.tool()
async def node_query(
    parent_path: str = "/",
    node_type: str | None = None,
    name_pattern: str | None = None,
    recurse: bool = False,
    include_connections: bool = False,
    include_positions: bool = False,
) -> dict[str, Any]:
    """
    List and search nodes within a network.

    Without filters, lists direct children (breadth-first overview).
    With filters, searches matching nodes. With include_connections, returns
    the wiring between matched nodes as well.

    Args:
        parent_path: Root node path to list/search under (default: "/")
        node_type: Filter by node type substring (e.g. "topnet", "oom_cache")
        name_pattern: Glob pattern for node name (e.g. "cache_*", "OUT")
        recurse: Search all descendants, not just direct children (default: False)
        include_connections: Include connection data between matched nodes
        include_positions: Include network positions for each node

    Returns:
        {success, parent_path, count, nodes: [{path, name, type, [position]}],
         [connections: [{from, from_output, to, to_input}]]}
    """
    ok, err = require_session()
    if not ok:
        return err  # type: ignore[return-value]

    manager = get_session_manager()
    hou = manager.get_hou()
    return await asyncio.to_thread(
        _do_node_query,
        hou,
        parent_path,
        node_type,
        name_pattern,
        recurse,
        include_connections,
        include_positions,
    )


@mcp.tool()
async def parm(
    action: str,
    node_path: str,
    parm_name: str | None = None,
    value: Any = None,
    expression: str | None = None,
    language: str = "hscript",
    parms: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Read or write node parameters.

    Single-parm mode (parm_name provided):
      action="get"            — read value, raw string, expression, type, menu items
      action="set"            — set value (requires value)
      action="set_expression" — set expression string (requires expression; language optional)

    Batch mode (parms list provided):
      Ignores action/parm_name/value/expression at the top level.
      Each entry: {action, parm_name, [value], [expression], [language]}
      Returns {results: [per-entry result dicts]}

    Args:
        action: "get", "set", or "set_expression"
        node_path: Absolute node path
        parm_name: Parameter name (required for single-parm mode)
        value: New value for set (str, int, or float)
        expression: Expression string for set_expression
        language: "hscript" (default) or "python"
        parms: List of parm operation dicts for batch mode
    """
    ok, err = require_session()
    if not ok:
        return err  # type: ignore[return-value]

    manager = get_session_manager()
    hou = manager.get_hou()

    if parms is not None:
        return await asyncio.to_thread(_do_parm_batch, hou, node_path, parms)

    if not parm_name:
        return {"success": False, "error": "parm_name is required (or provide parms list for batch)"}

    if action == "get":
        return await asyncio.to_thread(_do_parm_get, hou, node_path, parm_name)
    elif action == "set":
        return await asyncio.to_thread(_do_parm_set, hou, node_path, parm_name, value)
    elif action == "set_expression":
        if expression is None:
            return {"success": False, "error": "expression is required for action='set_expression'"}
        return await asyncio.to_thread(
            _do_parm_set_expression, hou, node_path, parm_name, expression, language
        )
    else:
        return {
            "success": False,
            "error": f"Unknown action: {action!r}; use 'get', 'set', or 'set_expression'",
        }


@mcp.tool()
async def node_create(
    parent_path: str,
    node_type: str,
    name: str | None = None,
) -> dict[str, Any]:
    """
    Create a new node inside a parent network.

    Args:
        parent_path: Parent node path (e.g. "/obj")
        node_type: Houdini node type (e.g. "geo", "topnet", "rop_geometry")
        name: Optional node name; Houdini auto-assigns if omitted

    Returns:
        path, name, and type of the created node
    """
    ok, err = require_session()
    if not ok:
        return err  # type: ignore[return-value]

    manager = get_session_manager()
    hou = manager.get_hou()
    return await asyncio.to_thread(_do_node_create, hou, parent_path, node_type, name)


@mcp.tool()
async def node_delete(node_path: str) -> dict[str, Any]:
    """
    Delete a node.

    Args:
        node_path: Absolute path of the node to delete
    """
    ok, err = require_session()
    if not ok:
        return err  # type: ignore[return-value]

    manager = get_session_manager()
    hou = manager.get_hou()
    return await asyncio.to_thread(_do_node_delete, hou, node_path)


@mcp.tool()
async def node_connect(
    from_path: str,
    output_index: int,
    to_path: str,
    input_index: int,
) -> dict[str, Any]:
    """
    Connect two nodes.

    Args:
        from_path: Source node path
        output_index: Output connector index on the source node
        to_path: Destination node path
        input_index: Input connector index on the destination node
    """
    ok, err = require_session()
    if not ok:
        return err  # type: ignore[return-value]

    manager = get_session_manager()
    hou = manager.get_hou()
    return await asyncio.to_thread(
        _do_node_connect, hou, from_path, output_index, to_path, input_index
    )


@mcp.tool()
async def node_set_flags(
    node_path: str,
    display: bool | None = None,
    render: bool | None = None,
    bypass: bool | None = None,
) -> dict[str, Any]:
    """
    Set node flags (only the explicitly provided flags are changed).

    Args:
        node_path: Node path
        display: Set display flag (optional)
        render: Set render flag (optional)
        bypass: Set bypass flag (optional)
    """
    ok, err = require_session()
    if not ok:
        return err  # type: ignore[return-value]

    manager = get_session_manager()
    hou = manager.get_hou()
    return await asyncio.to_thread(
        _do_node_set_flags, hou, node_path, display, render, bypass
    )
