import os
import nuke
import subprocess
import shlex


def _ensure_toolkit():
    engine = getattr(nuke, "oom_engine", None)
    tk = getattr(nuke, "oom_tk", None)
    context = getattr(nuke, "oom_context", None)
    if engine and tk:
        return engine, tk, tk.shotgun, context
    try:
        import oom_sg_tk  # noqa: F401
        from oom_bootstrap import bootstrap

        engine, tk, sg = bootstrap()
        context = getattr(nuke, "oom_context", None) or tk.context_empty()
        nuke.oom_engine = engine
        nuke.oom_tk = tk
        nuke.oom_context = context
        return engine, tk, sg, context
    except Exception as e:
        raise RuntimeError(f"Toolkit bootstrap failed: {e}")


def _internal_write(node, name: str = "write1"):
    try:
        return node.node(name)
    except Exception:
        return None


def _publish_name_from_gizmo(node) -> str | None:
    try:
        # Prefer a dedicated publish_name knob to avoid clashing with built-in 'name'
        if "publish_name" in node.knobs():
            val = str(node["publish_name"].value()).strip()
            return val or None
        # Fallback: if user still uses 'name', try to read it, but this is the node's label
        if "name" in node.knobs():
            val = str(node["name"].value()).strip()
            return val or None
    except Exception:
        pass
    return None


def update_path(node, write_node_name: str = "write1"):
    """Resolve and set the internal Write's file path using oom_nuke_dir."""
    engine, tk, sg, context = _ensure_toolkit()
    tmpl = tk.templates.get("oom_nuke_dir")
    if not tmpl:
        nuke.message("[oom] Missing template: oom_nuke_dir")
        return

    # Knobs on the gizmo
    name = node["name"].value() if "name" in node.knobs() else "comp"
    version = int(node["version"].value()) if "version" in node.knobs() else 1
    ext = node["ext"].value() if "ext" in node.knobs() else "exr"

    try:
        fields = context.as_template_fields(tmpl)
        step = context.step
        if step and "Step" not in fields:
            fields["Step"] = step.get("code") or step.get("name")
        fields["name"] = name
        fields["version"] = version
        base_dir = tmpl.apply_fields(fields)
        os.makedirs(base_dir, exist_ok=True)
        # Use Nuke-style frame token ####
        path = os.path.join(base_dir, f"{name}.####.{ext}")
    except Exception as e:
        nuke.message(f"[oom] Failed resolving oom_nuke_dir: {e}")
        return

    w = _internal_write(node, write_node_name)
    if not w:
        nuke.message('[oom] OOM_Write gizmo missing internal node "write1"')
        return
    try:
        w["file"].setValue(path)
    except Exception:
        pass


def knob_changed():
    """Wire from gizmo knobChanged.

    python {import oom.nodes.write_gizmo as g; g.knob_changed()}
    """
    try:
        n = nuke.thisNode()
        k = nuke.thisKnob()
    except Exception:
        return

    if k.name() in ("name", "version", "ext"):
        update_path(n)


# ---------------------------------------------------------------------------
# Helpers for publishing and version uploads


def _get_pf_type_id(sg, code: str) -> int:
    rec = sg.find_one("PublishedFileType", [["code", "is", code]], ["id"])
    if not rec:
        raise RuntimeError(f"Missing PublishedFileType: {code}")
    return rec["id"]


def _next_version(sg, ctx, pf_type_id: int, name_code: str) -> int:
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
    versions = sorted(
        {p.get("version_number") for p in pubs if p.get("version_number") is not None}
    )
    return (versions[-1] if versions else 0) + 1


def _latest_publish_version(sg, ctx, pf_type_id: int, name_code: str) -> int:
    """Return the latest PublishedFile version_number for the given name/code.

    Returns 0 if none exist.
    """
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
    versions = [
        int(p.get("version_number"))
        for p in pubs
        if p.get("version_number") is not None
    ]
    return max(versions) if versions else 0


