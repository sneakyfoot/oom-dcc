"""
Single runtime session management.
Tracks one persistent hython worker per server instance.
"""

from __future__ import annotations

import asyncio
import json
import os
import select
import socket
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import rpyc


def _hython_path() -> str:
    hfs = os.environ.get("HFS")
    if not hfs:
        raise RuntimeError("HFS environment variable not set")
    hython = f"{hfs}/bin/hython"
    if not Path(hython).exists():
        raise RuntimeError(f"Houdini hython not found at {hython}")
    return hython


def _worker_script_path() -> str:
    return str(Path(__file__).parent / "hython_rpyc_worker.py")


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class ConnectionMode(Enum):
    HYTHON = "hython"  # Spawn hython subprocess, start rpyc server, connect
    LIVE = "live"      # Connect to existing Houdini GUI hrpyc server


@dataclass
class RuntimeState:
    initialized: bool = False
    created_at: Optional[str] = None
    project: Optional[str] = None
    sequence: Optional[str] = None
    shot: Optional[str] = None
    paths: dict[str, str] = field(default_factory=dict)
    env_vars: dict[str, str] = field(default_factory=dict)
    hip_path: Optional[str] = None
    hip_loaded: bool = False
    healthy: bool = False
    worker_pid: Optional[int] = None
    last_error: Optional[str] = None
    mode: Optional[str] = None


