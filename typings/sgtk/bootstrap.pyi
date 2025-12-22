"""Minimal stub of sgtk.bootstrap for static analysis."""

from typing import Any, Optional


class ToolkitManager:
    plugin_id: str
    pipeline_configuration: str

    def __init__(self, user: Any): ...
    def bootstrap_engine(self, engine: str, entity: Optional[Any] = ...) -> Any: ...
