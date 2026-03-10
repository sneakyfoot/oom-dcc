"""Unit tests for output-length limiting on recursive listing tools.

These tests exercise the pure-Python helper functions (_do_node_query,
_scene_list) without a live Houdini session or ShotGrid connection.  All DCC
and MCP infrastructure is stubbed out via sys.modules so the test suite runs
with the bare CPython standard library.

Run with:
    python3 -m unittest tests/test_output_limits.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub out packages that are not available in the bare CPython environment:
#   fastmcp, rpyc  (and sub-modules accessed at import time).
#
# fastmcp needs a real FastMCP base-class that keeps @mcp.tool() as a
# passthrough so that the actual async functions remain callable coroutines.
# ---------------------------------------------------------------------------


class _FastMCPStub:
    """Minimal FastMCP stand-in: decorators are pass-throughs."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def tool(self, *args: object, **kwargs: object):  # type: ignore[override]
        def decorator(fn):
            return fn

        return decorator

    def resource(self, uri: str, *args: object, **kwargs: object):
        def decorator(fn):
            return fn

        return decorator

    def _setup_handlers(self) -> None:
        pass

    def _setup_task_protocol_handlers(self) -> None:
        pass

    @property
    def _mcp_server(self) -> MagicMock:
        m = MagicMock()
        m.get_capabilities.return_value = MagicMock(tasks=None)
        return m


def _make_fastmcp_stub() -> ModuleType:
    mod = ModuleType("fastmcp")
    mod.FastMCP = _FastMCPStub  # type: ignore[attr-defined]
    return mod


def _make_generic_stub(name: str) -> ModuleType:
    mod = ModuleType(name)
    mod.__class__ = type(  # type: ignore[assignment]
        "_StubModule",
        (ModuleType,),
        {"__getattr__": lambda self, _attr: MagicMock()},
    )
    return mod


if "fastmcp" not in sys.modules:
    sys.modules["fastmcp"] = _make_fastmcp_stub()
for _pkg in ("rpyc", "rpyc.core", "rpyc.utils"):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = _make_generic_stub(_pkg)