class SessionManager:
    """Manage the single runtime session and its hython worker."""

    def __init__(self) -> None:
        self._state = RuntimeState()
        self._process: Optional[subprocess.Popen[str]] = None
        self._conn: Optional[rpyc.Connection] = None
        self._hou: Optional[Any] = None
        self._remote_exec: Optional[Any] = None  # callable proxy for LIVE mode
        self._mode: Optional[ConnectionMode] = None
        self._exec_lock = asyncio.Lock()
        self._stderr_buffer: deque[str] = deque(maxlen=200)
        self._stderr_thread: Optional[threading.Thread] = None

    @property
    def state(self) -> RuntimeState:
        return self._state

    def is_initialized(self) -> bool:
        return self._state.initialized

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_stderr_forever(self) -> None:
        if self._process is None or self._process.stderr is None:
            return
        for line in self._process.stderr:
            self._stderr_buffer.append(line.rstrip("\n"))

    def _readline_from_process(self, timeout: float) -> Optional[str]:
        if self._process is None or self._process.stdout is None:
            return None
        fd = self._process.stdout.fileno()
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None
        line = self._process.stdout.readline()
        return line.strip() if line else None

    # ------------------------------------------------------------------
    # Initialize
    # ------------------------------------------------------------------

    def initialize(
        self,
        context_info: dict[str, Any],
        mode: ConnectionMode = ConnectionMode.HYTHON,
        host: str = "localhost",
        port: int = 18811,
    ) -> RuntimeState:
        if self._state.initialized:
            raise RuntimeError(
                "Session already active; call agent.destroy_session first"
            )

        self._mode = mode
        if mode == ConnectionMode.HYTHON:
            self._initialize_hython(context_info)
        else:
            self._initialize_live(context_info, host, port)

        return self._state

    def _initialize_hython(self, context_info: dict[str, Any]) -> None:
        env = os.environ.copy()
        env.update(context_info.get("env_vars", {}))
        # Hython runs python3.11; swap in OOM_PYTHONPATH so it doesn't get
        # the MCP server's python3.13 packages on PYTHONPATH.
        oom_pythonpath = env.get("OOM_PYTHONPATH")
        if oom_pythonpath:
            env["PYTHONPATH"] = oom_pythonpath
        env["PYTHONUNBUFFERED"] = "1"

        port = int(env.get("OOM_HRPYC_PORT") or "0") or _find_free_port()
        env["OOM_HRPYC_PORT"] = str(port)

        process = subprocess.Popen(
            [_hython_path(), "--indie", "-u", _worker_script_path()],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self._process = process
        self._stderr_thread = threading.Thread(
            target=self._read_stderr_forever, daemon=True
        )
        self._stderr_thread.start()

        worker_timeout = float(os.environ.get("OOM_WORKER_TIMEOUT", "300"))
        deadline = time.monotonic() + worker_timeout
        ready_payload = None

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            line = self._readline_from_process(timeout=min(remaining, 5.0))
            if line is None:
                if process.poll() is not None:
                    self.shutdown(force=True)
                    raise RuntimeError("Hython worker exited before ready")
                continue
            try:
                ready_payload = json.loads(line)
                break
            except Exception:
                continue

        if ready_payload is None:
            self.shutdown(force=True)
            raise RuntimeError("Timed out waiting for hython worker startup")

        if ready_payload.get("type") != "ready":
            self.shutdown(force=True)
            raise RuntimeError(
                f"Unexpected startup payload from hython worker: {ready_payload}"
            )

        actual_port = ready_payload.get("port", port)
        rpyc_timeout = float(os.environ.get("OOM_RPYC_TIMEOUT", "30"))
        self._conn = rpyc.connect(
            "localhost",
            actual_port,
            config={"sync_request_timeout": rpyc_timeout, "allow_public_attrs": True},
        )
        self._hou = self._conn.root.hou

        self._state = RuntimeState(
            initialized=True,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            project=context_info.get("project"),
            sequence=context_info.get("sequence"),
            shot=context_info.get("shot"),
            paths=context_info.get("paths", {}),
            env_vars=context_info.get("env_vars", {}),
            healthy=True,
            worker_pid=process.pid,
            mode="hython",
        )

    def _initialize_live(
        self, context_info: dict[str, Any], host: str, port: int
    ) -> None:
        rpyc_timeout = float(os.environ.get("OOM_RPYC_TIMEOUT", "30"))
        # hrpyc starts a SlaveService -- connect with rpyc.classic so that
        # conn.modules, conn.execute, and conn.builtins are available.
        self._conn = rpyc.classic.connect(host, port)
        self._conn._config["sync_request_timeout"] = rpyc_timeout  # type: ignore[index]
        self._hou = self._conn.modules.hou

        # Inject a stdout/stderr-capturing exec helper into the remote namespace
        # so execute_remote() has the same visibility as HYTHON mode.
        self._conn.execute(
            "import contextlib as _oom_cl, io as _oom_io, traceback as _oom_tb\n"
            "def _oom_exec(code):\n"
            "    import hou\n"
            "    buf_out, buf_err = _oom_io.StringIO(), _oom_io.StringIO()\n"
            "    ok = True\n"
            "    ns = {'hou': hou, '__name__': '__main__'}\n"
            "    with _oom_cl.redirect_stdout(buf_out), _oom_cl.redirect_stderr(buf_err):\n"
            "        try:\n"
            "            exec(code, ns, ns)\n"
            "        except Exception:\n"
            "            ok = False\n"
            "            _oom_tb.print_exc(file=buf_err)\n"
            "    return {'ok': ok, 'stdout': buf_out.getvalue(), 'stderr': buf_err.getvalue()}\n"
        )
        self._remote_exec = self._conn.eval("_oom_exec")

        # Try to read existing context from the live session
        project = context_info.get("project")
        sequence = context_info.get("sequence")
        shot = context_info.get("shot")
        try:
            ctx = self._hou.session.oom_context
            if ctx is not None and project is None:
                project = str(ctx.project.get("name", "")) or None
        except Exception:
            pass

        self._state = RuntimeState(
            initialized=True,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            project=project,
            sequence=sequence,
            shot=shot,
            paths=context_info.get("paths", {}),
            env_vars=context_info.get("env_vars", {}),
            healthy=True,
            mode="live",
        )

    # ------------------------------------------------------------------
    # RPC access
    # ------------------------------------------------------------------

    def get_hou(self) -> Any:
        """Return the hou proxy object for direct RPC calls."""
        if self._hou is None:
            raise RuntimeError("Session not initialized; call agent.create_session first")
        return self._hou

    def execute_remote(self, code: str, timeout: float) -> dict[str, Any]:
        """Execute arbitrary Python code in the remote hython session."""
        if self._conn is None:
            raise RuntimeError("Session not initialized; call agent.create_session first")
        if not self._state.initialized:
            raise RuntimeError("Session not initialized; call agent.create_session first")

        try:
            if self._remote_exec is not None:
                # LIVE mode: call the _oom_exec helper injected at connect time.
                # Returns a netref dict with ok/stdout/stderr -- same shape as OomService.
                result = self._remote_exec(code)
            else:
                # HYTHON mode: OomService exposes exec() with stdout/stderr capture.
                async_exec = rpyc.async_(self._conn.root.exec)
                future = async_exec(code)
                future.wait(timeout=timeout)
                result = future.value

            return {
                "ok": bool(result["ok"]),
                "stdout": str(result["stdout"] or ""),
                "stderr": str(result["stderr"] or ""),
            }
        except EOFError:
            self._mark_unhealthy("rpyc connection lost")
            raise RuntimeError("rpyc connection to hython worker was lost")

    async def execute(self, code: str, timeout: float) -> dict[str, Any]:
        """Async wrapper for execute_remote (preserves existing interface)."""
        async with self._exec_lock:
            return await asyncio.to_thread(self.execute_remote, code, timeout)

    def _check_connection(self) -> bool:
        if self._conn is None:
            return False
        try:
            self._conn.ping()
            return True
        except Exception:
            return False

    def _mark_unhealthy(self, error: str) -> None:
        self._state.healthy = False
        self._state.last_error = error

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def set_hip_state(self, hip_path: Optional[str], loaded: bool) -> None:
        self._state.hip_path = hip_path
        self._state.hip_loaded = loaded

    def stderr_tail(self) -> list[str]:
        return list(self._stderr_buffer)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self, force: bool = False) -> bool:
        did_shutdown = False

        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._hou = None
            self._remote_exec = None
            did_shutdown = True

        if self._process is not None:
            process = self._process
            if process.poll() is None:
                if force:
                    process.kill()
                    process.wait(timeout=5)
                else:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            self._process = None
            did_shutdown = True

        self._mode = None
        self._state = RuntimeState()
        return did_shutdown


_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
