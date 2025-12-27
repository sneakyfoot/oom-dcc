"""
Shared helpers for PDG Python Script TOP publishes.

Centralizes common ShotGrid publish logic so individual TOP scripts can
simply call the appropriate function with minimal boilerplate.

Notes:
- Assumes facility context via hou.session.oom_tk and hou.session.oom_context.
- Publishes are ShotGrid-native and Task-first; this only registers a
  PublishedFile record — the heavy lifting (rendering/writing) is done by TOPs.
"""

import os
from datetime import datetime, timezone

import hou


# -----------------------------------------------------------------------------
# ShotGrid helpers
# -----------------------------------------------------------------------------
def _sg_handles():
    tk = hou.session.oom_tk
    ctx = hou.session.oom_context
    sg = tk.shotgun

    return tk, ctx, sg


def _get_pf_type_id(sg, code: str) -> int:
    rec = sg.find_one("PublishedFileType", [["code", "is", code]], ["id"])
    if not rec:
        raise RuntimeError(f"PublishedFileType '{code}' not found in ShotGrid")
    return rec["id"]


def _published_versions(sg, ctx, pf_type_id: int, name_code: str) -> list[int]:
    pubs = sg.find(
        "PublishedFile",
        [
            ["project", "is", ctx.project],
            ["entity", "is", ctx.entity],
            [
                "published_file_type",
                "is",
                {"type": "PublishedFileType", "id": pf_type_id},
            ],
            ["code", "is", name_code],
        ],
        ["version_number"],
    )

    return sorted(
        {p["version_number"] for p in pubs if p.get("version_number") is not None}
    )


def _next_version(sg, ctx, pf_type_id: int, name_code: str) -> int:
    versions = _published_versions(sg, ctx, pf_type_id, name_code)
    return (versions[-1] if versions else 0) + 1


def _create_publish(
    sg, ctx, pf_type_id: int, name_code: str, local_path: str, version: int
) -> dict:
    # Require a Task in context for Task-first workflow
    if not getattr(ctx, "task", None):
        raise RuntimeError(
            "ShotGrid Task is not set in the current context. "
            "Use the Save dialog to choose a Task, then re-run the publish."
        )

    data = {
        "project": ctx.project,
        "entity": ctx.entity,
        "task": ctx.task,
        "code": name_code,
        "path": {"local_path": local_path},
        "version_number": version,
        "published_file_type": {"type": "PublishedFileType", "id": pf_type_id},
        "description": "",
        "created_at": datetime.now(timezone.utc),
    }

    return sg.create("PublishedFile", data)


# -----------------------------------------------------------------------------
# Cache-node driven publishes (HDA parms provide paths)
# -----------------------------------------------------------------------------
def publish_usd_from_cache_node(work_item, cache_node_attr: str = "cache_node") -> None:
    """Register a USD publish using paths from a cache HDA node.

    Mirrors existing behavior in PDG_PUBLISH_SCRIPTS' "OOM LOP PUBLISH" block:
    - Reads version from node parm menu and increments for the new publish.
    - Replaces only the version token for SG path (no $F4 tokenization).
    - Stores useful paths back onto the work item for downstream tasks.
    """

    # Get the cache node from work item
    cache_path = work_item.stringAttribValue(cache_node_attr)
    cache_node = hou.node(cache_path)

    if cache_node is None:
        raise RuntimeError(f"Cache node '{cache_path}' not found")

    # Pull parms
    cache_name = cache_node.evalParm("name").strip()
    filename = cache_node.parm("filename").unexpandedString()
    filename_frames = cache_node.parm("filename_frames").unexpandedString()

    # ShotGrid handles and next version (SG-backed)
    tk, ctx, sg = _sg_handles()
    pf_type_id = _get_pf_type_id(sg, "oom_usd_publish_wedged")
    version = _next_version(sg, ctx, pf_type_id, cache_name)

    # Resolve SG and Houdini paths with concrete version
    sg_path = filename.replace('`chs("version")`', str(version)).replace(
        '`chs("wedge_index")`', "%02d"
    )

    hou_path = filename.replace('`chs("version")`', str(version))
    hou_path_frames = filename_frames.replace('`chs("version")`', str(version))
    hou_path_clip = hou_path_frames.replace("$F4.usd", "")

    pub = _create_publish(sg, ctx, pf_type_id, cache_name, sg_path, version)

    # Store attributes on the work item
    work_item.setIntAttrib("sg_publish_id", pub["id"])
    work_item.setStringAttrib("hou_filepath", hou_path)
    work_item.setStringAttrib("hou_filepath_frames", hou_path_frames)
    work_item.setStringAttrib("hou_filepath_clip", hou_path_clip)
    work_item.setStringAttrib("sg_filepath", sg_path)


