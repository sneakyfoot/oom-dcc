# oom_sg_auth.py
import base64
import os
from typing import Mapping, Optional, Tuple, cast

from sgtk.authentication import ShotgunAuthenticator, ShotgunUser


REQUIRED_KEYS = ("SG_SCRIPT_NAME", "SG_SCRIPT_KEY", "SG_HOST")
Credentials = Tuple[str, str, str]


def oom_auth() -> ShotgunUser:
    auth = ShotgunAuthenticator()

    kube_credentials = _load_credentials_from_kubernetes()

    if kube_credentials:
        script_name, api_key, host = kube_credentials
        # print("[oom] Authorizing with script user from kubernetes secret")
        return auth.create_script_user(
            api_script=script_name, api_key=api_key, host=host
        )

    env_credentials = _load_credentials_from_environment()

    if env_credentials:
        script_name, api_key, host = env_credentials
        print("[oom] K8s auth failed")
        print("[oom] Authorizing with script user from environment variables")
        return auth.create_script_user(
            api_script=script_name, api_key=api_key, host=host
        )

    raise RuntimeError(
        "ShotGrid script credentials not found in kubernetes secret or environment"
    )


def _load_credentials_from_kubernetes() -> Optional[Credentials]:
    # Try to import the kubernetes client lazily so non-cluster hosts still work
    try:
        from kubernetes import client, config
        from kubernetes.client import ApiException
        from kubernetes.config.config_exception import ConfigException
    except ImportError:
        return None

    try:
        config.load_incluster_config()
    except ConfigException:
        try:
            config.load_kube_config()
        except ConfigException:
            return None

    kube = client.CoreV1Api()

    try:
        secret = kube.read_namespaced_secret("shotgun-auth", "dcc")
    except ApiException:
        return None

    data = getattr(secret, "data", None) or {}

    try:
        values = tuple(_decode_secret_value(data, key) for key in REQUIRED_KEYS)
        return cast(Credentials, values)
    except (KeyError, ValueError, UnicodeDecodeError):
        return None


def _load_credentials_from_environment() -> Optional[Credentials]:
    values = tuple(os.environ.get(key) for key in REQUIRED_KEYS)

    if any(not value for value in values):
        return None

    return cast(Credentials, values)


def _decode_secret_value(data: Mapping[str, str], key: str) -> str:
    value = data[key]

    decoded = base64.b64decode(value)

    plain_text = decoded.decode("utf-8").strip()

    if not plain_text:
        raise ValueError(f"Empty value for kubernetes secret key '{key}'")

    return plain_text
