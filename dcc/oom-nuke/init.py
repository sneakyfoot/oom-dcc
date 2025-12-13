import os, sys, socket
import nuke  # pyright: ignore

# Add local plugin paths (absolute; avoid adding '.')
ROOT_DIR = os.path.dirname(__file__)
GIZMOS_DIR = os.path.join(ROOT_DIR, 'gizmos')
PLUGINS_DIR = os.path.join(ROOT_DIR, 'plugins')
try:
    if os.path.isdir(GIZMOS_DIR):
        nuke.pluginAddPath(GIZMOS_DIR)
    if os.path.isdir(PLUGINS_DIR):
        nuke.pluginAddPath(PLUGINS_DIR)
    # Proactively register gizmos, including Nuke Indie extensions
    try:
        import glob
        loaded_flag = '_oom_gizmos_loaded'
        if not getattr(nuke, loaded_flag, False):
            patterns = [
                os.path.join(GIZMOS_DIR, '*.gizmo'),
                os.path.join(GIZMOS_DIR, '*.giz'),
                os.path.join(GIZMOS_DIR, '*.gzind'),  # Nuke Indie
                os.path.join(GIZMOS_DIR, '*.gizind'), # Nuke Indie (alt)
            ]
            for pat in patterns:
                for fp in glob.glob(pat):
                    try:
                        nuke.loadGizmo(fp)
                    except Exception:
                        pass
            setattr(nuke, loaded_flag, True)
    except Exception:
        pass
except Exception:
    pass

# Ensure our python package path is importable (oom package)
PY_DIR = os.path.join(ROOT_DIR, 'python')
if PY_DIR not in sys.path:
    sys.path.insert(0, PY_DIR)
    print(f"[oom] Added to sys.path: {PY_DIR}")

print('[oom] Nuke init starting')

# Set ShotGrid home and certs (shared home layout)
hostname = socket.gethostname()
os.environ["SHOTGUN_HOME"] = os.path.expanduser(f"~/.shotgun-{hostname}")
os.environ["SSL_CERT_FILE"] = "/mnt/RAID/Assets/shotgun/certs/cacert.pem"
print(f"[oom] Set SSL cert and SHOTGUN_HOME for {hostname}")

# Constants used to infer project from path (matches Houdini scripts)
PROJECT_ROOT = "/mnt/RAID2/SHOTGUN_TEST"
LOCAL_STORAGE_CODE = "RAID2"

# Session handles (stored on the nuke module)
setattr(nuke, 'oom_engine', getattr(nuke, 'oom_engine', None))
setattr(nuke, 'oom_tk', getattr(nuke, 'oom_tk', None))
setattr(nuke, 'oom_context', getattr(nuke, 'oom_context', None))

# Runtime flags
IS_GUI = bool(getattr(nuke, 'env', {}).get('gui', ''))
DISABLE = os.getenv('OOM_DISABLE_NUKE_INIT') == '1'
ALLOW_HEADLESS = os.getenv('OOM_NUKE_BOOTSTRAP_HEADLESS') == '1'

# Helpers

def _set_cut_range_on_root(cut_in, cut_out):
    try:
        r = nuke.root()
        r['first_frame'].setValue(int(cut_in))
        r['last_frame'].setValue(int(cut_out))
        # lock range if knob exists to ensure UI/playback honors it
        try:
            r['lock_range'].setValue(True)
        except Exception:
            pass
        os.environ['CUT_IN'] = str(int(cut_in))
        os.environ['CUT_OUT'] = str(int(cut_out))
        print(f"[oom] Set Nuke frame range to {cut_in}-{cut_out}")
    except Exception as e:
        print(f"[oom] Failed setting frame range: {e}")


def _restore_readable_names(context, tk):
    step, task = context.step, context.task
    if step and "name" not in step:
        step = dict(step)
        step["name"] = step.get("code")
        context = tk.context_from_entity("Step", step.get("id"))
    if task and "name" not in task:
        task = dict(task)
        task["name"] = task.get("content")
        context = tk.context_from_entity("Task", task.get("id"))
    return context


def _context_from_path(path, tk, engine, sg=None):
    # Lazy import Toolkit deps to avoid loading in headless unnecessarily
    import oom_sg_tk  # noqa: F401 ensures tk-core on sys.path
    import sgtk
    from oom_bootstrap import bootstrap

    if sg is None:
        sg = tk.shotgun

    # Determine project from path folder under PROJECT_ROOT
    try:
        project_name = os.path.relpath(path, PROJECT_ROOT).split(os.sep)[0]
    except Exception:
        project_name = None

    if project_name:
        print(f"[oom] Project folder inferred: {project_name}")
        project = sg.find_one("Project", [["tank_name", "is", project_name]], ["id"])
        if project:
            try:
                engine.destroy_engine()
            except Exception:
                pass
            try:
                sgtk.platform.engine.set_current_engine(None)
            except Exception:
                pass
            engine, tk, sg = bootstrap(project)
            tk.synchronize_filesystem_structure()

    # Build context directly from path
    context = tk.context_from_path(path)

    # If missing step/task, try looking up a PublishedFile using template fields
    if context.step is None or context.task is None:
        print("[oom] Context missing step or task – querying ShotGrid")
        try:
            fields = None
            # Prefer facility templates; fall back to legacy names
            tmpl = (
                tk.templates.get("oom_nuke_file")
                or tk.templates.get("nuke_shot_work")
                or tk.templates.get("nuke_shot_publish")
            )
            if tmpl:
                fields = tmpl.get_fields(path)
            if fields:
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
                    print(f"[oom] Restored context from SG – step: {context.step}, task: {context.task}")
        except Exception as e:
            print(f"[oom] PublishedFile context restore failed: {e}")

    # Switch engine context if present
    try:
        engine.change_context(context)
    except Exception:
        pass

    print(context)
    return engine, tk, sg, context


