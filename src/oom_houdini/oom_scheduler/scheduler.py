import json
import os
import time
import uuid

import pdg
from pdg.scheduler import PyScheduler
from pdg.job.eventdispatch import EventDispatchMixin

from .mq import MQManager
from .job_submitter import JobSubmitter


# Debug / Dev mode helpers
def _env_truthy(value):
    # Normalize env var values like 1/true/yes/on
    text = str(value).strip().lower()

    return text in ("1", "true", "yes", "on")


_DEV_VERBOSE = _env_truthy(os.environ.get("OOM_DEV", ""))


def _dprint(*parts):
    # Print debug info only when OOM_DEV is enabled
    if not _DEV_VERBOSE:
        return None

    try:
        print("[OOM_DEV][oom_scheduler]", *parts)
    except Exception:
        # Avoid raising from debug printing
        pass

    return None


def _log_exception(context: str, exc: Exception) -> None:
    try:
        _dprint(context, "error", repr(exc))
    except Exception:
        pass
    return None


def _register_scheduler_instance(instance):
    return None


class oom_scheduler(EventDispatchMixin, PyScheduler):
    """
    K8s scheduler implementation
    """

    def __init__(self, scheduler, name):
        """
        __init__(self, pdg.Scheduler) -> NoneType

        Initializes the Scheduler with a C++ scheduler reference and name
        """
        PyScheduler.__init__(self, scheduler, name)
        EventDispatchMixin.__init__(self)

        # Track per-session storage id
        self._cook_id = None

        _register_scheduler_instance(self)

        # MQ manager state
        self._mq = MQManager(self)
        self._job_submitter = JobSubmitter(self)

        # Debug: constructor details
        _dprint("__init__", f"name={name}")

        return None

    @classmethod
    def templateName(cls):
        return "oom_scheduler"

    @classmethod
    def templateBody(cls):
        # Define PDG UI parms for GPU and Priority (0=default, 1=low, 2=high)
        return json.dumps(
            {
                "name": "oom_scheduler",
                "parameters": [
                    {
                        "name": "gpu",
                        "type": "bool",
                        "size": 1,
                    },
                    {
                        "name": "priority",
                        "type": "int",
                        "size": 1,
                    },
                    # Houdini parms for CPU cores and RAM (GiB)
                    {
                        "name": "cpu",
                        "type": "int",
                        "size": 1,
                    },
                    {
                        "name": "ram",
                        "type": "int",
                        "size": 1,
                    },
                ],
            }
        )

    def onTransferFile(self, file_path):
        # Placeholder callback
        _dprint("onTransferFile", file_path)
        return None

    def submitAsJob(self, graph_file, node_path):
        # Placeholder callback
        _dprint("submitAsJob", graph_file, node_path)
        return None

    def onSchedule(self, work_item):
        # Defer scheduling until MQ is ready so PDG_RESULT_SERVER is valid
        def _wi_repr(wi):
            # Safe representation for work items
            try:
                name = getattr(wi, "name", None)
                if name:
                    return f"WorkItem(name={name})"
                wid = getattr(wi, "id", None)
                if wid is not None:
                    return f"WorkItem(id={wid})"
            except Exception as exc:
                _log_exception("_wi_repr", exc)
            return str(wi)

        _dprint("onSchedule:start", _wi_repr(work_item))

        try:
            if self._mq.is_waiting() or not self._mq.is_ready():
                _dprint(
                    "onSchedule:deferred",
                    f"ready={self._mq.is_ready()}",
                    f"waiting={self._mq.is_waiting()}",
                )
                return pdg.scheduleResult.Deferred
        except Exception as exc:
            _log_exception("onSchedule:deferred", exc)
            _dprint("onSchedule:deferred", "MQ state check failed")
            return pdg.scheduleResult.Deferred

        try:
            result = self._job_submitter.submit_work_item(
                work_item,
                mq_client_id=getattr(self._mq, "client_id", "") or "",
                result_server=self.workItemResultServerAddr() or "",
            )
            _dprint(
                "onSchedule:submitted",
                _wi_repr(work_item),
                f"client_id={getattr(self._mq, 'client_id', '') or ''}",
                f"result_server={self.workItemResultServerAddr() or ''}",
                f"result={result}",
            )
        except Exception as exc:
            try:
                self.cookError(f"Failed submitting work item: {exc}")
            except Exception as inner_exc:
                _log_exception("onSchedule:cookError", inner_exc)
            _dprint("onSchedule:failed", repr(exc))
            return pdg.scheduleResult.Failed

        _dprint("onSchedule:done", _wi_repr(work_item))
        return result

    def onScheduleStatic(self, dependencies, dependents, ready_items):
        # Placeholder callback
        return None

    def onStart(self):
        from oom_houdini.oom_scheduler.storage import ensure_dirs

        if not self._cook_id:
            self._cook_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"

        # Make sure shared storage for this cook exists
        base, scripts = ensure_dirs(self._cook_id)

        # Store directories
        self.setWorkingDir(base, base)
        self.setTempDir(base, base)
        self.setScriptDir(scripts, scripts)

        # Debug: start info
        _dprint(
            "onStart", f"cook_id={self._cook_id}", f"base={base}", f"scripts={scripts}"
        )

        # Spin up MQ server for the session
        try:
            _dprint("onStart:mq", "starting MQ")
            self._mq.start()
        except Exception as exc:
            try:
                self.cookError(f"Failed starting PDGMQ: {exc}")
            except Exception as inner_exc:
                _log_exception("onStart:cookError", inner_exc)
            _dprint("onStart:mq", "failed", repr(exc))

        return None

    def onStop(self):
        # Placeholder callback while the scheduler logic is under development.
        try:
            _dprint("onStop", "stopping all jobs")
            self._job_submitter.stop_all_jobs()
        except Exception as exc:
            _log_exception("onStop:jobs", exc)

        # try:
        #     _dprint("onStop:mq", "stopping MQ")
        #     self._mq.stop(False)
        # except Exception:
        #     pass

        _dprint("onStop", "clearing cook id", f"was={self._cook_id}")
        self._cook_id = None
        return None

    def onStartCook(self, static, cook_set):
        # Ensure we have an id if onStart was skipped (shouldn't happen but PDG can reload)
        if not self._cook_id:
            self._cook_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
            _dprint("onStartCook", f"new cook_id={self._cook_id}")

        # Ensure PDG dirs exist (in case onStart didn't run)
        try:
            from oom_houdini.oom_scheduler.storage import ensure_dirs

            base = self.workingDir(False)
            scripts = self.scriptDir(False)
            if (
                not base
                or not os.path.isdir(base)
                or not scripts
                or not os.path.isdir(scripts)
            ):
                base, scripts = ensure_dirs(self._cook_id)
                self.setWorkingDir(base, base)
                self.setTempDir(base, base)
                self.setScriptDir(scripts, scripts)
            _dprint("onStartCook:dirs", f"base={base}", f"scripts={scripts}")
        except Exception as exc:
            _dprint("onStartCook:dirs", "ensure_dirs failed")
            _log_exception("onStartCook:dirs", exc)

        # Ensure MQ server remains available for the cook
        try:
            if not self._mq.is_ready() and not self._mq.is_waiting():
                _dprint("onStartCook:mq", "MQ not ready -> starting")
                self._mq.start()
            else:
                _dprint("onStartCook:mq", "MQ already running or pending")
        except Exception as e:
            try:
                self.cookError(f"Failed starting PDGMQ: {e}")
            except Exception as inner_exc:
                _log_exception("onStartCook:cookError", inner_exc)
            _dprint("onStartCook:mq", "failed", repr(e))
            return None

        _dprint("onStartCook", "done")
        return None

    def onStopCook(self, cancel):
        try:
            if cancel is True:
                _dprint("onStopCook:jobs", f"stopping jobs cancel={bool(cancel)}")
                self._job_submitter.stop_all_jobs(cancel)
            else:
                _dprint("onStopCook: doing nothing")
        except Exception as exc:
            _log_exception("onStopCook", exc)

        _dprint("onStopCook", "done")
        return None

    def onTick(self):
        # Let MQ manager poll without blocking the UI
        try:
            # _dprint("onTick", "poll")
            self._mq.poll()
        except Exception as exc:
            _log_exception("onTick:mq", exc)

        try:
            updates = self._job_submitter.poll_job_updates()
            for update in updates:
                state = update.get("state")
                job_name = update.get("job_name")
                wi_id = update.get("work_item_id")
                if state == "failed" and wi_id is not None:
                    try:
                        self.onWorkItemFailed(int(wi_id), -1)
                        _dprint(
                            "onTick:job_failed",
                            f"job={job_name}",
                            f"wi_id={wi_id}",
                            update.get("message", ""),
                        )
                    except Exception as exc:
                        _log_exception("onTick:onWorkItemFailed", exc)
                elif state == "succeeded":
                    _dprint(
                        "onTick:job_succeeded",
                        f"job={job_name}",
                        f"wi_id={wi_id}",
                    )
        except Exception as exc:
            _log_exception("onTick:jobs", exc)
        return None

    def getLogURI(self, work_item):
        # Placeholder callback
        return None

    def getStatusURI(self, work_item):
        # Placeholder callback
        return None

    def endSharedServer(self, sharedserver_name):
        # Placeholder callback
        return None

    def applicationBin(self, name, work_item):
        if name == "python":
            path = self._pythonBin()
            _dprint("applicationBin", name, path)
            return path
        elif name == "hython":
            path = self._hythonBin()
            _dprint("applicationBin", name, path)
            return path

    # Function Defs
    def _pythonBin(self) -> str:
        # Use Houdini's shipped Python
        hfs = os.environ.get("HFS", "/opt/houdini")
        return f"{hfs}/python/bin/python"

    def _hythonBin(self) -> str:
        hfs = os.environ.get("HFS", "/opt/houdini")
        return f"{hfs}/bin/hython"

    # Parm helpers (PDG parm first, then scheduler node parm)
    def _scheduler_parm(self, name, default=None):
        # Try PDG parameter interface: self['name']
        try:
            pdg_parm = self[name]
            if pdg_parm is not None:
                # Prefer integer for numeric parms to avoid bool coercion of non-zero
                for method in ("evaluateInt", "evaluateBool", "evaluateString"):
                    fn = getattr(pdg_parm, method, None)
                    if callable(fn):
                        return fn()
        except Exception as exc:
            _log_exception("_scheduler_parm", exc)

        # Default
        return default

    def get_gpu_enabled(self) -> int:
        # Return 1 if gpu parm is enabled, else 0
        val = self._scheduler_parm("gpu", 0)
        return 1 if bool(val) else 0

    def get_priority_class(self) -> str:
        # Map 0->farm-default, 1->farm-low, 2->farm-high
        level = self._scheduler_parm("priority", 0)
        try:
            level = int(level)
        except Exception as exc:
            _log_exception("get_priority_class", exc)
            level = 0
        # clamp to 0..2
        if level < 0:
            level = 0
        if level > 2:
            level = 2
        if level == 1:
            return "farm-low"
        if level == 2:
            return "farm-high"
        return "farm-default"

    def get_cpu_cores(self) -> int:
        # Integer cores; 0 or less means use defaults
        value = self._scheduler_parm("cpu", 0)
        try:
            cores = int(value)
        except Exception as exc:
            _log_exception("get_cpu_cores", exc)
            cores = 0
        return cores if cores > 0 else 0

    def get_ram_gb(self) -> int:
        # Integer GiB; 0 or less means use defaults
        value = self._scheduler_parm("ram", 0)
        try:
            gib = int(value)
        except Exception as exc:
            _log_exception("get_ram_gb", exc)
            gib = 0
        return gib if gib > 0 else 0

    def _shutdown_cleanup(self, source: str = "manual") -> None:
        return None


def registerTypes(type_registry):
    type_registry.registerScheduler(oom_scheduler)
