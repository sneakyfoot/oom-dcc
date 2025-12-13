from oom_houdini.sg_load import browse_publish, update_to_latest

# Allow the Image Loader to browse both renderpasses and comps
IMAGE_PUBLISHED_TYPES = ["oom_renderpass", "oom_comp"]


def browse_image(kwargs: dict) -> None:
    """Called by the Image Loader HDA's Browse button."""

    browse_publish(kwargs, IMAGE_PUBLISHED_TYPES)


def update_image_to_latest(target, is_path: bool = False) -> None:
    """Called on OnLoad/Refresh when force_latest is enabled."""

    update_to_latest(target, IMAGE_PUBLISHED_TYPES, is_path=is_path)