def _latest_version_entity_version(sg, ctx, name_code: str) -> int:
    """Return the highest N parsed from Version.code formatted as '<name>_vNNN'.

    Filters by current project/entity and, if available, current task.
    Returns 0 if none found.
    """
    filters = [
        ["project", "is", ctx.project],
        ["entity", "is", ctx.entity],
        ["code", "contains", f"{name_code}_v"],
    ]
    if getattr(ctx, "task", None):
        # ShotGrid field for Version is 'sg_task'
        filters.append(["sg_task", "is", ctx.task])

    vers = sg.find(
        "Version", filters, ["code"], order=[{"field_name": "id", "direction": "desc"}]
    )

    import re

    max_v = 0
    for v in vers:
        code = v.get("code") or ""
        m = re.search(r"^" + re.escape(name_code) + r"_v(\d+)\b", code)
        if m:
            try:
                max_v = max(max_v, int(m.group(1)))
            except Exception:
                pass
    return max_v


def _latest_version_on_disk(tk, ctx, template_name: str, name: str) -> int:
    """Inspect the template directory and return highest existing version folder number.

    This looks at the parent directory that contains the version folders.
    Returns 0 if not found or non-numeric.
    """
    tmpl = tk.templates.get(template_name)
    if not tmpl:
        return 0

    try:
        fields = ctx.as_template_fields(tmpl)
        step = ctx.step
        if step and "Step" not in fields:
            fields["Step"] = step.get("code") or step.get("name")
        fields["name"] = name
        fields.setdefault("frame", 1)
        fields["version"] = 1
        raw = tmpl.apply_fields(fields)
        dir_path, _fname = os.path.split(raw)
        parent = os.path.dirname(dir_path)
        if not os.path.isdir(parent):
            return 0
        candidates = []
        for entry in os.listdir(parent):
            try:
                v = int(entry)
                candidates.append(v)
            except Exception:
                pass
        return max(candidates) if candidates else 0
    except Exception:
        return 0


def _apply_template_dir(
    tk, context, template_name: str, name: str, version: int, frame_pad: int = 4
) -> tuple[str, str]:
    """Resolve sequence paths from a template (e.g., 'oom_comp' or 'oom_renderpass').

    Returns a tuple:
      - sg_seq: printf-token sequence (e.g., %04d) suitable for ShotGrid publish
      - nuke_seq: hash-token sequence (e.g., ####) suitable for Nuke write
    """
    tmpl = tk.templates.get(template_name)
    if not tmpl:
        raise RuntimeError(f"Missing template: {template_name}")

    fields = context.as_template_fields(tmpl)
    step = context.step
    if step and "Step" not in fields:
        fields["Step"] = step.get("code") or step.get("name")
    # Houdini pattern: start with version=1 and frame=1, then rewrite
    fields["name"] = name
    fields.setdefault("frame", 1)
    fields["version"] = 1

    raw = tmpl.apply_fields(fields)

    # Replace the last directory with the concrete version
    dir_path, fname = os.path.split(raw)
    dirs = dir_path.split(os.sep)
    if dirs:
        dirs[-1] = str(int(version))
    ver_dir = os.sep.join(dirs)

    # Build filename with printf token
    base, rest = fname.split(".", 1)
    ext = rest.split(".")[-1]
    printf_tok = f"%{frame_pad}d"
    file_expr = f"{base}.{printf_tok}.{ext}"

    sg_seq = os.path.join(ver_dir, file_expr)
    nuke_seq = sg_seq.replace(printf_tok, "#" * frame_pad)

    # Ensure directory exists for Nuke writes
    os.makedirs(ver_dir, exist_ok=True)
    return sg_seq, nuke_seq


def _frame_range_from_write(write_node) -> tuple[int, int]:
    try:
        if int(write_node["use_limit"].value()):
            return int(write_node["first"].value()), int(write_node["last"].value())
    except Exception:
        pass
    r = nuke.root()
    return int(r["first_frame"].value()), int(r["last_frame"].value())