def publish_cache_from_cache_node(
    work_item, cache_node_attr: str = "cache_node"
) -> None:
    """Register a frame-sequence cache publish from a cache HDA node.

    Mirrors existing behavior in PDG_PUBLISH_SCRIPTS' "OOM Cache" block:
    - Replaces $F4 with %04d and wedge/version tokens with printf tokens for SG.
    - Bumps the node's version for the publish record.
    - Stores SG/Houdini filepaths back onto the work item.
    """

    cache_path = work_item.stringAttribValue(cache_node_attr)
    cache_node = hou.node(cache_path)

    if cache_node is None:
        raise RuntimeError(f"Cache node '{cache_path}' not found")

    cache_name = cache_node.evalParm("name").strip()

    # Existing filename may contain $F4 and chs() tokens
    filename = cache_node.parm("filename").unexpandedString()

    # ShotGrid handles and next version (SG-backed)
    tk, ctx, sg = _sg_handles()
    pf_type_id = _get_pf_type_id(sg, "oom_houdini_cache")
    version = _next_version(sg, ctx, pf_type_id, cache_name)

    # SG sequence path uses printf-style tokens
    sg_path = (
        filename.replace("$F4", "%04d")
        .replace('`chs("wedge_index")`', "%02d")
        .replace('`chs("version")`', "%03d")
    )

    # Houdini path has concrete version baked in
    hou_path = filename.replace('`chs("version")`', str(version))

    # ShotGrid publish
    pub = _create_publish(sg, ctx, pf_type_id, cache_name, sg_path, version)

    work_item.setIntAttrib("sg_publish_id", pub["id"])
    work_item.setStringAttrib("hou_filepath", hou_path)
    work_item.setStringAttrib("sg_filepath", sg_path)


# -----------------------------------------------------------------------------
# Template-driven sequence publishes (renderpass/comp)
# -----------------------------------------------------------------------------
def _sequence_path_from_template(template_name: str, name: str, version: int) -> str:
    tk, ctx, _ = _sg_handles()
    template = tk.templates[template_name]

    fields = ctx.as_template_fields(template)
    try:
        fields["Step"] = ctx.step["name"]
    except Exception:
        pass

    fields["name"] = name
    fields["frame"] = 1
    fields["version"] = 1
    fields["wedge"] = 1

    raw = template.apply_fields(fields)

    dir_path, fname = os.path.split(raw)
    dirs = dir_path.split(os.sep)
    dirs[-1] = str(version)
    dir_expr = os.sep.join(dirs)

    wedge_key = "%02d"
    frame_key = "%04d"

    base, rest = fname.split(".", 1)
    ext = rest.split(".")[-1]
    file_expr = f"{base}.{wedge_key}.{frame_key}.{ext}"

    return os.path.join(dir_expr, file_expr)


