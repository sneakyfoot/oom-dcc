from __future__ import annotations

from typing import Any


class HoudiniService:
    """RPyC service exposing the Houdini hou module."""

    exposed_hou: Any


class HrpycServer:
    """Handle returned by start_server(); wraps the underlying ThreadedServer."""

    def close(self) -> None: ...


def start_server(
    port: int = 18811,
    use_thread: bool = True,
    **kwargs: Any,
) -> HrpycServer:
    """Start an RPyC server in a daemon thread exposing the hou module.

    Args:
        port: TCP port to listen on (default 18811).
        use_thread: Run the server in a background daemon thread.

    Returns:
        HrpycServer handle; call .close() to stop.
    """
    ...


def import_remote_module(conn: Any, module_name: str) -> Any:
    """Import a module on the remote rpyc connection and return its proxy."""
    ...


def __getattr__(name: str) -> Any: ...