def _render_write(write_node, first: int, last: int, incr: int = 1):
    # Prefer Frame Server / background execute if available
    try:
        import nukescripts  # type: ignore

        if hasattr(nukescripts, "executeInBackground"):
            try:
                # Some versions want node names, others accept node objects
                nukescripts.executeInBackground(
                    "OOM Render", [write_node], int(first), int(last), int(incr)
                )
            except Exception:
                nukescripts.executeInBackground(
                    "OOM Render",
                    [write_node.fullName()],
                    int(first),
                    int(last),
                    int(incr),
                )
            return
        fs = getattr(nukescripts, "frameServer", None)
        if fs and hasattr(fs, "render"):
            # frameserver expects a list of nodes
            try:
                fs.render([write_node], int(first), int(last), int(incr))
            except Exception:
                fs.render([write_node.fullName()], int(first), int(last), int(incr))
            return
    except Exception:
        pass
    # Last-resort: some builds expose background execute on nuke module
    try:
        if hasattr(nuke, "executeInBackground"):
            nuke.executeInBackground(
                "OOM Render", [write_node.fullName()], int(first), int(last), int(incr)
            )
            return
    except Exception:
        pass
    # Fallback to direct execute
    nuke.execute(write_node, int(first), int(last), int(incr))


def _version_from_exr_write(gizmo_node, exr_node_name: str = "write_exr") -> int:
    """Try to read the version folder from the internal EXR Write path.

    Returns 0 if not determinable.
    """
    try:
        w = _internal_write(gizmo_node, exr_node_name)
        if not w:
            return 0

        file_path = str(w["file"].value()).strip()
        if not file_path:
            return 0

        # Path shape: .../<version>/<name>.####.exr — we want <version>
        ver_dir = os.path.basename(os.path.dirname(file_path))
        try:
            return int(ver_dir)
        except Exception:
            return 0
    except Exception:
        return 0


def open_render_dialog(gizmo_node, write_node_name: str = "write_exr"):
    """Open Nuke's Render dialog for the internal Write node.

    This mirrors the manual UI path so you can tick "Use Frame Server".
    """
    w = _internal_write(gizmo_node, write_node_name)
    if not w:
        nuke.message(f"[oom] Missing internal node {write_node_name!r}")
        return
    try:
        # Select only our write node
        for n in nuke.allNodes():
            n.setSelected(False)
        w.setSelected(True)
        # Try to invoke the Render dialog menu item
        m = None
        try:
            m = nuke.menu("Nuke").findItem("Render/Render...")
        except Exception:
            m = None
        if m:
            m.execute()
        else:
            # Fallback: open the node panel; user can press Render there
            nuke.show(w)
    except Exception as e:
        nuke.message(f"[oom] Could not open Render dialog: {e}")


def prefer_frame_server_setting():
    """Best-effort: enable any preferences related to Frame Server if present.

    Nuke 16 may not expose programmatic FS render; this toggles likely prefs.
    """
    try:
        prefs = nuke.toNode("preferences")
        if not prefs:
            return False
        changed = False
        for kname, knob in prefs.knobs().items():
            lname = kname.lower()
            if "frame" in lname and "server" in lname:
                try:
                    if hasattr(knob, "setValue"):
                        knob.setValue(True)
                        changed = True
                except Exception:
                    pass
        if changed:
            nuke.tprint("[oom] Enabled Frame Server-related preferences (best-effort)")
        return changed
    except Exception:
        return False


def _create_publish(
    sg, ctx, pf_type_id: int, name: str, sg_seq_path: str, version: int
) -> dict:
    if not getattr(ctx, "task", None):
        raise RuntimeError("Missing Task in context — run OOM Save and select a Task")
    data = {
        "project": ctx.project,
        "entity": ctx.entity,
        "task": ctx.task,
        "code": name,
        "path": {"local_path": sg_seq_path},
        "version_number": version,
        "published_file_type": {"type": "PublishedFileType", "id": pf_type_id},
    }
    return sg.create("PublishedFile", data)