def publish_renderpass_from_template(
    work_item, cache_node_attr: str = "cache_node"
) -> None:
    cache_path = work_item.stringAttribValue(cache_node_attr)
    cache_node = hou.node(cache_path)

    if cache_node is None:
        raise RuntimeError(f"Cache node '{cache_path}' not found")

    publish_name = cache_node.evalParm("name").strip()

    tk, ctx, sg = _sg_handles()
    pf_type_id = _get_pf_type_id(sg, "oom_renderpass_wedged")
    version = _next_version(sg, ctx, pf_type_id, publish_name)

    path = _sequence_path_from_template("oom_renderpass_wedged", publish_name, version)

    pub = _create_publish(sg, ctx, pf_type_id, publish_name, path, version)

    work_item.setIntAttrib("sg_publish_id", pub["id"])
    work_item.setStringAttrib("image_path", path)


def publish_comp_from_template(work_item, cache_node_attr: str = "cache_node") -> None:
    cache_path = work_item.stringAttribValue(cache_node_attr)
    cache_node = hou.node(cache_path)

    if cache_node is None:
        raise RuntimeError(f"Cache node '{cache_path}' not found")

    publish_name = cache_node.evalParm("name").strip()

    tk, ctx, sg = _sg_handles()
    pf_type_id = _get_pf_type_id(sg, "oom_comp")
    version = _next_version(sg, ctx, pf_type_id, publish_name)

    path = _sequence_path_from_template("oom_comp", publish_name, version)

    # For the TOP graph, keep some Houdini-friendly variants
    hou_path = path.replace("%4d", "$F4")
    hou_prefix = path.replace("%4d.exr", "")

    pub = _create_publish(sg, ctx, pf_type_id, publish_name, path, version)

    work_item.setIntAttrib("sg_publish_id", pub["id"])
    work_item.setStringAttrib("image_path", hou_path)
    work_item.setStringAttrib("image_prefix", hou_prefix)


# -----------------------------------------------------------------------------
# Dailies (Version entity) for Comp
# -----------------------------------------------------------------------------
def create_comp_daily_version(work_item, cache_node_attr: str = "cache_node") -> None:
    """Create a ShotGrid Version (daily) for a comp publish and upload the movie.

    Replicates the existing TOPs Python logic for OOM Comp HDA:
    - Builds a human-friendly Version.code based on Step/Project/Shot/name
    - Creates a Version linked to the current entity (and task if available)
    - Uploads the generated movie (mp4) to sg_uploaded_movie
    """

    # Handles
    tk, ctx, sg = _sg_handles()

    # Cache node and publish name/description
    cache_path = work_item.stringAttribValue(cache_node_attr)
    cache_node = hou.node(cache_path)
    if cache_node is None:
        raise RuntimeError(f"Cache node '{cache_path}' not found")

    publish_name = cache_node.parm("name").evalAsString()
    publish_description = cache_node.parm("description").evalAsString()

    # Step / Project / Shot code via template fields
    step_name = None
    try:
        step_name = ctx.step["name"]
    except Exception:
        step_name = "UnknownStep"

    project_name = ctx.project.get("name") if isinstance(ctx.project, dict) else None

    template = tk.templates["oom_comp"]
    fields = ctx.as_template_fields(template)
    shot_code = f"{fields.get('Sequence')}_{fields.get('Shot')}"

    daily_name = f"{step_name}_Daily_{project_name}_{shot_code}_{publish_name}"

    # Build Version data; include task if available
    version_data = {
        "project": ctx.project,
        "entity": ctx.entity,
        "code": daily_name,
        "description": publish_description,
        "sg_status_list": "rev",
    }
    if getattr(ctx, "task", None):
        version_data["sg_task"] = ctx.task

    version = sg.create("Version", version_data)

    # Upload the movie generated by the TOP graph
    file_path = work_item.stringAttribValue("image_path")
    mov_path = file_path.replace("$F4.exr", "mp4")

    sg.upload(
        entity_type="Version",
        entity_id=version["id"],
        path=mov_path,
        field_name="sg_uploaded_movie",
        display_name=os.path.basename(mov_path),
    )

    # Store the Version id in case downstream TOPs want it
    work_item.setIntAttrib("sg_version_id", version["id"])
