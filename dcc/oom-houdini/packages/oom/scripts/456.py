import os
import sys
from pathlib import Path
from pprint import pformat

import hou
import sgtk

from oom_bootstrap import bootstrap

print("[oom] Running Houdini load script")
PROJECT_ROOT = "/mnt/RAID/Projects"
LOCAL_STORAGE_CODE = "RAID"


def context_from_path(path, tk, engine, sg=None):
    if sg is None:
        sg = tk.shotgun

    project_name = Path(path).relative_to(PROJECT_ROOT).parts[0]
    print("Project_name:")
    print(project_name)
    project = sg.find_one("Project", [["tank_name", "is", project_name]], ["id"])
    if not project:
        raise RuntimeError(f"No SG project with tank_name='{project_name}'")
    engine.destroy_engine()
    sgtk.platform.engine.set_current_engine(None)
    # sgtk.platform.current_engine().destroy()
    # sgtk.platform.engine.set_current_engine(None)
    engine, tk, sg = bootstrap(project)
    tk.synchronize_filesystem_structure()
    print(path)
    context = tk.context_from_path(path)
    if context.step is None or context.task is None:
        print("[oom] Context missing step or task – querying ShotGrid")

        # fall back to PublishedFile lookup by name and version if path filter fails
        fields = tk.templates["oom_hip_file"].get_fields(path)
        pub = sg.find_one(
            "PublishedFile",
            [
                ["project", "is", context.project],
                ["code", "is", fields.get("name")],
                ["version_number", "is", fields.get("version")],
            ],
            ["task", "task.Task.step"],
        )
        if pub:
            task = pub.get("task")
            step = pub.get("task.Task.step")
            if step and "name" not in step:
                step = dict(step)
                step["name"] = step.get("code")
            if task and "name" not in task:
                task = dict(task)
                task["name"] = task.get("content")
            if step and context.step is None:
                context = tk.context_from_entity("Step", step.get("id"))
            if task and context.task is None:
                context = tk.context_from_entity("Task", task.get("id"))
            print(
                f"[oom] Restored context from SG – step: {context.step}, task: {context.task}"
            )
        else:
            print("[oom] No PublishedFile found to restore context")

    engine.change_context(context)
    print(context)
    return engine, tk, sg, context


try:
    # ── 0. Re‑use handles if 123.py already bootstrapped ───────────────
    tk = getattr(hou.session, "oom_tk", None)
    engine = getattr(hou.session, "oom_engine", None)
    context = getattr(hou.session, "oom_context", None)
    test = 0
    # ── 1. Bootstrap tk‑shell if nothing exists yet ───────────────
    # if tk is None or engine is None:
    #     print("[oom] Missing Toolkit session – bootstrapping tk‑shell")

    #     # bootstrap
    #     engine,tk,sg = bootstrap()

    # ── 2. Update context whenever a hip is (re)loaded ─────────────────
    hip_path = hou.hipFile.path()
    if hip_path and os.path.exists(hip_path):
        # bootstrap if no engine
        if engine is None:
            print("[oom] Missing Toolkit session – bootstrapping tk‑shell")
            # bootstrap
            engine, tk, sg = bootstrap()

        # start up new engine in current context
        engine, tk, sg, context = context_from_path(hip_path, tk, engine)
        hou.session.oom_context = context
        hou.session.oom_tk = tk
        hou.session.oom_engine = engine

        # Log version if template available
        try:
            template = tk.templates["oom_hip_file"]
            ver = template.get_fields(hip_path).get("version")
            print(f"[oom] Detected file version: {ver}")
        except Exception:
            pass

        # Ensure readable step / task names
        step, task = context.step, context.task
        if step and "name" not in step:
            step = dict(step)
            step["name"] = step.get("code")
            context = tk.context_from_entity("Step", step.get("id"))
        if task and "name" not in task:
            task = dict(task)
            task["name"] = task.get("content")
            context = tk.context_from_entity("Task", task.get("id"))

        # ensure engine context matches any modifications
        hou.session.oom_engine.change_context(context)
        hou.session.oom_context = context
        print(
            f"[oom] Updated Houdini session context to step: {context.step}, task: {context.task}"
        )

        # Pull cut‑range if present
        sg = tk.shotgun
        shot_id = context.entity.get("id") if context.entity else None
        if shot_id:
            shot = sg.find_one(
                "Shot", [["id", "is", shot_id]], ["sg_cut_in", "sg_cut_out"]
            )
            if (
                shot
                and shot["sg_cut_in"] is not None
                and shot["sg_cut_out"] is not None
            ):
                os.environ["CUT_IN"] = str(shot["sg_cut_in"])
                os.environ["CUT_OUT"] = str(shot["sg_cut_out"])

        print(f"[oom] Context updated from hip:\n  {hip_path}")
        print(f"[oom] Current step: {context.step}, task: {context.task}")
    else:
        print("[oom] No valid hip loaded — context unchanged.")

except Exception as e:
    print(f"[oom] Failed in 456.py: {e}")
