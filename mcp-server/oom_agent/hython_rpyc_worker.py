"""
Houdini rpyc worker script.
Spawned by SessionManager in HYTHON mode. Starts an RPyC server exposing
the hou module and remote code execution, then signals readiness via stdout.
"""

import contextlib
import io
import json
import os
import signal
import sys
import threading
import traceback

import rpyc


class OomService(rpyc.Service):
    """RPyC service exposing the hou module and arbitrary code execution."""

    @property
    def exposed_hou(self):
        import hou
        return hou

    def exposed_exec(self, code: str) -> dict:
        """Execute arbitrary Python code in hython context."""
        import hou

        buf_out = io.StringIO()
        buf_err = io.StringIO()
        ok = True
        ns = {"hou": hou, "__name__": "__main__"}
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            try:
                exec(code, ns, ns)  # noqa: S102
            except Exception:
                ok = False
                traceback.print_exc()

        return {
            "ok": ok,
            "stdout": buf_out.getvalue(),
            "stderr": buf_err.getvalue(),
        }


_port = int(os.environ.get("OOM_HRPYC_PORT", "18811"))

_server = rpyc.ThreadedServer(
    OomService,
    port=_port,
    protocol_config={"allow_public_attrs": True},
)

_thread = threading.Thread(target=_server.start, daemon=True)
_thread.start()

_stdout = sys.__stdout__ or sys.stdout
_stdout.write(json.dumps({"type": "ready", "port": _port}) + "\n")
_stdout.flush()

_stop = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: _stop.set())
_stop.wait()
_server.close()