def _encode_mp4_with_ffmpeg(
    seq_printf_path: str, start: int, fps: float, out_path: str, crf: int = 18
) -> None:
    import re

    # ffmpeg tends to prefer %0Nd; coerce %4d -> %04d for safety
    seq_for_ffmpeg = re.sub(r"%([1-9])d", lambda m: f"%0{m.group(1)}d", seq_printf_path)

    # Basic existence check for first frame to produce clearer errors
    try:
        width = 4
        m = re.search(r"%0?(\d+)d", seq_for_ffmpeg)
        if m:
            width = int(m.group(1))
        first_frame_path = re.sub(r"%0?\d+d", f"{start:0{width}d}", seq_for_ffmpeg)
        if not os.path.exists(first_frame_path):
            raise RuntimeError(
                f"Sequence not found: expected first frame '{first_frame_path}'"
            )
    except Exception as _e:
        # Proceed to ffmpeg which will emit a detailed error
        pass

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-framerate",
        str(fps),
        "-start_number",
        str(start),
        "-i",
        seq_for_ffmpeg,
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        out_path,
    ]
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if proc.returncode != 0:
        stderr_tail = "\n".join(proc.stderr.splitlines()[-30:])
        raise RuntimeError(
            f"ffmpeg encode failed (exit {proc.returncode}).\nCommand: {' '.join(shlex.quote(c) for c in cmd)}\n{stderr_tail}"
        )


def _upload_version(
    sg,
    ctx,
    task,
    code: str,
    movie_path: str,
    start: int,
    end: int,
    fps: float,
    description: str | None = None,
) -> dict:
    """Create a ShotGrid Version and upload movie.

    Note: Version's task field is schema'd as 'sg_task', not 'task'.
    """
    data = {
        "project": ctx.project,
        "entity": ctx.entity,
        "code": code,
        "description": (description or "").strip(),
        "sg_first_frame": int(start),
        "sg_last_frame": int(end),
        "frame_count": int(end - start + 1),
        "frame_range": f"{int(start)}-{int(end)}",
        "sg_movie_has_slate": False,
    }
    if task:
        data["sg_task"] = task
    ver = sg.create("Version", data)
    sg.upload("Version", ver["id"], movie_path, field_name="sg_uploaded_movie")
    return ver


# ---------------------------------------------------------------------------
# Public API for gizmo buttons


def render_and_publish_exr(
    gizmo_node,
    name: str | None = None,
    pft_code: str = "oom_comp",
    version: int | None = None,
    write_node_name: str = "write_exr",
):
    """Render EXR sequence via internal write1 and register a ShotGrid publish.

    - name: publish code (defaults to file base of write path)
    - pft_code: PublishedFileType code, e.g. 'oom_comp' or 'oom_renderpass'
    - version: if None, determines next version from ShotGrid for (name, pft_code)
    """
    w = _internal_write(gizmo_node, write_node_name)
    if not w:
        raise RuntimeError('OOM_Write gizmo missing internal node "write1"')

    if not name:
        # Prefer explicit gizmo knob 'name'
        name = _publish_name_from_gizmo(gizmo_node)
    if not name:
        try:
            base = os.path.basename(w["file"].value())
            name = os.path.splitext(base)[0].split(".")[0]
        except Exception:
            name = "comp"

    engine, tk, sg, ctx = _ensure_toolkit()
    pf_type_id = _get_pf_type_id(sg, pft_code)

    # Decide version robustly so repeat runs increment even without a publish.
    if version is None:
        latest_pub_v = _latest_publish_version(sg, ctx, pf_type_id, name)
        latest_ver_v = _latest_version_entity_version(sg, ctx, name)
        latest_disk_v = _latest_version_on_disk(tk, ctx, pft_code, name)
        base = max(latest_pub_v, latest_ver_v, latest_disk_v)
        version = base + 1

    # Use the SG template that matches the publish type (e.g., 'oom_comp')
    sg_seq, nuke_seq = _apply_template_dir(tk, ctx, pft_code, name, version)

    try:
        if "file_type" in w.knobs():
            w["file_type"].setValue("exr")
    except Exception:
        pass
    w["file"].setValue(nuke_seq)

    first, last = _frame_range_from_write(w)
    _render_write(w, first, last)

    pub = _create_publish(sg, ctx, pf_type_id, name, sg_seq, version)
    nuke.tprint(f"[oom] Published EXR sequence as {pft_code} v{version}: {sg_seq}")
    return {
        "publish": pub,
        "sequence": sg_seq,
        "version": version,
        "first": first,
        "last": last,
    }


