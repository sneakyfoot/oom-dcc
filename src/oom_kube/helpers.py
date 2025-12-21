import os
import pathlib
import re
from typing import Optional
from jinja2 import Environment, FileSystemLoader
from kubernetes import client, config


# Check if environment DEV mode is active
def dev_mode() -> bool:
    return os.getenv("OOM_DEV", "0").lower() in ("1", "true", "yes", "on")


# Gets template yaml file for substitutions and submission
def template_path(template: str = "pdg-job-gpu.yaml") -> pathlib.Path:
    repo_env = os.getenv("OOM")
    if repo_env:
        repo = pathlib.Path(repo_env)
    else:
        repo = pathlib.Path(__file__).resolve().parents[2]  # src root
    templates = repo / "src/oom_kube/templates"
    if not templates.exists():
        templates = repo / "oom-core/oom_kube/templates"
    template_path = templates / template
    return template_path


# Loads the template with jinja
def load_environment(template: Optional[str]) -> Environment:
    if template:
        path = template_path(template)
    else:
        path = template_path()
    loader = FileSystemLoader(path.parent)
    return Environment(
        loader=loader,
        variable_start_string="{ {",
        variable_end_string=" } }",
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def normalize_cpu(cpu_str: str) -> str:
    # Accept "16" or "2.5"; convert decimals to millicores "2500m"
    if re.fullmatch(r"\d+", cpu_str):
        return cpu_str
    if re.fullmatch(r"\d+\.\d+", cpu_str):
        whole, frac = cpu_str.split(".")
        millicores = int(whole) * 1000 + int((frac + "000")[:3])
        return f"{millicores}m"
    raise ValueError("CPU must be a number (e.g. 16 or 2.5)")


# loads kubeconfig from local, or in-cluster
def load_kube():
    try:
        config.load_kube_config()
    except Exception:
        config.load_incluster_config()


def create_job(api: client.BatchV1Api, manifest: dict):
    namespace = manifest["metadata"]["namespace"]
    return api.create_namespaced_job(namespace=namespace, body=manifest)


def get_pod(api: client.CoreV1Api, ns: str, name: str):
    return api.read_namespaced_pod(namespace=ns, name=name)


def delete_job(api: client.BatchV1Api, ns: str, name: str):
    options = client.V1DeleteOptions(
        grace_period_seconds=10,
        propagation_policy="Foreground",
    )
    try:
        api.delete_namespaced_job(namespace=ns, name=name, body=options)
    except client.exceptions.ApiException:
        pass
