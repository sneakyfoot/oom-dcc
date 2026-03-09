"""Shared FastMCP application instance.

Split from mcp_server.py so tool modules can import ``mcp`` without
circular-import issues.
"""

from typing import Any

import fastmcp


class _NoTasksMCP(fastmcp.FastMCP):
    """FastMCP subclass that suppresses MCP tasks capability.

    FastMCP 2.14.5 unconditionally advertises a ``tasks`` capability whose
    JSON shape is incompatible with rmcp 0.13.0 (the Rust MCP client used
    by daemon-wizard).  We suppress it at both layers:
    - Skip task protocol handler registration
    - Patch the low-level server's get_capabilities to strip ``tasks``
    """

    def _setup_task_protocol_handlers(self) -> None:
        pass

    def _setup_handlers(self) -> None:
        super()._setup_handlers()
        orig_get_caps = self._mcp_server.get_capabilities

        def _get_caps_no_tasks(*args: Any, **kwargs: Any) -> Any:
            caps = orig_get_caps(*args, **kwargs)
            caps.tasks = None
            return caps

        self._mcp_server.get_capabilities = _get_caps_no_tasks  # type: ignore[method-assign]


mcp = _NoTasksMCP(
    "OOM DCC Server",
    instructions="""
MCP server controlling a persistent Houdini runtime for VFX pipeline operations.

Tools (14 total):
- session(action)      — create/destroy/status for Houdini sessions with ShotGrid context
- scene(action)        — load/save/version_up/info/list HIP files
- node_info            — full detail on one node (parms, flags, color, position)
- node_query           — list/search nodes; optionally include connections and positions
- parm(action)         — get/set/set_expression on node parameters; batch mode available
- node_create          — create a node inside a parent network
- node_delete          — delete a node
- node_connect         — wire two nodes together
- node_set_flags       — set display/render/bypass flags
- cook_node            — cook a TOP/PDG node (session or agent mode)
- farm_submit          — submit a TOP node cook to the Kubernetes farm
- cache(action)        — get_versions/refresh for OOM cache HDAs via ShotGrid
- publish(action)      — list/load_latest published files for the current shot context
- execute_code         — run arbitrary Python in the hython session

Always call session(action="status") first to verify an active session exists.
""",
)
