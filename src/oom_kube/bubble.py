import os, sys, time, signal, socket, re, subprocess, pathlib
from typing import Optional

try:
    import yaml
except ImportError as exc:
    print("bubble.py requires PyYAML. Install with `pip install pyyaml`.", file=sys.stderr)
    raise

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError as exc:
    print("bubble.py requires Jinja2. Install with `pip install jinja2`.", file=sys.stderr)
    raise

from kubernetes import client, config


JOB_LABEL_KEY = "oom-bubble-job"
DEFAULT_CPU = "32"
DEFAULT_MEM_GI = "64"


# -----------------------------
# Small helpers
# -----------------------------

def default_pod_name():
    # dcc-<user>-MMDD-HHMMSS
    user = os.environ.get("USER") or "user"
    stamp = time.strftime("%m%d-%H%M%S", time.localtime())
    return f"dcc-{user}-{stamp}"


def current_user():
    return os.environ.get("USER") or "user"


def state_file_path():
    user = current_user()
    return f"/tmp/oom-bubble.{user}"


def write_state(ns: str, pod: str, template: str = "dcc-session", job: Optional[str] = None):
    path = state_file_path()

    content = [
        f"BUBBLE_NS={ns}",
        f"BUBBLE_WORKFLOW={pod}",  # keep key name for compatibility
        f"BUBBLE_POD={pod}",
        f"BUBBLE_TEMPLATE={template}",
        f"BUBBLE_STARTED={int(time.time())}",
        "",
    ]

    if job:
        content.insert(4, f"BUBBLE_JOB={job}")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(content))

    try:
        os.chmod(path, 0o644)
    except Exception:
        pass


def clear_state_if_matching(pod: str):
    path = state_file_path()
    try:
        data = {}
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data[key] = value
        if data.get("BUBBLE_WORKFLOW") == pod:
            os.remove(path)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def normalize_cpu(cpu_str: str) -> str:
    # Accept "16" or "2.5"; convert decimals to millicores "2500m"
    if re.fullmatch(r"\d+", cpu_str):
        return cpu_str
    if re.fullmatch(r"\d+\.\d+", cpu_str):
        whole, frac = cpu_str.split(".")
        millicores = int(whole) * 1000 + int((frac + "000")[:3])
        return f"{millicores}m"
    raise ValueError("CPU must be a number (e.g. 16 or 2.5)")


def find_gpus() -> int:
    output = subprocess.check_output(["nvidia-smi", "-L"], text=True)
    gpu_count = int(len(output.strip().splitlines()))
    return gpu_count


def template_path() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve().parent
    return here / "templates" / "bubble-job.yaml"


def load_environment() -> Environment:
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

# Check for dev mode env var, sets environment to flow through pipeline using live oom branch etc
def dev_mode() -> bool:
    return os.getenv("OOM_DEV", "0").lower() in ("1", "true", "yes", "on")

# -----------------------------
# Job manifest
# -----------------------------

def build_job_manifest(
    name: str,
    ns: str,
    target_node: str,
    uid: int,
    gid: int,
    display: str,
    cpu: Optional[str],
    mem_gi: Optional[str],
    gpu: int = 1,
) -> dict:

    env = load_environment()
    template = env.get_template("bubble-job.yaml")

    cpu_value = cpu if cpu is not None else DEFAULT_CPU
    mem_value = mem_gi if mem_gi is not None else DEFAULT_MEM_GI
    gpu_count = int(gpu) if gpu is not None else 0

    cpu_request = normalize_cpu(cpu_value)
    mem_request = f"{mem_value}Gi"
    if gpu_count <= 0:
        raise RuntimeError("No GPUs detected on this host; bubble requires at least one GPU.")
    gpu_request = str(gpu_count)

    # Check for dev mode
    is_dev = dev_mode()
    if is_dev:
        oom_repo = "oom-repo-pvc"
        dev_env = "'True'"
    else:
        oom_repo = "oom-repo-prod-pvc"
        dev_env = "'False'"

    context = {
        "job_name": name,
        "namespace": ns,
        "oom_repo": oom_repo,
        "oom_repo_path": os.environ.get("OOM", "/workspace/oom-dcc"),
        "oom_dev": dev_env,
        "target_node": target_node,
        "uid": uid,
        "gid": gid,
        "display": display,
        "cpu_request": cpu_request,
        "mem_request": mem_request,
        "gpu_request": gpu_request,
    }

    text = template.render(**context)
    return yaml.safe_load(text)


# -----------------------------
# K8s ops
# -----------------------------

