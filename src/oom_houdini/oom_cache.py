"""Utilities for Houdini cache HDAs.

This module assumes ShotGrid Toolkit has been bootstrapped via the ``123.py``
startup script. The bootstrap stores ``oom_tk`` and ``oom_context`` on
``hou.session`` which are used here to resolve template paths and query
publishes.
"""

import ast
import os
from typing import List, Optional

import hou

from oom_houdini.sg_template_utils import build_template_fields

CACHE_TEMPLATE_NAME = "oom_houdini_cache"
# Default PublishedFileType code for generic Houdini cache publishes
CACHE_PUBLISHED_TYPE_CODE = "oom_houdini_cache"


def get_versions(
    cache_name: str, published_file_type: Optional[str] = None
) -> List[int]:
    """Return sorted ints of published versions (or []).

    If ``published_file_type`` is provided, restricts the search to that
    ShotGrid PublishedFileType code (e.g. ``"oom_houdini_cache"`` or
    ``"oom_usd_publish"``). This avoids cross-type collisions when different
    publishes share the same code/name.
    """
    tk = hou.session.oom_tk
    ctx = hou.session.oom_context
    sg = tk.shotgun

    filters = [
        ["project", "is", ctx.project],
        ["entity", "is", ctx.entity],
        ["code", "is", cache_name],
    ]

    if published_file_type:
        pf = sg.find_one(
            "PublishedFileType", [["code", "is", published_file_type]], ["id"]
        )
        if pf:
            filters.insert(
                2,
                [
                    "published_file_type",
                    "is",
                    {"type": "PublishedFileType", "id": pf["id"]},
                ],
            )

    pubs = sg.find("PublishedFile", filters, ["version_number"])
    return sorted(
        {p["version_number"] for p in pubs if p.get("version_number") is not None}
    )


def cache_versions_update(cache_name, versions):
    if not hasattr(hou.session, "oom_cache_versions"):
        hou.session.oom_cache_versions = {}

    hou.session.oom_cache_versions[cache_name] = versions


def ensure_spare_versions_initialized(node, versions):
    """Seed spare/version parms so menu callbacks don't fail on new nodes."""
    spare = node.parm("spare_versions").eval().strip()
    if not spare:
        if 0 not in versions:
            versions = [0] + versions
        node.parm("selected_version").set("0")
        node.parm("version").set(0)
    return versions


def store_versions(node, versions):
    versions = str(versions)
    node.parm("spare_versions").set(versions)
    return


def store_selected(node=None):
    if node is None:
        node = hou.pwd()
    selected = node.parm("version").evalAsString()
    node.parm("selected_version").set(selected)
    return


def restore_selected(node=None):
    if node is None:
        node = hou.pwd()

    # read the stored selected version
    version = node.parm("selected_version").eval().strip()
    if not version:
        return

    # read the stored list
    versions_string = node.parm("spare_versions").eval().strip()
    versions = ast.literal_eval(versions_string) if versions_string else []

    # reverse sort
    versions = versions[::-1]

    try:
        index = versions.index(int(version))
    except ValueError:
        return

    node.parm("version").set(index)
    return


def refresh_versions(kwargs):
    node = kwargs["node"]
    cache_name = node.parm("name").eval()
    versions = get_versions(cache_name, CACHE_PUBLISHED_TYPE_CODE)
    store_versions(node, versions)
    cache_versions_update(cache_name, versions)
    restore_selected(node)


def populate_cache(kwargs: dict) -> None:
    """Callback for the cache HDA name parameter.

    This resolves the cache file path using the ShotGrid template and updates
    the version menu from existing publishes.
    """
    tk = hou.session.oom_tk
    template = tk.templates["oom_houdini_cache"]
    node = kwargs["node"]
    name_parm = kwargs["parm"]
    cache_name = name_parm.eval()
    print("Debug Localization")
    print(cache_name)
    if str(cache_name).strip() == "0":
        print("Localize")
        cache_name = node.parm("name").eval()
        print(cache_name)

    # build template fields (Step, name, frame/version defaults)
    fields = build_template_fields(
        template, publish_name=cache_name, include_frame=True
    )
    # cache templates may include a wedge token; set a placeholder so apply works
    fields["wedge"] = 1
    try:
        raw = template.apply_fields(fields)
    except Exception as e:
        hou.ui.displayMessage(
            "Failed to set path. Are you inisde a blank scene: " + str(e)
        )
        return

    # construct houdini path
    dir_path, fname = os.path.split(raw)
    dirs = dir_path.split(os.sep)
    dirs[-1] = '`chs("version")`'  # version folder
    dir_expr = os.sep.join(dirs)

    base, wedge_tok, rest = fname.split(".", 2)
    file_expr = f'{base}.`chs("wedge_index")`.$F4.{rest.split(".", 1)[1]}'

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

    versions = get_versions(cache_name, CACHE_PUBLISHED_TYPE_CODE)
    ensure_spare_versions_initialized(node, versions)
    store_versions(node, versions)
    cache_versions_update(cache_name, versions)
    store_selected(node)


def version_menu():
    node = hou.pwd()
    versions_string = node.parm("spare_versions").eval().strip()
    versions = ast.literal_eval(versions_string) if versions_string else []
    # cache_name = node.evalParm("name").strip()

    # cache = getattr(hou.session, "oom_cache_versions", {})
    # versions =  cache.get(cache_name, [])          # empty list if not cached

    """
    Ordered menu callback.
    Returns a flat tuple: (token, label, token, label, …)

        • token  → what Houdini stores in the parm (goes into the file path)
        • label  → what the user sees in the UI
    """
    # versions = _get_versions()          # e.g. [1, 2, 3]  or  []
    # reverse the list
    versions = versions[::-1]
    if not versions:  # no publishes yet
        return ("000", "0")  # token '000' (path), label '0' (UI)

    # TOKENS = '001','002',…   LABELS = '1','2',…
    tokens = [v for v in versions]  # zero padded
    labels = [str(v) for v in versions]  # plain ints

    # flatten to token,label,token,label,…
    flat = tuple(x for pair in zip(tokens, labels) for x in pair)

    # store as selected
    return flat


# Submit headless farm job
def submit_job(node):
    from oom_houdini.cook_top import pre_update_cache
    from oom_houdini.submit_pdg_cook import submit_controller_job

    hip = hou.hipFile.path()
    ok, msg = submit_controller_job(hip, node)
    cache_node = node.rsplit("/cache_top/OUT", 1)[0]
    cache_node = hou.node(cache_node)
    pre_update_cache([cache_node])
    if ok:
        print(f"[oom] {msg}")
        hou.ui.displayMessage(f"{msg}")
    else:
        print(f"[oom] Controller submit failed:\n{msg}")
        hou.ui.displayMessage(f"Controller submit failed:\n{msg}")