def render_and_upload_mp4(
    gizmo_node,
    name: str | None = None,
    version: int | None = None,
    fps: float | None = None,
    crf: int = 18,
    pft_code: str = "oom_comp",
    write_node_name: str | None = "write_mp4",
):
    """Encode MP4 for the comp and upload a ShotGrid Version.

    Version selection when not provided:
    - Prefer the version folder from the internal EXR write in this gizmo.
    - Else use the latest PublishedFile version for (name, pft_code) from ShotGrid.
    - Else use the highest version folder found on disk under the template root.
    - Else default to 1.
    """
    engine, tk, sg, ctx = _ensure_toolkit()
    w = _internal_write(gizmo_node, write_node_name or "write1")

    if fps is None:
        try:
            fps = float(nuke.root()["fps"].value())
        except Exception:
            fps = 24.0

    if not name:
        name = _publish_name_from_gizmo(gizmo_node)
    if not name:
        try:
            base = os.path.basename(w["file"].value())
            name = os.path.splitext(base)[0].split(".")[0]
        except Exception:
            name = "comp"

    pf_type_id = _get_pf_type_id(sg, pft_code)

    # Determine version based on the EXR publish/versioning, not "next".
    if version is None:
        ver_from_exr = _version_from_exr_write(gizmo_node, exr_node_name="write_exr")
        latest_pub_v = _latest_publish_version(sg, ctx, pf_type_id, name)
        latest_disk_v = _latest_version_on_disk(tk, ctx, pft_code, name)

        candidates = [
            v for v in (ver_from_exr, latest_pub_v, latest_disk_v) if int(v) > 0
        ]
        version = max(candidates) if candidates else 1

    sg_seq, nuke_seq = _apply_template_dir(tk, ctx, pft_code, name, version)
    first, last = _frame_range_from_write(w)

    mp4_path = os.path.join(os.path.dirname(sg_seq), f"{name}.v{version:03d}.mp4")

    # Prefer the dedicated movie write node if it exists; if it does not exist,
    # fall back to encoding from the EXR sequence via ffmpeg. If the node exists
    # but rendering fails, surface the error instead of silently falling back.
    if write_node_name and w:
        try:
            # Point it at our mp4 path
            w["file"].setValue(mp4_path)
            # Set fps knob if present
            if "fps" in w.knobs():
                w["fps"].setValue(float(fps))
            # Execute across range to write the movie
            _render_write(w, first, last)
        except Exception as e:
            raise RuntimeError(
                f"MP4 write via internal node '{write_node_name}' failed: {e}"
            )
    else:
        # No dedicated node found — use ffmpeg as a fallback only in this case
        _encode_mp4_with_ffmpeg(
            sg_seq, start=first, fps=fps, out_path=mp4_path, crf=crf
        )

    # Optional: pull a user-entered description from the gizmo knob
    try:
        description = str(gizmo_node["version_description"].value()).strip()
    except Exception:
        description = ""

    ver = _upload_version(
        sg,
        ctx,
        ctx.task,
        f"{name}_v{version:03d}",
        mp4_path,
        first,
        last,
        fps,
        description=description,
    )
    nuke.tprint(f"[oom] Uploaded Version with movie: {mp4_path}")
    return {
        "version_entity": ver,
        "movie_path": mp4_path,
        "first": first,
        "last": last,
        "fps": fps,
    }
