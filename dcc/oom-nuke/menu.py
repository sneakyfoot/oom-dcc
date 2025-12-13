import os
import nuke

# Try Qt for a deferred call after UI is up
try:
    from PySide6 import QtCore  # type: ignore
except Exception:
    try:
        from PySide2 import QtCore  # type: ignore
    except Exception:
        QtCore = None

# Create OOM menu in Nuke and wire commands to our tools
oom_menu = nuke.menu('Nuke').addMenu('OOM')


def _cmd(label, func_path):
    # Use string command for compatibility across Nuke versions
    mod_path, func_name = func_path.rsplit('.', 1)
    command = f"import {mod_path} as _oom_mod; _oom_mod.{func_name}()"
    oom_menu.addCommand(label, command)


_cmd('OOM Load', 'oom.file_load.launch')
_cmd('OOM Save', 'oom.file_save.launch')
_cmd('OOM Version Up', 'oom.file_version_up.launch')

# Utilities
_cmd('Sync Cut Range', 'oom.sync_cut_range.launch')

# IO helpers
# Keep node creation discoverable via the Nodes toolbar (Tab) only.
# Old OOM menu items for inserting Read/Write have been removed to reduce clutter.


# On GUI startup, perform an optional one-time cut range sync after UI/menu is ready
def _auto_sync_cut_range():
    if os.getenv('OOM_NUKE_DISABLE_AUTO_SYNC_CUT') == '1':
        return

    # Schedule a few attempts since some host init steps reset the range late
    delay_ms = int(os.getenv('OOM_NUKE_AUTO_SYNC_DELAY_MS', '1000'))
    attempts = int(os.getenv('OOM_NUKE_AUTO_SYNC_ATTEMPTS', '3'))

    def _attempt(remaining):
        try:
            import oom.sync_cut_range as _scr
            _scr.launch()
            if remaining == attempts:
                print('[oom] Auto Sync Cut Range (initial)')
        except Exception as e:
            try:
                nuke.tprint(f'[oom] Auto Sync Cut Range skipped: {e}')
            except Exception:
                pass
        finally:
            if remaining > 1 and QtCore is not None:
                QtCore.QTimer.singleShot(delay_ms, lambda: _attempt(remaining - 1))

    _attempt(attempts)


if QtCore is not None:
    try:
        # Kick off after menus are built; subsequent attempts are scheduled inside
        QtCore.QTimer.singleShot(500, _auto_sync_cut_range)
    except Exception:
        _auto_sync_cut_range()
else:
    _auto_sync_cut_range()


# Register gizmos to Nodes toolbar so they appear in Tab search
def _register_gizmos_to_toolbar():
    if os.getenv('OOM_NUKE_DISABLE_NODE_REG') == '1':
        return
    try:
        ROOT_DIR = os.path.dirname(__file__)
        GIZMOS_DIR = os.path.join(ROOT_DIR, 'gizmos')
        if not os.path.isdir(GIZMOS_DIR):
            return
        import glob
        patterns = [
            os.path.join(GIZMOS_DIR, '*.gizmo'),
            os.path.join(GIZMOS_DIR, '*.giz'),
            os.path.join(GIZMOS_DIR, '*.gzind'),
            os.path.join(GIZMOS_DIR, '*.gizind'),
        ]
        classes = set()
        for pat in patterns:
            for fp in glob.glob(pat):
                base = os.path.basename(fp)
                name, _ext = os.path.splitext(base)
                if name:
                    classes.add(name)

        if not classes:
            return

        tb = nuke.toolbar('Nodes')
        oom_menu = None
        try:
            oom_menu = tb.addMenu('OOM')
        except Exception:
            oom_menu = tb

        for cls in sorted(classes):
            try:
                oom_menu.addCommand(cls, f'nuke.createNode("{cls}")')
            except Exception:
                pass
        nuke.tprint(f"[oom] Registered gizmo nodes: {', '.join(sorted(classes))}")
    except Exception as e:
        try:
            nuke.tprint(f"[oom] Gizmo toolbar registration skipped: {e}")
        except Exception:
            pass


_register_gizmos_to_toolbar()
