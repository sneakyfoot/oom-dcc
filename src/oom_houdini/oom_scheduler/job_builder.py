import getpass
import os
from typing import Optional, Union

import yaml

from oom_kube.helpers import dev_mode, load_environment, normalize_cpu

DEFAULT_CPU = "8"
DEFAULT_MEM_GI = "8"
GPU_TEMPLATE = "pdg-job-gpu.yaml"
CPU_TEMPLATE = "pdg-job-cpu.yaml"
SERVICE_TEMPLATE = "pdg-job-service.yaml"
MQ_TEMPLATE = "pdg-job-mq.yaml"


def _render_template(template: str, context: dict) -> dict:
    env = load_environment(template)
    tpl = env.get_template(template)
    return yaml.safe_load(tpl.render(**context))


def _base_context(name: str, ns: str) -> dict:
    is_dev = dev_mode()
    username = getpass.getuser()
    return {
        "job_name": name,
        "namespace": ns,
        "oom_dev": "'True'" if is_dev else "'False'",
        "username": username,
    }


def _normalize_mem_value(mem_value: Optional[Union[str, int]]) -> str:
    if mem_value is None:
        return DEFAULT_MEM_GI
    if isinstance(mem_value, int):
        return str(mem_value)
    mem = mem_value.strip()
    lower = mem.lower()
    if lower.endswith("gib"):
        mem = mem[:-3]
    elif lower.endswith("gi"):
        mem = mem[:-2]
    elif lower.endswith("gb"):
        mem = mem[:-2]
    return mem or DEFAULT_MEM_GI


def _coerce_gpu(gpu: Optional[Union[str, int]]) -> int:
    if gpu is None:
        return 0
    if isinstance(gpu, int):
        gpu_count = gpu
    else:
        gpu_count = int(str(gpu).strip())
    if gpu_count < 0:
        raise ValueError("GPU count cannot be negative")
    return gpu_count


def _resolve_tag() -> str:
    """
    Resolve pipeline version hash from OOM_TAG environment variable.
    Using 'latest' when not set or dirty.
    """
    tag = (os.environ.get("OOM_TAG") or "").strip()
    # When developing on a dirty tree, fall back to the latest published image
    if not tag or "dirty" in tag:
        return "latest"
    return tag


def build_job_manifest(
    template: Optional[str],
    name: str,
    ns: str,
    command: str,
    pdg_item_name: str,
    pdg_dir: str,
    pdg_scripts: str,
    pdg_item: str,
    pdg_result_server: Optional[str],
    pdg_result_client_id: Optional[str],
    uid: int,
    gid: int,
    cpu: Optional[str],
    mem_gi: Optional[str],
    gpu: Union[int, str, None] = 0,
    priority_class: Optional[str] = "farm-default",
) -> dict:
    gpu_count = _coerce_gpu(gpu)
    resolved_template = template or (GPU_TEMPLATE if gpu_count > 0 else CPU_TEMPLATE)

    cpu_value = cpu if cpu is not None else DEFAULT_CPU
    mem_value = _normalize_mem_value(mem_gi)

    context = _base_context(name, ns)
    # Pass-through selected environment variables from the submitting session
    passthrough_vars = [
        "OOM_PROJECT_ID",
        "OOM_PROJECT_PATH",
        "OOM_SEQUENCE_ID",
        "OOM_SHOT_ID",
        "OOM_SHOT_PATH",
        "CUT_IN",
        "CUT_OUT",
    ]
    for var in passthrough_vars:
        context[var] = os.environ.get(var, "")
    context["OOM_TAG"] = _resolve_tag()
    context.update(
        {
            "uid": uid,
            "gid": gid,
            "cpu_request": normalize_cpu(str(cpu_value)),
            "mem_request": f"{mem_value}Gi",
            "gpu_request": str(gpu_count),
            "priority_class": priority_class or "farm-default",
            "command": command,
            "pdg_item_name": pdg_item_name,
            "pdg_dir": pdg_dir,
            "pdg_scripts": pdg_scripts,
            "pdg_item": pdg_item,
            "pdg_result_server": pdg_result_server or "",
            "pdg_result_client_id": pdg_result_client_id or "",
        }
    )

    return _render_template(resolved_template, context)


def build_service_job_manifest(
    template: Optional[str],
    name: str,
    ns: str,
    command: str,
    pdg_dir: str,
    pdg_scripts: str,
    uid: int,
    gid: int,
    *,
    pdg_item_name: str = "",
    pdg_item: str = "",
    pdg_result_server: Optional[str] = None,
    pdg_result_client_id: Optional[str] = None,
) -> dict:
    resolved_template = template or SERVICE_TEMPLATE

    context = _base_context(name, ns)
    # Pass-through selected environment variables from the submitting session
    import os as _os

    passthrough_vars = [
        "OOM_PROJECT_ID",
        "OOM_PROJECT_PATH",
        "OOM_SEQUENCE_ID",
        "OOM_SHOT_ID",
        "OOM_SHOT_PATH",
        "CUT_IN",
        "CUT_OUT",
    ]
    for var in passthrough_vars:
        context[var] = _os.environ.get(var, "")
    context["OOM_TAG"] = _resolve_tag()
    context.update(
        {
            "uid": uid,
            "gid": gid,
            "command": command,
            "pdg_dir": pdg_dir,
            "pdg_scripts": pdg_scripts,
            "pdg_item_name": pdg_item_name or "",
            "pdg_item": pdg_item or "",
            "pdg_result_server": pdg_result_server or "",
            "pdg_result_client_id": pdg_result_client_id or "",
        }
    )

    return _render_template(resolved_template, context)


def build_mq_job_manifest(
    template: Optional[str],
    name: str,
    ns: str,
    command: str,
    pdg_dir: str,
    pdg_scripts: str,
    uid: int,
    gid: int,
) -> dict:
    resolved_template = template or MQ_TEMPLATE
    return build_service_job_manifest(
        resolved_template,
        name,
        ns,
        command,
        pdg_dir,
        pdg_scripts,
        uid,
        gid,
    )