def _bootstrap_from_env():
    # Lazy imports: only when env bootstrap is requested
    import oom_sg_tk  # noqa: F401
    import sgtk  # noqa: F401
    from oom_bootstrap import bootstrap
    import oom_sg_auth

    project_id = os.getenv("OOM_PROJECT_ID")
    shot_id = os.getenv("OOM_SHOT_ID")

    if not project_id or not shot_id:
        print("[oom] Missing OOM_PROJECT_ID or OOM_SHOT_ID — skipping bootstrap.")
        return None, None, None, None

    # Auth & bootstrap tk-shell in project scope
    user = oom_sg_auth.oom_auth()
    sg = user.create_sg_connection()
    project = sg.find_one("Project", [["id", "is", int(project_id)]], ["id"])
    engine, tk, sg = bootstrap(project)

    # Context from shot
    context = tk.context_from_entity("Shot", int(shot_id))
    try:
        engine.change_context(context)
    except Exception:
        pass

    # Do not set frame range here; menu.py performs a deferred sync after UI is ready

    print(f"[oom] Bootstrapped Shot context: {context}")
    return engine, tk, sg, context




def _shot_id_from_context(context, sg):
    try:
        ent = context.entity if context else None
        if ent and ent.get('type') == 'Shot':
            return ent.get('id')
        task = context.task if context else None
        if task and task.get('id'):
            t = sg.find_one('Task', [['id', 'is', task.get('id')]], ['entity'])
            ent2 = t.get('entity') if t else None
            if ent2 and ent2.get('type') == 'Shot':
                return ent2.get('id')
    except Exception:
        pass
    return None


def _on_script_load():
    try:
        script_path = nuke.root().name()
        if not script_path or script_path in (None, 'Root', 'Untitled'):
            print('[oom] Script load callback: no valid path')
            return

        # Lazy imports for Toolkit
        import oom_sg_tk  # noqa: F401
        import sgtk
        from oom_bootstrap import bootstrap

        engine = getattr(nuke, 'oom_engine', None)
        tk = getattr(nuke, 'oom_tk', None)

        # If we have no TK yet, bootstrap a generic session
        if engine is None or tk is None:
            print('[oom] No Toolkit session found — bootstrapping site session')
            engine, tk, sg = bootstrap()
        else:
            sg = tk.shotgun

        # Update context from the loaded script path
        engine, tk, sg, context = _context_from_path(script_path, tk, engine, sg)

        # Store for later
        nuke.oom_engine = engine
        nuke.oom_tk = tk
        nuke.oom_context = context

        # Optional: set frame range from Shot entity if available
        shot_id = _shot_id_from_context(context, sg)
        if shot_id:
            shot = sg.find_one('Shot', [['id', 'is', int(shot_id)]], ['sg_cut_in', 'sg_cut_out'])
            if shot and shot.get('sg_cut_in') is not None and shot.get('sg_cut_out') is not None:
                _set_cut_range_on_root(shot.get('sg_cut_in'), shot.get('sg_cut_out'))

        print(f"[oom] Updated Nuke context to step: {nuke.oom_context.step}, task: {nuke.oom_context.task}")
    except Exception as e:
        print(f"[oom] onScriptLoad failed: {e}")


def _sync_cut_range_from_current():
    try:
        tk = getattr(nuke, 'oom_tk', None)
        context = getattr(nuke, 'oom_context', None)
        if not tk or not context:
            return
        sg = tk.shotgun
        shot_id = _shot_id_from_context(context, sg)
        if not shot_id:
            return
        shot = sg.find_one('Shot', [['id', 'is', int(shot_id)]], ['sg_cut_in', 'sg_cut_out'])
        if shot and shot.get('sg_cut_in') is not None and shot.get('sg_cut_out') is not None:
            _set_cut_range_on_root(shot.get('sg_cut_in'), shot.get('sg_cut_out'))
            print('[oom] Sync Cut Range on new script')
    except Exception as e:
        print(f"[oom] Sync Cut Range failed: {e}")


# 1) Bootstrap from env if provided (matches Houdini 123.py)
if not DISABLE:
    try:
        if getattr(nuke, 'oom_engine', None) is None and (IS_GUI or ALLOW_HEADLESS):
            engine, tk, sg, context = _bootstrap_from_env()
            if engine and tk:
                nuke.oom_engine = engine
                nuke.oom_tk = tk
                nuke.oom_context = _restore_readable_names(context, tk) if context else context
    except Exception as e:
        print(f"[oom] Env bootstrap failed: {e}")


# 2) Update context when scripts are opened (Houdini 456.py analogue)
try:
    if not DISABLE and IS_GUI:
        if hasattr(nuke, 'addOnScriptLoad'):
            nuke.addOnScriptLoad(_on_script_load)
        # Some Nuke versions do not support addOnScriptNew; menu.py will handle first-session sync
        if hasattr(nuke, 'addOnScriptNew'):
            nuke.addOnScriptNew(_sync_cut_range_from_current)
        print('[oom] Registered script callbacks where available')
    else:
        print('[oom] Skipping script callback registration (headless or disabled)')
except Exception as e:
    print(f"[oom] Failed registering script callbacks: {e}")
