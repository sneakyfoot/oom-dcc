import os

import hou

import oom_houdini.oom_cache as _cache
from oom_houdini.sg_template_utils import build_template_fields

# Alias reusable cache helpers; override refresh for USD specificity
get_versions = _cache.get_versions
cache_versions_update = _cache.cache_versions_update
store_versions = _cache.store_versions
store_selected = _cache.store_selected
restore_selected = _cache.restore_selected
version_menu = _cache.version_menu


def populate_lop(kwargs: dict) -> None:
    """Callback for USD LOP publish name parameter.

    Builds the publish file path using the ``oom_usd_publish_wedged`` ShotGrid
    template and updates version tracking parameters.
    """
    tk = hou.session.oom_tk
    template = tk.templates["oom_usd_publish_wedged"]
    node = kwargs["node"]
    name_parm = kwargs["parm"]
    publish_name = name_parm.eval()

    if publish_name == 0:
        print("Localize")
        publish_name = node.parm("name").eval()

    # Build common template fields
    fields = build_template_fields(
        template, publish_name=publish_name, include_frame=False
    )

    # cache templates may include a wedge token; set a placeholder so apply works
    fields["wedge"] = 1
    try:
        raw = template.apply_fields(fields)
    except Exception as e:
        hou.ui.displayMessage("Failed to set path. Are you inside a blank scene?")
        print(e)
        return

    dir_path, fname = os.path.split(raw)
    dirs = dir_path.split(os.sep)
    dirs[-1] = '`chs("version")`'
    dir_expr = os.sep.join(dirs)

    base, wedge_tok, rest = fname.split(".", 2)
    file_expr = f'{base}.`chs("wedge_index")`.{rest.split(".", 1)[0]}'

    final = os.path.join(dir_expr, file_expr)
    node.parm("filename").set(final)

    # set pre and post wedge file string for houdini wedge reading
    WEDGE_EXPR = '`chs("wedge_index")`'

    full_path = os.path.join(dir_expr, file_expr)  # same as “final”
    idx = full_path.find(WEDGE_EXPR)

    pre_wedge = full_path[:idx]  # dir_expr + base + first dot
    post_wedge = full_path[idx + len(WEDGE_EXPR) :]  # ".$F4.bgeo.sc"

    node.parm("filename_pre_wedge").set(pre_wedge)
    node.parm("filename_post_wedge").set(post_wedge)

    frame_path = final.replace(".usd", ".$F4.usd")
    node.parm("filename_frames").set(frame_path)

    post_wedge_frames = post_wedge.replace(".usd", ".$F4.usd")
    node.parm("filename_post_wedge_frames").set(post_wedge_frames)

    versions = get_versions(publish_name, "oom_usd_publish_wedged")
    versions = _cache.ensure_spare_versions_initialized(node, versions)
    store_versions(node, versions)
    cache_versions_update(publish_name, versions)
    store_selected(node)


def refresh_versions(kwargs: dict) -> None:
    """Refresh version list for USD publishes only.

    Ensures the query is constrained to PublishedFileType 'oom_usd_publish_wedged'
    so similarly named cache publishes don’t collide.
    """
    node = kwargs["node"]
    publish_name = node.parm("name").eval()

    versions = get_versions(publish_name, "oom_usd_publish_wedged")
    store_versions(node, versions)
    cache_versions_update(publish_name, versions)
    restore_selected(node)