def load_kube():
    # Use KUBECONFIG or in-cluster
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


def wait_for_job_pod_ready(api: client.CoreV1Api, ns: str, job_name: str, timeout_sec: int = 600):
    start = time.time()
    label_selector = f"{JOB_LABEL_KEY}={job_name}"

    while True:
        pods = api.list_namespaced_pod(namespace=ns, label_selector=label_selector)

        for pod in pods.items:
            phase = (pod.status.phase or "").lower()
            if phase == "failed":
                raise RuntimeError("Pod failed early (phase=Failed)")
            if phase == "succeeded":
                return pod

            for condition in (pod.status.conditions or []):
                if condition.type == "Ready" and condition.status == "True":
                    return pod

        if time.time() - start > timeout_sec:
            raise TimeoutError("Timed out waiting for pod readiness")

        time.sleep(2)


# -----------------------------
# Interactive lifecycle
# -----------------------------

def interactive(cpu: Optional[str] = None, mem_gi: Optional[str] = None):
    ns = "dcc"
    uid = os.getuid()
    gid = os.getgid()
    display = os.environ.get("DISPLAY", ":1")
    target_node = socket.gethostname()
    job_name = default_pod_name()

    load_kube()
    core_api = client.CoreV1Api()
    batch_api = client.BatchV1Api()

    gpus = find_gpus()

    manifest = build_job_manifest(
        name=job_name,
        ns=ns,
        target_node=target_node,
        uid=uid,
        gid=gid,
        display=display,
        cpu=cpu,
        mem_gi=mem_gi,
        gpu=gpus,
    )

    print("Starting a new bubble…")
    create_job(batch_api, manifest)
    pod = wait_for_job_pod_ready(core_api, ns, job_name, timeout_sec=600)
    pod_name = pod.metadata.name

    node = pod.spec.node_name or target_node
    ip = pod.status.pod_ip or "n/a"

    write_state(ns, pod_name, template="dcc-session", job=job_name)

    print("")
    print("Bubble is ready")
    print(f"- job: {job_name}")
    print(f"- pod: {pod_name}")
    print(f"- namespace: {ns}")
    print(f"- node: {node}")
    print(f"- pod ip: {ip}")
    print("")
    print("This terminal now represents your bubble.")
    print("Press Ctrl+C to close it.")
    print(f"Run `kubectl delete job {job_name} -n {ns}` if you lose this terminal.")

    stop = {"flag": False}

    def on_signal(signum, frame):
        stop["flag"] = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    try:
        while not stop["flag"]:
            try:
                current = get_pod(core_api, ns, pod_name)
            except client.exceptions.ApiException as exc:
                if exc.status == 404:
                    print("Bubble ended (pod no longer present).")
                    return 0
                raise

            phase = (current.status.phase or "").lower()
            if phase in ("failed", "succeeded"):
                print("Bubble ended (pod completed).")
                return 0

            time.sleep(2)
    finally:
        print("Closing bubble…")
        try:
            delete_job(batch_api, ns, job_name)
        except Exception:
            pass
        clear_state_if_matching(pod_name)
        print("Bubble closed.")
        return 0


# -----------------------------
# CLI
# -----------------------------

def usage():
    print(
        "Usage: bubble_k8s.py [-c CPU] [-m MEM_GI]",
        "\n  -c CPU    : number of CPU cores (e.g. 16 or 2.5)",
        "\n  -m MEM_GI : RAM in Gi as a number (e.g. 64)",
        sep="",
    )


def main(argv):
    cpu = None
    mem_gi = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            usage()
            return 0
        if arg in ("-c", "--cpu"):
            if i + 1 >= len(argv):
                print("Missing value after -c/--cpu", file=sys.stderr); return 2
            val = argv[i + 1]
            if not re.fullmatch(r"\d+(?:\.\d+)?", val):
                print("CPU must be a number (e.g. 16 or 2.5)", file=sys.stderr); return 2
            cpu = val; i += 2; continue
        if arg in ("-m", "--memory"):
            if i + 1 >= len(argv):
                print("Missing value after -m/--memory", file=sys.stderr); return 2
            val = argv[i + 1]
            if not re.fullmatch(r"\d+", val):
                print("RAM must be an integer Gi amount (e.g. 64)", file=sys.stderr); return 2
            mem_gi = val; i += 2; continue
        print(f"Unknown argument: {arg}", file=sys.stderr)
        usage(); return 2

    try:
        return interactive(cpu=cpu, mem_gi=mem_gi)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
