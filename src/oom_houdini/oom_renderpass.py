import oom_houdini.oom_cache as _cache
from oom_houdini.sg_template_utils import build_template_fields
import hou
import os

# Alias reusable cache helpers; override refresh for renderpass specificity
get_versions = _cache.get_versions
cache_versions_update = _cache.cache_versions_update
store_versions = _cache.store_versions
store_selected = _cache.store_selected
restore_selected = _cache.restore_selected
version_menu = _cache.version_menu


def populate_lop(kwargs: dict) -> None:
    """Callback for rendersettings publish name parameter.

    Builds the publish file path using the ``oom_renderpass`` ShotGrid
    template and updates version tracking parameters.
    """
    tk = hou.session.oom_tk
    template = tk.templates["oom_renderpass"]
    node = kwargs["node"]
    name_parm = kwargs["parm"]
    publish_name = name_parm.eval()

    # Build common template fields
    fields = build_template_fields(
        template, publish_name=publish_name, include_frame=True
    )

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

    base, rest = fname.split(".", 1)
    file_expr = f"{base}.$F4.{rest.split('.')[1]}"

    final = os.path.join(dir_expr, file_expr)
    node.parm("filename").set(final)

    versions = get_versions(publish_name, "oom_renderpass")
    versions = _cache.ensure_spare_versions_initialized(node, versions)
    store_versions(node, versions)
    cache_versions_update(publish_name, versions)
    store_selected(node)


def refresh_versions(kwargs: dict) -> None:
    """Refresh version list for Renderpass publishes only.

    Ensures the query is constrained to PublishedFileType 'oom_renderpass'.
    """
    node = kwargs["node"]
    publish_name = node.parm("name").eval()

    versions = get_versions(publish_name, "oom_renderpass")
    store_versions(node, versions)
    cache_versions_update(publish_name, versions)
    restore_selected(node)
