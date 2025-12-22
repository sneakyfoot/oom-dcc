import os
import shlex
import textwrap
from typing import Dict, List, Optional, Tuple, TypedDict, cast


DEFAULT_HFS = "/opt/houdini"
DEFAULT_HYTHON = "/opt/houdini/bin/hython"
DEFAULT_PYTHON = "/opt/houdini/python/bin/python"


def _env_truthy(value):
    text = str(value).strip().lower()
    return text in ("1", "true", "yes", "on")


_DEV_VERBOSE = _env_truthy(os.environ.get("OOM_DEV", ""))


def _dprint(*parts):
    if not _DEV_VERBOSE:
        return None
    try:
        print("[OOM_DEV][job_submitter]", *parts)
    except Exception:
        pass
    return None


def _log_exception(context: str, exc: Exception) -> None:
    _dprint(context, "error", repr(exc))
    return None


class _ActiveJobInfo(TypedDict):
    namespace: str
    job_name: str
    work_item_id: int
    work_item_name: str


class JobSubmitter:
    def __init__(self, owner):
        # owner is the scheduler instance
        self._owner = owner

        # allow overriders via environment (falls back to Houdini defaults)
        self._hfs = os.environ.get("HFS", DEFAULT_HFS)
        self._python_bin = os.environ.get("PDG_PYTHON", DEFAULT_PYTHON)
        self._hython_bin = os.environ.get("PDG_HYTHON", DEFAULT_HYTHON)
        self._active_jobs: Dict[Tuple[str, str], _ActiveJobInfo] = {}
        self._batch_api = None
        self._core_api = None
        self._kube_client_mod = None

    def submit_work_item(
        self,
        work_item,
        *,
        mq_client_id: Optional[str],
        result_server: Optional[str],
    ):
        import pdg
        from oom_houdini.oom_scheduler.job_builder import build_job_manifest
        from oom_kube.helpers import load_kube, create_job

        owner = self._owner
        owner.createJobDirsAndSerializeWorkItems(work_item)

        wi_id = str(work_item.id)
        wi_name = str(work_item.name)
        wi_job_name = work_item.stringAttribValue("job_name")
        cook_id = getattr(owner, "_cook_id", "") or ""

        job_name_input_parts = []
        for part in (
            (wi_job_name.strip() if wi_job_name else ""),
            wi_name,
            wi_id,
            cook_id,
        ):
            if part:
                job_name_input_parts.append(part)
        job_name_input = "_".join(job_name_input_parts)
        job_name = self._sanitize_job_name(job_name_input)
        namespace = "dcc"

        item_command = self._resolve_item_command(work_item)
        wrapper_command = self._wrap_with_pdgjobcmd(item_command)

        # Read scheduler parameters for GPU and priority class
        try:
            gpu_flag = 1 if bool(getattr(owner, "get_gpu_enabled", lambda: 0)()) else 0
        except Exception as exc:
            _log_exception("submit_work_item:get_gpu_enabled", exc)
            gpu_flag = 0

        try:
            priority_class = getattr(
                owner, "get_priority_class", lambda: "farm-default"
            )()
        except Exception as exc:
            _log_exception("submit_work_item:get_priority_class", exc)
            priority_class = "farm-default"

        # Resolve optional CPU/RAM requests from scheduler parms
        try:
            cpu_cores = getattr(owner, "get_cpu_cores", lambda: 0)()
        except Exception as exc:
            _log_exception("submit_work_item:get_cpu_cores", exc)
            cpu_cores = 0
        try:
            ram_gb = getattr(owner, "get_ram_gb", lambda: 0)()
        except Exception as exc:
            _log_exception("submit_work_item:get_ram_gb", exc)
            ram_gb = 0

        # Preserve previous defaults when parms are unset
        cpu_arg = str(int(cpu_cores)) if int(cpu_cores) > 0 else "10"
        mem_arg = str(int(ram_gb)) if int(ram_gb) > 0 else "32"

        manifest = build_job_manifest(
            None,
            job_name,
            namespace,
            wrapper_command,
            wi_name,
            owner.workingDir(False) or "",
            owner.scriptDir(False) or "",
            wi_id,
            result_server or "",
            mq_client_id or "",
            1000,
            100,
            # CPU and RAM requests (ints)
            cpu_arg,
            mem_arg,
            gpu=gpu_flag,
            priority_class=priority_class,
        )

        load_kube()
        batch_api = self._ensure_batch_api()
        if batch_api is None:
            raise RuntimeError("Failed to initialize Kubernetes client")
        job_resource = create_job(batch_api, manifest)

        submitted_name = str(
            getattr(getattr(job_resource, "metadata", None), "name", None)
            or manifest.get("metadata", {}).get("name")
            or job_name
        )
        self._active_jobs[(namespace, submitted_name)] = cast(
            _ActiveJobInfo,
            {
                "namespace": namespace,
                "job_name": submitted_name,
                "work_item_id": int(getattr(work_item, "id", 0) or 0),
                "work_item_name": wi_name,
            },
        )

        return pdg.scheduleResult.Succeeded

    def _sanitize_job_name(self, work_item_name: str) -> str:
        text = (work_item_name or "").strip()
        if not text:
            return "pdg-job"

        slug = []
        prev_dash = False
        for ch in text.lower():
            if ch.isalnum():
                slug.append(ch)
                prev_dash = False
                continue
            if not prev_dash:
                slug.append("-")
                prev_dash = True

        value = "".join(slug).strip("-")
        if not value:
            value = "pdg-job"
        return value[:63]

    def _resolve_item_command(self, work_item) -> str:
        import pdg

        command = work_item.platformCommand(pdg.platform.Linux)
        # Ensure PDG Python runs via hython so pdgcmd/pdgjson are available
        command = command.replace("__PDG_PYTHON__", self._hython_bin)
        command = command.replace("__PDG_HYTHON__", self._hython_bin)
        command = command.replace("__PDG_HFS__", self._hfs)
        command = command.replace(
            "__PDG_SCRIPTDIR__", self._owner.scriptDir(False) or ""
        )

        parts = shlex.split(command)
        return " ".join(shlex.quote(arg) for arg in parts)

    def _wrap_with_pdgjobcmd(self, item_command: str) -> str:
        # use the scheduler-provided hython so Houdini modules are available
        hython = self._owner._hythonBin()
        pdgjobcmd = f"{self._hfs}/houdini/python3.11libs/pdgjob/pdgjobcmd.py"

        start_snippet = textwrap.dedent(f"""
            {shlex.quote(hython)} - <<'PDG_START'
            import os, sys
            sys.path.insert(0, os.environ.get('PDG_SCRIPTDIR',''))
            try:
                import pdgcmd
            except ImportError:
                from pdgjob import pdgcmd
            pdgcmd.workItemStartCook(int(os.environ.get('PDG_ITEM_ID', '0')))
            PDG_START
        """).strip()

        success_snippet = textwrap.dedent(f"""
            {shlex.quote(hython)} - <<'PDG_SUCCESS'
            import os, sys
            sys.path.insert(0, os.environ.get('PDG_SCRIPTDIR',''))
            try:
                import pdgcmd
            except ImportError:
                from pdgjob import pdgcmd
            pdgcmd.workItemSuccess(int(os.environ.get('PDG_ITEM_ID', '0')))
            PDG_SUCCESS
        """).strip()

        main_cmd = (
            f"{shlex.quote(hython)} {shlex.quote(pdgjobcmd)} "
            f"--hfs {shlex.quote(self._hfs)} --norpc --keepalive 10 --sendstatus {item_command}"
        )

        script = textwrap.dedent(
            f"""
            set -euo pipefail
            umask 000
            {start_snippet}
            {main_cmd}
            rc=$?
            if [ "$rc" -eq 0 ]; then
                {success_snippet}
                exit 0
            fi
            exit "$rc"
            """
        ).strip()

        return script

    def stop_all_jobs(self, cancel: bool = False) -> None:
        # Best-effort cleanup of worker jobs
        if not self._active_jobs:
            return

        try:
            from oom_kube.helpers import load_kube, delete_job

            load_kube()
            batch_api = self._ensure_batch_api()
            if batch_api is None:
                return
            for info in list(self._active_jobs.values()):
                namespace = info["namespace"]
                name = info["job_name"]
                try:
                    delete_job(batch_api, namespace, name)
                except Exception as exc:
                    _log_exception("stop_all_jobs:delete_job", exc)
                    continue
        finally:
            self._active_jobs.clear()

    def poll_job_updates(self) -> List[dict]:
        if not self._active_jobs:
            return []

        batch_api = self._ensure_batch_api()
        if batch_api is None:
            return []

        updates: List[dict] = []
        client_mod = self._kube_client_mod

        for key, info in list(self._active_jobs.items()):
            namespace = info["namespace"]
            job_name = info["job_name"]

            try:
                job = batch_api.read_namespaced_job_status(
                    name=job_name, namespace=namespace
                )
            except Exception as exc:
                if client_mod is not None:
                    api_exc = getattr(client_mod, "exceptions", None)
                    if (
                        api_exc
                        and isinstance(exc, api_exc.ApiException)
                        and exc.status == 404
                    ):
                        updates.append(
                            {
                                "state": "failed",
                                "work_item_id": info["work_item_id"],
                                "job_name": job_name,
                                "namespace": namespace,
                                "message": "Job not found (deleted)",
                            }
                        )
                        self._active_jobs.pop(key, None)
                        continue
                _log_exception("poll_job_updates:read", exc)
                continue

            status = getattr(job, "status", None)
            outcome = self._evaluate_job_outcome(job, status)
            if not outcome:
                outcome = self._detect_pod_failure(namespace, job_name)
            if not outcome:
                continue

            updates.append(
                {
                    "state": outcome["state"],
                    "work_item_id": info["work_item_id"],
                    "job_name": job_name,
                    "namespace": namespace,
                    "message": outcome.get("message", ""),
                }
            )
            self._active_jobs.pop(key, None)
            # self._delete_job_resource(namespace, job_name)

        return updates

    def _evaluate_job_outcome(self, job, status) -> Optional[dict]:
        if not status:
            return None

        completions = 1
        backoff_limit = None
        spec = getattr(job, "spec", None)
        if spec is not None:
            completions = getattr(spec, "completions", None) or 1
            backoff_limit = getattr(spec, "backoff_limit", None)

        succeeded = int(getattr(status, "succeeded", 0) or 0)
        if succeeded >= int(completions):
            return {"state": "succeeded", "message": "Job completed"}

        conditions = getattr(status, "conditions", None) or []
        for condition in conditions:
            ctype = getattr(condition, "type", "")
            cstatus = (getattr(condition, "status", "") or "").lower()
            if cstatus != "true":
                continue
            if ctype == "Complete":
                return {"state": "succeeded", "message": "Job completed"}
            if ctype == "Failed":
                reason = getattr(condition, "reason", "") or ""
                message = getattr(condition, "message", "") or ""
                return {
                    "state": "failed",
                    "message": reason or message or "Job failed",
                }

        failed = int(getattr(status, "failed", 0) or 0)
        if backoff_limit is not None and failed > int(backoff_limit):
            return {"state": "failed", "message": "Backoff limit exceeded"}

        return None

    def _ensure_batch_api(self):
        if self._batch_api is not None:
            return self._batch_api
        try:
            from kubernetes import client
            from oom_kube.helpers import load_kube
        except Exception as exc:
            _log_exception("_ensure_batch_api:import", exc)
            return None
        try:
            load_kube()
            self._batch_api = client.BatchV1Api()
            self._kube_client_mod = client
        except Exception as exc:
            _log_exception("_ensure_batch_api:init", exc)
            self._batch_api = None
        return self._batch_api

    def _ensure_core_api(self):
        if self._core_api is not None:
            return self._core_api
        try:
            from kubernetes import client
            from oom_kube.helpers import load_kube
        except Exception as exc:
            _log_exception("_ensure_core_api:import", exc)
            return None
        try:
            load_kube()
            self._core_api = client.CoreV1Api()
            self._kube_client_mod = client
        except Exception as exc:
            _log_exception("_ensure_core_api:init", exc)
            self._core_api = None
        return self._core_api

    def _delete_job_resource(self, namespace: str, job_name: str) -> None:
        if not namespace or not job_name:
            return
        batch_api = self._ensure_batch_api()
        if batch_api is None:
            return
        try:
            from oom_kube.helpers import delete_job

            delete_job(batch_api, namespace, job_name)
        except Exception as exc:
            _log_exception("delete_job_resource", exc)

    def _detect_pod_failure(self, namespace: str, job_name: str) -> Optional[dict]:
        core_api = self._ensure_core_api()
        if core_api is None:
            return None
        label_selector = f"oom-bubble-job={job_name}"
        try:
            pods = core_api.list_namespaced_pod(
                namespace=namespace,
                label_selector=label_selector,
            )
        except Exception as exc:
            _log_exception("_detect_pod_failure:list", exc)
            return None

        for pod in getattr(pods, "items", []) or []:
            statuses = (
                getattr(getattr(pod, "status", None), "container_statuses", None) or []
            )
            for status in statuses:
                state = getattr(status, "state", None)
                terminated = getattr(state, "terminated", None)
                if terminated and (terminated.reason or "").lower() == "oomkilled":
                    container_name = getattr(status, "name", "<container>")
                    return {
                        "state": "failed",
                        "message": f"{container_name} hit OOMKilled",
                    }
        return None