# Add the mcp-server directory to sys.path so oom_agent is importable.
_MCP_SERVER_DIR = str(Path(__file__).parent.parent / "mcp-server")
if _MCP_SERVER_DIR not in sys.path:
    sys.path.insert(0, _MCP_SERVER_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_node(path: str, name: str, ntype: str) -> MagicMock:
    node = MagicMock()
    node.path.return_value = path
    node.name.return_value = name
    node.type.return_value.name.return_value = ntype
    node.outputConnections.return_value = []
    return node


def _make_mock_hou(children: list[MagicMock]) -> MagicMock:
    hou = MagicMock()
    parent = MagicMock()
    parent.allSubChildren.return_value = children
    parent.children.return_value = children
    hou.node.return_value = parent
    return hou


def _make_nodes(n: int) -> list[MagicMock]:
    return [_make_mock_node(f"/obj/node{i}", f"node{i}", "geo") for i in range(n)]


# ---------------------------------------------------------------------------
# _do_node_query  (nodes.py)
# ---------------------------------------------------------------------------


class TestDoNodeQuery(unittest.TestCase):
    """Tests for _do_node_query output-length limiting."""

    def setUp(self) -> None:
        from oom_agent.tools.nodes import _do_node_query

        self._fn = _do_node_query

    def _call(
        self,
        nodes: list[MagicMock],
        max_results: int = 200,
        recurse: bool = True,
        include_connections: bool = False,
    ) -> dict:
        hou = _make_mock_hou(nodes)
        return self._fn(
            hou=hou,
            parent_path="/",
            node_type=None,
            name_pattern=None,
            recurse=recurse,
            include_connections=include_connections,
            include_positions=False,
            max_results=max_results,
        )

    # -- no truncation -------------------------------------------------------

    def test_under_limit_returns_all_nodes(self) -> None:
        result = self._call(_make_nodes(5), max_results=10)
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 5)
        self.assertEqual(len(result["nodes"]), 5)

    def test_under_limit_no_truncated_flag(self) -> None:
        result = self._call(_make_nodes(5), max_results=10)
        self.assertNotIn("truncated", result)
        self.assertNotIn("truncation_message", result)

    def test_exactly_at_limit_no_truncation(self) -> None:
        result = self._call(_make_nodes(10), max_results=10)
        self.assertEqual(result["count"], 10)
        self.assertNotIn("truncated", result)

    # -- truncation ----------------------------------------------------------

    def test_over_limit_count_matches_max(self) -> None:
        result = self._call(_make_nodes(15), max_results=10)
        self.assertEqual(result["count"], 10)
        self.assertEqual(len(result["nodes"]), 10)

    def test_over_limit_sets_truncated_true(self) -> None:
        result = self._call(_make_nodes(15), max_results=10)
        self.assertIs(result.get("truncated"), True)

    def test_over_limit_truncation_message_present(self) -> None:
        result = self._call(_make_nodes(15), max_results=10)
        self.assertIn("truncation_message", result)

    def test_truncation_message_contains_limit_value(self) -> None:
        result = self._call(_make_nodes(50), max_results=7)
        self.assertIn("7", result["truncation_message"])

    def test_truncation_message_suggests_filters(self) -> None:
        result = self._call(_make_nodes(50), max_results=7)
        msg = result["truncation_message"].lower()
        self.assertTrue("filter" in msg or "narrow" in msg)

    # -- connections only reference kept nodes --------------------------------

    def test_connections_confined_to_kept_nodes(self) -> None:
        """A connection referencing a cut-off node must not appear in output."""
        nodes = _make_nodes(15)
        # node0 has a connection to node14, which is beyond max_results=10
        conn = MagicMock()
        conn.outputNode.return_value = nodes[14]
        conn.outputIndex.return_value = 0
        conn.inputIndex.return_value = 0
        nodes[0].outputConnections.return_value = [conn]

        from oom_agent.tools.nodes import _do_node_query

        result = _do_node_query(
            hou=_make_mock_hou(nodes),
            parent_path="/",
            node_type=None,
            name_pattern=None,
            recurse=True,
            include_connections=True,
            include_positions=False,
            max_results=10,
        )
        kept = {n["path"] for n in result["nodes"]}
        for entry in result.get("connections", []):
            self.assertIn(entry["from"], kept)
            self.assertIn(entry["to"], kept)

    # -- node not found -------------------------------------------------------

    def test_node_not_found_returns_error(self) -> None:
        hou = MagicMock()
        hou.node.return_value = None
        from oom_agent.tools.nodes import _do_node_query

        result = _do_node_query(
            hou=hou,
            parent_path="/missing",
            node_type=None,
            name_pattern=None,
            recurse=False,
            include_connections=False,
            include_positions=False,
            max_results=200,
        )
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"].lower())


# ---------------------------------------------------------------------------
# _scene_list  (scene.py)
# ---------------------------------------------------------------------------


