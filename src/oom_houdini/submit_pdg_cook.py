#!/usr/bin/env python3
"""
Submit a headless PDG cook using the Kubernetes controller job.

This module intentionally lives outside `oom_scheduler` to avoid importing
Houdini/PDG during a simple submit action.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import yaml

from oom_kube.helpers import dev_mode, load_environment, create_job, load_kube


DEFAULT_NAMESPACE = "dcc"
DEFAULT_HFS = "/opt/houdini"
SERVICE_TEMPLATE = "pdg-job-service.yaml"


def sanitize_job_name(text: str) -> str:
    slug = []
    prev_dash = False
    for ch in text.lower():
        if ch.isalnum():
            slug.append(ch)
            prev_dash = False
        else:
            if not prev_dash:
                slug.append("-")
            prev_dash = True
    value = "".join(slug).strip("-")
    if not value:
        value = "pdg-ctrl"
    return value[:63]


def parse_mem_arg(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    mem = value.strip()
    lower = mem.lower()
    if lower.endswith("gib"):
        mem = mem[:-3]
    elif lower.endswith("gi"):
        mem = mem[:-2]
    elif lower.endswith("gb"):
        mem = mem[:-2]
    return mem or None


def parse_gpu_arg(value: Optional[str]) -> int:
    if value is None or str(value).strip() == "":
        return 0
    try:
        count = int(value)
    except ValueError as exc:
        raise ValueError("GPU count must be an integer") from exc
    if count != 0:
        raise ValueError("Service jobs do not request GPUs; pass 0 for --gpu")
    return 0


def resolve_uid_gid() -> tuple[int, int]:
    uid = os.environ.get("OOM_PDG_UID")
    gid = os.environ.get("OOM_PDG_GID")
    try:
        uid_val = int(uid) if uid is not None else os.getuid()
    except ValueError as exc:
        raise ValueError("OOM_PDG_UID must be an integer") from exc
    try:
        gid_val = int(gid) if gid is not None else os.getgid()
    except ValueError as exc:
        raise ValueError("OOM_PDG_GID must be an integer") from exc
    return uid_val, gid_val


def ensure_dirs(cook_id: str) -> tuple[str, str]:
    hip = os.environ.get("HIP", "").strip()
    base = os.path.join(hip, f"pdgtemp_{cook_id}")
    scripts = os.path.join(base, "scripts")
    Path(base).mkdir(parents=True, exist_ok=True)
    Path(scripts).mkdir(parents=True, exist_ok=True)
    return base, scripts


def _render_template(template: str, context: dict) -> dict:
    env = load_environment(template)
    tpl = env.get_template(template)
    return yaml.safe_load(tpl.render(**context))


def build_service_job_manifest(
    name: str,
    ns: str,
    command: str,
#    pdg_dir: str,
#    pdg_scripts: str,
    uid: int,
    gid: int,
    *,
#    pdg_item_name: str = "",
#    pdg_item: str = "",
#    pdg_result_server: Optional[str] = None,
#    pdg_result_client_id: Optional[str] = None,
    hhp: Optional[str] = None,
) -> dict:
    # Base context without touching the scheduler package
    is_dev = dev_mode()
    context = {
        "job_name": name,
        "namespace": ns,
        "oom_repo": "oom-repo-pvc" if is_dev else "oom-repo-prod-pvc",
        "oom_dev": "'True'" if is_dev else "'False'",
        # Tag for the runtime image (falls back to latest if unset/dirty)
        "OOM_TAG": "latest" if "dirty" in os.environ.get("OOM_TAG", "") or not os.environ.get("OOM_TAG") else os.environ["OOM_TAG"],
        "uid": uid,
        "gid": gid,
        "command": command,
#        "pdg_dir": pdg_dir,
#        "pdg_scripts": pdg_scripts,
#        "pdg_item_name": pdg_item_name or "",
#        "pdg_item": pdg_item or "",
#        "pdg_result_server": pdg_result_server or "",
#        "pdg_result_client_id": pdg_result_client_id or "",
        "hhp": hhp or "",
    }
    # Pass-through selected environment variables from the submitting session
    for var in (
        "OOM_PROJECT_ID",
        "OOM_PROJECT_PATH",
        "OOM_SEQUENCE_ID",
        "OOM_SHOT_ID",
        "OOM_SHOT_PATH",
        "CUT_IN",
        "CUT_OUT",
    ):
        context[var] = os.environ.get(var, "")
    return _render_template(SERVICE_TEMPLATE, context)


def ensure_pdg_dirs(hip_path: Path, cook_id: str) -> tuple[str, str]:
    hip_dir = hip_path.parent.as_posix()
    prev = os.environ.get("HIP")
    os.environ["HIP"] = hip_dir
    try:
        base, scripts = ensure_dirs(cook_id)
    finally:
        if prev is None:
            os.environ.pop("HIP", None)
        else:
            os.environ["HIP"] = prev
    return base, scripts


def build_controller_cmd(hip: Path, node: str, *, hfs: str, hip_dir: str) -> str:
    hython = Path(hfs) / "bin" / "hython"
    snippet = f"from oom_houdini.cook_top import cook; cook({json.dumps(str(hip))}, {json.dumps(node)})"
    parts = [
        "set -euo pipefail",
        "umask 000",
        f"export HIP={shlex.quote(hip_dir)}",
        f"export HFS={shlex.quote(hfs)}",
        f"{shlex.quote(str(hython))} -c {shlex.quote(snippet)}",
    ]
    return "; ".join(parts)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Submit headless PDG cook (controller job)")
    parser.add_argument("--hip", required=True, help="Absolute path to the .hip/.hiplc file")
    parser.add_argument("--node", required=True, help="TOP/PDG node path (e.g. /obj/topnet1)")
    parser.add_argument("--cpu", default=None, help="Deprecated; service jobs do not request CPU explicitly")
    parser.add_argument("--ram", default=None, help="Deprecated; service jobs do not request memory explicitly")
    parser.add_argument("--gpu", default="0", help="Deprecated; service jobs must use 0 GPUs")
    parser.add_argument("--namespace", default=None, help="Kubernetes namespace (env OOM_PDG_NAMESPACE or dcc)")
    parser.add_argument("--name", default=None, help="Optional job name override")
    args = parser.parse_args(argv)

    hip_path = Path(args.hip).expanduser().resolve()
    if not hip_path.is_file():
        raise SystemExit(f"HIP file not found: {hip_path}")

    node_path = args.node.strip()
    if not node_path:
        raise SystemExit("TOP node path is required")

    cook_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    base_dir, scripts_dir = ensure_pdg_dirs(hip_path, cook_id)

    if args.cpu:
        print("Ignoring --cpu for service job submission", file=sys.stderr)
    if args.ram:
        parse_mem_arg(args.ram)  # Validate format but ignore value
        print("Ignoring --ram for service job submission", file=sys.stderr)
    parse_gpu_arg(args.gpu)
    uid, gid = resolve_uid_gid()

    namespace = (args.namespace or os.environ.get("OOM_PDG_NAMESPACE") or DEFAULT_NAMESPACE).strip()
    if not namespace:
        namespace = DEFAULT_NAMESPACE

    job_name_input = args.name or f"pdg-ctrl-{cook_id}"
    job_name = sanitize_job_name(job_name_input)

    hfs = os.environ.get("HFS", DEFAULT_HFS).strip() or DEFAULT_HFS
    command = build_controller_cmd(hip_path, node_path, hfs=hfs, hip_dir=hip_path.parent.as_posix())

    manifest = build_service_job_manifest(
        name=job_name,
        ns=namespace,
        command=command,
#        pdg_dir=base_dir,
#        pdg_scripts=scripts_dir,
        uid=uid,
        gid=gid,
#        pdg_item_name="controller",
#        pdg_item="controller",
        hhp=os.environ.get("HHP", ""),
    )

    try:
        from kubernetes import client
    except ImportError as exc:
        raise SystemExit("The 'kubernetes' Python package is required to submit jobs") from exc

    load_kube()
    batch_api = client.BatchV1Api()
    job = create_job(batch_api, manifest)
    created_name = getattr(getattr(job, "metadata", None), "name", job_name)
    print(f"Submitted controller job: {created_name} (namespace={namespace})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


# Function Defs
def submit_controller_job(hip: str, node: str, *, namespace: Optional[str] = None, name: Optional[str] = None):

    # Validate inputs
    hip_path = Path(hip).expanduser().resolve()
    if not hip_path.is_file():
        return False, f"HIP file not found: {hip_path}"

    node_path = (node or "").strip()
    if not node_path:
        return False, "TOP node path is required"

    # Prepare PDG temp dirs
    cook_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    # Resolve IDs
    try:
        uid, gid = resolve_uid_gid()
    except Exception as e:
        return False, f"Failed resolving UID/GID: {e}"

    # Namespace + job name
    ns = (namespace or os.environ.get("OOM_PDG_NAMESPACE") or DEFAULT_NAMESPACE).strip() or DEFAULT_NAMESPACE
    job_name_input = name or f"pdg-ctrl-{cook_id}"
    job_name = sanitize_job_name(job_name_input)

    # Build controller command (runs hython in the pod)
    hfs = os.environ.get("HFS", DEFAULT_HFS).strip() or DEFAULT_HFS
    command = build_controller_cmd(hip_path, node_path, hfs=hfs, hip_dir=hip_path.parent.as_posix())

    # Build manifest
    manifest = build_service_job_manifest(
        name=job_name,
        ns=ns,
        command=command,
#         pdg_dir=base_dir,
#         pdg_scripts=scripts_dir,
        uid=uid,
        gid=gid,
#        pdg_item_name="controller",
#        pdg_item="controller",
        hhp=os.environ.get("HHP", ""),
    )

    # Submit to k8s
    try:
        from kubernetes import client
    except ImportError as exc:
        return False, "The 'kubernetes' Python package is required to submit jobs"

    try:
        load_kube()
        batch_api = client.BatchV1Api()
        job = create_job(batch_api, manifest)
        created_name = getattr(getattr(job, "metadata", None), "name", job_name)
        return True, f"Submitted controller job: {created_name} (namespace={ns})"
    except Exception as e:
        return False, f"Failed to submit controller job: {e}"
