"""Tests for rpyc AsyncResult timeout handling and codebase timeout minimums.

Covers:
- set_expiry is called with the right value; wait() called with no args
- AsyncResultTimeout -> RuntimeError conversion + session marked unhealthy
- All configurable and hard-coded defaults meet the 60s/300s minimums

Run with:
    python3 -m unittest tests/test_rpyc_timeout.py
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, call, patch

# ---------------------------------------------------------------------------
# Stub out packages unavailable in the bare CPython test environment.
# ---------------------------------------------------------------------------


class _AsyncResultTimeout(Exception):
    """Stub for rpyc.AsyncResultTimeout."""


def _make_rpyc_stub() -> ModuleType:
    mod = ModuleType("rpyc")
    mod.AsyncResultTimeout = _AsyncResultTimeout  # type: ignore[attr-defined]
    mod.Service = object  # type: ignore[attr-defined]
    mod.ThreadedServer = MagicMock()  # type: ignore[attr-defined]
    mod.connect = MagicMock()  # type: ignore[attr-defined]
    classic = MagicMock()
    mod.classic = classic  # type: ignore[attr-defined]

    def _async_(fn):
        return fn

    mod.async_ = _async_  # type: ignore[attr-defined]
    return mod


def _make_fastmcp_stub() -> ModuleType:
    class _FastMCPStub:
        def __init__(self, *a, **kw):
            pass

        def tool(self, *a, **kw):
            def dec(fn):
                return fn
            return dec

        def resource(self, uri, *a, **kw):
            def dec(fn):
                return fn
            return dec

        def _setup_handlers(self):
            pass

        def _setup_task_protocol_handlers(self):
            pass

        @property
        def _mcp_server(self):
            m = MagicMock()
            m.get_capabilities.return_value = MagicMock(tasks=None)
            return m

    mod = ModuleType("fastmcp")
    mod.FastMCP = _FastMCPStub  # type: ignore[attr-defined]
    return mod


def _make_generic_stub(name: str) -> ModuleType:
    mod = ModuleType(name)
    mod.__class__ = type(  # type: ignore[assignment]
        "_StubModule",
        (ModuleType,),
        {"__getattr__": lambda self, _: MagicMock()},
    )
    return mod


# Install stubs before importing oom_agent modules.
_rpyc_stub = _make_rpyc_stub()
sys.modules["rpyc"] = _rpyc_stub
for _pkg in ("rpyc.core", "rpyc.utils"):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = _make_generic_stub(_pkg)

if "fastmcp" not in sys.modules:
    sys.modules["fastmcp"] = _make_fastmcp_stub()

_MCP_SERVER_DIR = str(Path(__file__).parent.parent / "mcp-server")
if _MCP_SERVER_DIR not in sys.path:
    sys.path.insert(0, _MCP_SERVER_DIR)


# ---------------------------------------------------------------------------
# Helpers to build a minimal SessionManager instance without a live process.
# ---------------------------------------------------------------------------


def _make_session_manager():
    """Return a SessionManager wired with a fake conn/root/exec."""
    from oom_agent.session_manager import RuntimeState, SessionManager

    mgr = SessionManager()
    # Simulate an initialized, healthy session in HYTHON mode.
    mgr._state = RuntimeState(initialized=True, healthy=True)
    mgr._conn = MagicMock()
    mgr._hou = MagicMock()
    mgr._remote_exec = None  # HYTHON path, not LIVE
    return mgr


# ---------------------------------------------------------------------------
# 1. set_expiry + wait() call pattern
# ---------------------------------------------------------------------------


class TestSetExpiryCallPattern(unittest.TestCase):
    """execute_remote must call set_expiry(timeout) then wait() with no args."""

    def _run(self, timeout: float = 120.0):
        mgr = _make_session_manager()

        future = MagicMock()
        future.value = {"ok": True, "stdout": "", "stderr": ""}

        # async_(fn) returns fn unchanged (our stub), so conn.root.exec is
        # called directly and returns `future`.
        mgr._conn.root.exec.return_value = future

        result = mgr.execute_remote("pass", timeout=timeout)
        return future, result

    def test_set_expiry_called_with_timeout(self):
        future, _ = self._run(timeout=120.0)
        future.set_expiry.assert_called_once_with(120.0)

    def test_wait_called_with_no_args(self):
        future, _ = self._run(timeout=120.0)
        future.wait.assert_called_once_with()

    def test_set_expiry_before_wait(self):
        """set_expiry must be called before wait()."""
        future, _ = self._run(timeout=90.0)
        calls = future.mock_calls
        expiry_idx = next(
            i for i, c in enumerate(calls) if c == call.set_expiry(90.0)
        )
        wait_idx = next(
            i for i, c in enumerate(calls) if c == call.wait()
        )
        self.assertLess(expiry_idx, wait_idx)

    def test_returns_ok_result(self):
        _, result = self._run()
        self.assertTrue(result["ok"])

    def test_different_timeout_propagated(self):
        future, _ = self._run(timeout=999.0)
        future.set_expiry.assert_called_once_with(999.0)


# ---------------------------------------------------------------------------
# 2. AsyncResultTimeout -> RuntimeError + session marked unhealthy
# ---------------------------------------------------------------------------


class TestAsyncResultTimeoutHandling(unittest.TestCase):
    """AsyncResultTimeout must become RuntimeError and mark session unhealthy."""

    def _run_with_timeout(self, timeout: float = 60.0):
        mgr = _make_session_manager()

        future = MagicMock()
        # wait() raises AsyncResultTimeout to simulate expiry.
        future.wait.side_effect = _AsyncResultTimeout("timed out")
        mgr._conn.root.exec.return_value = future

        return mgr, future

    def test_raises_runtime_error(self):
        mgr, _ = self._run_with_timeout()
        with self.assertRaises(RuntimeError):
            mgr.execute_remote("pass", timeout=60.0)

    def test_runtime_error_message_contains_timeout_value(self):
        mgr, _ = self._run_with_timeout(timeout=77.0)
        try:
            mgr.execute_remote("pass", timeout=77.0)
            self.fail("RuntimeError not raised")
        except RuntimeError as exc:
            self.assertIn("77", str(exc))

    def test_session_marked_unhealthy(self):
        mgr, _ = self._run_with_timeout()
        try:
            mgr.execute_remote("pass", timeout=60.0)
        except RuntimeError:
            pass
        self.assertFalse(mgr.state.healthy)

    def test_last_error_set_on_session(self):
        mgr, _ = self._run_with_timeout(timeout=55.0)
        try:
            mgr.execute_remote("pass", timeout=55.0)
        except RuntimeError:
            pass
        self.assertIsNotNone(mgr.state.last_error)

    def test_last_error_mentions_timeout(self):
        mgr, _ = self._run_with_timeout(timeout=55.0)
        try:
            mgr.execute_remote("pass", timeout=55.0)
        except RuntimeError:
            pass
        self.assertIn("55", mgr.state.last_error or "")

    def test_eof_error_still_marks_unhealthy(self):
        """EOFError path should also mark the session unhealthy (existing behaviour)."""
        mgr = _make_session_manager()
        future = MagicMock()
        future.wait.side_effect = EOFError("connection lost")
        mgr._conn.root.exec.return_value = future

        with self.assertRaises(RuntimeError):
            mgr.execute_remote("pass", timeout=60.0)
        self.assertFalse(mgr.state.healthy)


# ---------------------------------------------------------------------------
# 3. Timeout minimum enforcement
# ---------------------------------------------------------------------------


class TestTimeoutMinimums(unittest.TestCase):
    """All configurable and hard-coded timeout defaults must meet minimums."""

    # -- remote_exec default (60s minimum) -----------------------------------

    def test_remote_exec_default_timeout_at_least_60(self):
        import inspect
        import oom_agent.tools._helpers as helpers_mod

        sig = inspect.signature(helpers_mod.remote_exec)
        default = sig.parameters["timeout"].default
        self.assertGreaterEqual(
            default, 60.0, "remote_exec default timeout must be >= 60s"
        )

    # -- execute_code default (60s minimum) ----------------------------------

    def test_execute_code_default_timeout_at_least_60(self):
        import inspect
        import oom_agent.mcp_server as mcp_mod

        sig = inspect.signature(mcp_mod.execute_code)
        default = sig.parameters["timeout"].default
        self.assertGreaterEqual(
            default, 60.0, "execute_code default timeout must be >= 60s"
        )

    # -- OOM_RPYC_TIMEOUT env-var default (300s minimum, clamped) -----------

    def test_rpyc_timeout_default_env_at_least_300(self):
        """When OOM_RPYC_TIMEOUT is unset the resolved value must be >= 300s."""
        env = {k: v for k, v in os.environ.items() if k != "OOM_RPYC_TIMEOUT"}
        with patch.dict(os.environ, env, clear=True):
            value = max(300.0, float(os.environ.get("OOM_RPYC_TIMEOUT", "300")))
        self.assertGreaterEqual(value, 300.0)

    def test_rpyc_timeout_clamp_rejects_low_env_value(self):
        """Even if OOM_RPYC_TIMEOUT=10 is set, clamping must yield >= 300."""
        with patch.dict(os.environ, {"OOM_RPYC_TIMEOUT": "10"}):
            value = max(300.0, float(os.environ.get("OOM_RPYC_TIMEOUT", "300")))
        self.assertGreaterEqual(value, 300.0)

    def test_rpyc_timeout_clamp_preserves_high_value(self):
        """A value above the minimum must not be reduced."""
        with patch.dict(os.environ, {"OOM_RPYC_TIMEOUT": "600"}):
            value = max(300.0, float(os.environ.get("OOM_RPYC_TIMEOUT", "300")))
        self.assertEqual(value, 600.0)

    # -- OOM_WORKER_TIMEOUT default (300s minimum) ---------------------------

    def test_worker_timeout_default_at_least_300(self):
        env = {k: v for k, v in os.environ.items() if k != "OOM_WORKER_TIMEOUT"}
        with patch.dict(os.environ, env, clear=True):
            value = float(os.environ.get("OOM_WORKER_TIMEOUT", "300"))
        self.assertGreaterEqual(value, 300.0)

    # -- OOM_BOOTSTRAP_TIMEOUT default (300s minimum) ------------------------

    def test_bootstrap_timeout_default_at_least_300(self):
        env = {k: v for k, v in os.environ.items() if k != "OOM_BOOTSTRAP_TIMEOUT"}
        with patch.dict(os.environ, env, clear=True):
            value = float(os.environ.get("OOM_BOOTSTRAP_TIMEOUT", "600"))
        self.assertGreaterEqual(value, 300.0)

    # -- OOM_CONTEXT_TIMEOUT default (300s minimum) --------------------------

    def test_context_timeout_default_at_least_300(self):
        env = {k: v for k, v in os.environ.items() if k != "OOM_CONTEXT_TIMEOUT"}
        with patch.dict(os.environ, env, clear=True):
            value = float(os.environ.get("OOM_CONTEXT_TIMEOUT", "600"))
        self.assertGreaterEqual(value, 300.0)

    # -- Hard-coded call-site timeouts (60s minimum) -------------------------

    def test_pipeline_cache_timeout_at_least_60(self):
        """cache() remote_exec call must use >= 60s."""
        import ast
        import oom_agent.tools.pipeline as pipeline_mod

        src = Path(pipeline_mod.__file__).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "remote_exec":
                    for kw in node.keywords:
                        if kw.arg == "timeout":
                            if isinstance(kw.value, ast.Constant):
                                self.assertGreaterEqual(
                                    kw.value.value,
                                    60.0,
                                    f"remote_exec(timeout=...) < 60 at line {node.lineno}",
                                )

    def test_scene_version_up_timeout_at_least_60(self):
        """scene version_up remote_exec call must use >= 60s."""
        import ast
        import oom_agent.tools.scene as scene_mod

        src = Path(scene_mod.__file__).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "remote_exec":
                    for kw in node.keywords:
                        if kw.arg == "timeout":
                            if isinstance(kw.value, ast.Constant):
                                self.assertGreaterEqual(
                                    kw.value.value,
                                    60.0,
                                    f"remote_exec(timeout=...) < 60 at line {node.lineno}",
                                )


if __name__ == "__main__":
    unittest.main()