class TestSceneList(unittest.TestCase):
    """Tests for _scene_list output-length limiting."""

    def _write_hip_files(self, tasks_root: Path, count: int) -> None:
        for i in range(count):
            step_dir = tasks_root / f"step{i}" / "houdini"
            step_dir.mkdir(parents=True, exist_ok=True)
            (step_dir / f"scene{i}.hip").write_text("dummy")

    def _call(self, shot_path: Path, max_results: int = 200) -> dict:
        from oom_agent.tools.scene import _scene_list

        mock_manager = MagicMock()
        mock_manager.state.paths = {"shot_path": str(shot_path)}
        with patch(
            "oom_agent.tools.scene.get_session_manager", return_value=mock_manager
        ):
            return _scene_list(max_results=max_results)

    # -- no truncation -------------------------------------------------------

    def test_under_limit_returns_all(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shot = Path(td)
            self._write_hip_files(shot / "tasks", 5)
            result = self._call(shot, max_results=10)
        self.assertEqual(result["count"], 5)
        self.assertEqual(len(result["scenes"]), 5)
        self.assertNotIn("truncated", result)

    def test_exactly_at_limit_no_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shot = Path(td)
            self._write_hip_files(shot / "tasks", 10)
            result = self._call(shot, max_results=10)
        self.assertNotIn("truncated", result)
        self.assertEqual(result["count"], 10)

    # -- truncation ----------------------------------------------------------

    def test_over_limit_count_matches_max(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shot = Path(td)
            self._write_hip_files(shot / "tasks", 15)
            result = self._call(shot, max_results=10)
        self.assertEqual(result["count"], 10)
        self.assertEqual(len(result["scenes"]), 10)

    def test_over_limit_sets_truncated_true(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shot = Path(td)
            self._write_hip_files(shot / "tasks", 15)
            result = self._call(shot, max_results=10)
        self.assertIs(result.get("truncated"), True)

    def test_over_limit_message_contains_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shot = Path(td)
            self._write_hip_files(shot / "tasks", 15)
            result = self._call(shot, max_results=10)
        self.assertIn("10", result.get("truncation_message", ""))

    # -- edge cases -----------------------------------------------------------

    def test_missing_tasks_dir_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = self._call(Path(td), max_results=10)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["scenes"], [])
        self.assertNotIn("truncated", result)

    def test_no_shot_context_returns_error_key(self) -> None:
        from oom_agent.tools.scene import _scene_list

        mock_manager = MagicMock()
        mock_manager.state.paths = {}
        with patch(
            "oom_agent.tools.scene.get_session_manager", return_value=mock_manager
        ):
            result = _scene_list()
        self.assertIn("error", result)


# ---------------------------------------------------------------------------
# publish list — code-template sanity checks  (pipeline.py)
#
# We capture the code string sent to remote_exec and assert that it embeds
# the correct limit and truncation logic.  No live ShotGrid connection needed.
# ---------------------------------------------------------------------------


class TestPublishListCodeTemplate(unittest.TestCase):
    """Verify that the remote code snippet embeds the right limit values."""

    def _capture_code(self, max_results: int) -> str:
        captured: list[str] = []

        async def fake_remote_exec(code: str, timeout: float = 30.0) -> dict:
            captured.append(code)
            return {
                "ok": True,
                "stdout": json.dumps({"publishes": {}, "count": 0}),
                "stderr": "",
            }

        import oom_agent.tools.pipeline as pipeline_mod

        with patch.object(pipeline_mod, "remote_exec", side_effect=fake_remote_exec):
            with patch.object(
                pipeline_mod, "require_session", return_value=(True, None)
            ):
                asyncio.run(
                    pipeline_mod.publish(action="list", max_results=max_results)
                )

        self.assertTrue(captured, "remote_exec was never called")
        return captured[0]

    def test_sg_limit_is_max_results_plus_one(self) -> None:
        """sg.find() must be called with limit=max_results+1 to detect truncation."""
        code = self._capture_code(max_results=50)
        self.assertIn("limit=51", code)

    def test_max_results_value_appears_in_code(self) -> None:
        code = self._capture_code(max_results=50)
        self.assertIn("50", code)

    def test_truncation_message_key_in_code(self) -> None:
        code = self._capture_code(max_results=50)
        self.assertIn("truncation_message", code)

    def test_truncated_flag_in_code(self) -> None:
        code = self._capture_code(max_results=50)
        self.assertIn("truncated", code)

    def test_different_max_results_reflected(self) -> None:
        code = self._capture_code(max_results=99)
        self.assertIn("limit=100", code)


if __name__ == "__main__":
    unittest.main()
