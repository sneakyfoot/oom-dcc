import nuke

# Prefer PySide6 (optional, for message dialogs); fallback to PySide2
try:
    from PySide6 import QtWidgets  # type: ignore
except Exception:
    try:
        from PySide2 import QtWidgets  # type: ignore
    except Exception:
        QtWidgets = None


def _set_cut_range(cut_in, cut_out):
    try:
        r = nuke.root()
        r['first_frame'].setValue(int(cut_in))
        r['last_frame'].setValue(int(cut_out))
        try:
            r['lock_range'].setValue(True)
        except Exception:
            pass
        return True
    except Exception:
        return False


def launch():
    try:
        tk = getattr(nuke, 'oom_tk', None)
        context = getattr(nuke, 'oom_context', None)
        if not tk or not context:
            if QtWidgets:
                QtWidgets.QMessageBox.warning(None, 'OOM', 'Toolkit context not initialized.')
            return

        sg = tk.shotgun
        # Resolve a Shot id from current context
        ent = context.entity
        shot_id = None
        if ent and ent.get('type') == 'Shot':
            shot_id = ent.get('id')
        elif context.task and context.task.get('id'):
            t = sg.find_one('Task', [['id', 'is', context.task.get('id')]], ['entity'])
            e2 = t.get('entity') if t else None
            if e2 and e2.get('type') == 'Shot':
                shot_id = e2.get('id')

        if not shot_id:
            if QtWidgets:
                QtWidgets.QMessageBox.information(None, 'OOM', 'No Shot context to sync cut range from.')
            return

        shot = sg.find_one('Shot', [['id', 'is', int(shot_id)]], ['sg_cut_in', 'sg_cut_out'])
        if not shot or shot.get('sg_cut_in') is None or shot.get('sg_cut_out') is None:
            if QtWidgets:
                QtWidgets.QMessageBox.information(None, 'OOM', 'Shot has no sg_cut_in/sg_cut_out.')
            return

        ok = _set_cut_range(shot.get('sg_cut_in'), shot.get('sg_cut_out'))
        if not ok and QtWidgets:
            QtWidgets.QMessageBox.warning(None, 'OOM', 'Failed to set frame range.')
    except Exception as e:
        try:
            nuke.message(f'[oom] Sync Cut Range failed: {e}')
        except Exception:
            pass

