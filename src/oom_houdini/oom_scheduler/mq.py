import os
import uuid


DEFAULT_RELAY_PORT = 53000
DEFAULT_CALLBACK_PORT = 53001
DEFAULT_MQ_HOST = "192.168.0.225"

# Optional static configuration. Set the host/ports here when you do not want
# to rely on environment variables. Leave host empty to keep using env vars.
PERSISTENT_MQ_CONFIG = {
    "host": DEFAULT_MQ_HOST,
    "relay_port": DEFAULT_RELAY_PORT,
    "callback_port": DEFAULT_CALLBACK_PORT,
}


# Debug / Dev mode helpers (mirrors scheduler.py)
def _env_truthy(value):

    # Normalize env var values like 1/true/yes/on
    text = str(value).strip().lower()

    return text in ("1", "true", "yes", "on")


def _env_int(value, default):

    try:
        if value is None:
            return int(default)
        text = str(value).strip()
        if not text:
            return int(default)
        return int(text, 10)
    except Exception as exc:
        _log_exception("_env_int", exc)
        return int(default)


_DEV_VERBOSE = _env_truthy(os.environ.get("OOM_DEV", ""))


def _dprint(*parts):

    # Print debug info only when OOM_DEV is enabled
    if not _DEV_VERBOSE:
        return None

    try:
        print("[OOM_DEV][mq]", *parts)
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


class MQManager:
    """
    Minimal MQ wrapper that connects to a long-running mqserver instance.

    This implementation assumes the PDG Message Queue is provided externally
    (for example, via a persistent Kubernetes Deployment). The host and ports
    are resolved from either the provided persistent_config dict or the
    following environment variables:

        OOM_MQ_HOST              - required hostname or IP
        OOM_MQ_RELAY_PORT        - optional, defaults to 53000
        OOM_MQ_CALLBACK_PORT     - optional, defaults to 53001
    """

    def __init__(self, owner, persistent_config=None):
        # owner is the scheduler instance (provides PDG callbacks/APIs)
        self._owner = owner

        # cache for resolved persistent MQ configuration
        self._config_cache = persistent_config

        # client id used by relay connections
        self.client_id = uuid.uuid4().hex

        # runtime state
        self._host = None
        self._xmlport = None
        self._relayport = None
        self._relay = None

        # readiness/waiting flags
        self._ready = False

    # Function Defs
    def is_ready(self) -> bool:
        return bool(self._ready)

    def is_waiting(self) -> bool:
        return False

    def _load_persistent_config(self):
        if self._config_cache:
            return self._config_cache

        config = PERSISTENT_MQ_CONFIG or {}
        host = (config.get("host") or "").strip()
        relay_port = config.get("relay_port", DEFAULT_RELAY_PORT)
        callback_port = config.get("callback_port", DEFAULT_CALLBACK_PORT)

        if not host:
            host = (
                os.environ.get("OOM_MQ_HOST")
                or os.environ.get("PDG_MQ_HOST")
                or ""
            ).strip()
            relay_port = (
                os.environ.get("OOM_MQ_RELAY_PORT")
                or os.environ.get("PDG_MQ_RELAY_PORT")
                or relay_port
            )
            callback_port = (
                os.environ.get("OOM_MQ_CALLBACK_PORT")
                or os.environ.get("PDG_MQ_CALLBACK_PORT")
                or callback_port
            )

        if not host:
            return None

        relay_port = _env_int(relay_port, DEFAULT_RELAY_PORT)
        callback_port = _env_int(callback_port, DEFAULT_CALLBACK_PORT)

        self._config_cache = {
            "host": host,
            "relay_port": int(relay_port),
            "callback_port": int(callback_port),
        }
        return self._config_cache

    # Start the PDG MQ connection (persistent server assumed to be running)
    def start(self) -> None:
        if self._ready:
            return None

        config = self._load_persistent_config()
        if not config:
            raise RuntimeError(
                "Persistent MQ not configured. "
                "Set OOM_MQ_HOST (and optional *_PORT values) before cooking."
            )

        if not self._connect_shared(
            config["host"], config["relay_port"], config["callback_port"]
        ):
            raise RuntimeError(
                f"Failed to connect to persistent PDGMQ server "
                f"{config['host']}:{config['relay_port']}"
            )

        _dprint(
            "connected persistent MQ",
            f"{self._host}:{self._relayport}",
            f"callback={self._xmlport}",
        )

        return None

    def _connect_shared(self, host, relayport, xmlport):

        # Guard against incomplete connection details
        if not host or not relayport:
            return False

        try:
            from pdg.job.callbackserver import CallbackServerAPI
            from pdg.utils.mq import MQUtility
            from pdgutils import PDGNetMQRelay

            if not self._relay:
                self._relay = PDGNetMQRelay(CallbackServerAPI(self._owner))

            self._relay.connectToMQServer(
                host,
                int(relayport),
                self.client_id,
                MQUtility.RelayPollingTime,
                MQUtility.NetTimeout,
                MQUtility.RelayMaxReceiveMessageBuffer,
                MQUtility.NetTimeout,
            )
        except Exception as exc:
            _log_exception("_connect_shared", exc)
            return False

        self._host = host
        self._xmlport = int(xmlport) if xmlport else None
        self._relayport = int(relayport)
        self._owner.setWorkItemResultServerAddr(f"{host}:{int(relayport)}")
        self._ready = True

        _dprint("connected relay", host, int(relayport))
        return True

    # Poll for the MQ connection until the relay is established
    def poll(self) -> None:
        return None

    # Stop the relay and clear scheduler state
    def stop(self, cancel=False) -> None:
        # Stop relay and clear server address
        try:
            if self._relay:
                try:
                    self._relay.stopRelayServer()
                except Exception as exc:
                    _log_exception("mq.stop:relay", exc)
            self._owner.setWorkItemResultServerAddr("")
        except Exception as exc:
            _log_exception("mq.stop", exc)

        # Reset state
        self._host = None
        self._xmlport = None
        self._relayport = None
        self._relay = None
        self._ready = False

        return None
