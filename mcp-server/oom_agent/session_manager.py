"""
Single runtime session management.
Tracks one persistent hython worker per server instance.
"""

from __future__ import annotations

import asyncio
import json
import os
import select
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


def _hython_path() -> str:
    hfs = os.environ.get("HFS")
    if not hfs:
        raise RuntimeError("HFS environment variable not set")
    hython = f"{hfs}/bin/hython"
    if not Path(hython).exists():
        raise RuntimeError(f"Houdini hython not found at {hython}")
    return hython


def _worker_source() -> str:
    return """
import contextlib
import io
import json
import sys
import traceback

_globals = {"__name__": "__main__"}

def _emit(payload):
    sys.__stdout__.write(json.dumps(payload) + "\\n")
    sys.__stdout__.flush()

_emit({"type": "ready"})

for _line in sys.stdin:
    _line = _line.strip()
    if not _line:
        continue

    _request_id = None
    try:
        _request = json.loads(_line)
        _request_id = _request.get("id")
    except Exception as exc:
        _emit({"id": _request_id, "ok": False, "stdout": "", "stderr": f"Invalid request: {exc}"})
        continue

    if _request.get("op") == "shutdown":
        _emit({"id": _request_id, "ok": True, "stdout": "", "stderr": ""})
        break

    _code = _request.get("code") or ""
    _stdout = io.StringIO()
    _stderr = io.StringIO()
    _ok = True

    with contextlib.redirect_stdout(_stdout), contextlib.redirect_stderr(_stderr):
        try:
            exec(_code, _globals, _globals)
        except Exception:
            _ok = False
            traceback.print_exc()

    _emit(
        {
            "id": _request_id,
            "ok": _ok,
            "stdout": _stdout.getvalue(),
            "stderr": _stderr.getvalue(),
        }
    )
"""


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


class SessionManager:
    """Manage the single runtime session and its hython worker."""

    def __init__(self) -> None:
        self._state = RuntimeState()
        self._process: Optional[subprocess.Popen[str]] = None
        self._exec_lock = asyncio.Lock()
        self._request_counter = 0
        self._stderr_buffer: deque[str] = deque(maxlen=200)
        self._stderr_thread: Optional[threading.Thread] = None

    @property
    def state(self) -> RuntimeState:
        return self._state

    def is_initialized(self) -> bool:
        return self._state.initialized

    def _read_stderr_forever(self) -> None:
        if self._process is None or self._process.stderr is None:
            return
        for line in self._process.stderr:
            self._stderr_buffer.append(line.rstrip("\n"))

    def initialize(self, context_info: dict[str, Any]) -> RuntimeState:
        if self._state.initialized:
            raise RuntimeError(
                "Session already active; call agent.destroy_session first"
            )

        env = os.environ.copy()
        env.update(context_info.get("env_vars", {}))
        # Hython runs python3.11; swap in OOM_PYTHONPATH so it doesn't get
        # the MCP server's python3.13 packages on PYTHONPATH.
        oom_pythonpath = env.get("OOM_PYTHONPATH")
        if oom_pythonpath:
            env["PYTHONPATH"] = oom_pythonpath
        env["PYTHONUNBUFFERED"] = "1"

        process = subprocess.Popen(
            [_hython_path(), "--indie", "-u", "-c", _worker_source()],
            stdin=subprocess.PIPE,
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

        ready_payload = self._read_json_response(timeout=30.0)
        if ready_payload is None:
            self.shutdown(force=True)
            raise RuntimeError("Timed out waiting for hython worker startup")

        if ready_payload.get("type") != "ready":
            self.shutdown(force=True)
            raise RuntimeError(
                f"Unexpected startup payload from hython worker: {ready_payload}"
            )

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
        )
        return self._state

    def _readline_with_timeout(self, timeout: float) -> Optional[str]:
        if self._process is None or self._process.stdout is None:
            return None
        fd = self._process.stdout.fileno()
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None
        line = self._process.stdout.readline()
        if not line:
            return None
        return line.strip()

    def _read_json_response(
        self,
        timeout: float,
        request_id: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None

            line = self._readline_with_timeout(timeout=remaining)
            if line is None:
                return None

            try:
                payload = json.loads(line)
            except Exception:
                continue

            if request_id is None or payload.get("id") == request_id:
                return payload

    async def execute(self, code: str, timeout: float) -> dict[str, Any]:
        async with self._exec_lock:
            return await asyncio.to_thread(self._execute_blocking, code, timeout)

    def _execute_blocking(self, code: str, timeout: float) -> dict[str, Any]:
        if not self._state.initialized:
            raise RuntimeError(
                "Session not initialized; call agent.create_session first"
            )
        if self._process is None or self._process.poll() is not None:
            self._mark_unhealthy("Hython worker is not running")
            raise RuntimeError("Hython worker is not running")
        if self._process.stdin is None:
            self._mark_unhealthy("Hython worker stdin unavailable")
            raise RuntimeError("Hython worker stdin unavailable")

        self._request_counter += 1
        request_id = self._request_counter
        payload = {"id": request_id, "op": "exec", "code": code}
        self._process.stdin.write(json.dumps(payload) + "\n")
        self._process.stdin.flush()

        response = self._read_json_response(timeout=timeout, request_id=request_id)
        if response is None:
            self._mark_unhealthy(f"Execution timed out after {timeout} seconds")
            raise TimeoutError(f"Execution timed out after {timeout} seconds")

        return {
            "ok": bool(response.get("ok", False)),
            "stdout": str(response.get("stdout") or ""),
            "stderr": str(response.get("stderr") or ""),
        }

    def _mark_unhealthy(self, error: str) -> None:
        self._state.healthy = False
        self._state.last_error = error

    def set_hip_state(self, hip_path: Optional[str], loaded: bool) -> None:
        self._state.hip_path = hip_path
        self._state.hip_loaded = loaded

    def shutdown(self, force: bool = False) -> bool:
        if self._process is None:
            self._state = RuntimeState()
            return False

        process = self._process
        did_shutdown = True

        if process.poll() is None and not force and process.stdin:
            try:
                self._request_counter += 1
                process.stdin.write(
                    json.dumps({"id": self._request_counter, "op": "shutdown"}) + "\n"
                )
                process.stdin.flush()
                self._readline_with_timeout(timeout=2.0)
            except Exception:
                pass

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        self._process = None
        self._state = RuntimeState()
        return did_shutdown

    def stderr_tail(self) -> list[str]:
        return list(self._stderr_buffer)


_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
