from oom_houdini.sg_load import browse_publish
from oom_houdini.sg_load import update_to_latest as _update_to_latest

USD_PUBLISHED_TYPE = "oom_usd_publish_wedged"


def browse_usd(kwargs: dict) -> None:
    """Callback for the Browse button on the USD loader HDA."""
    browse_publish(kwargs, USD_PUBLISHED_TYPE)


def update_to_latest(target, is_path: bool = False) -> None:
    """Callback for updating to latest USD publish when ``force_latest`` is on."""
    _update_to_latest(target, USD_PUBLISHED_TYPE, is_path=is_path)
