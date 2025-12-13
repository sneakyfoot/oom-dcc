import os
import nuke


def _ensure_toolkit():
    engine = getattr(nuke, 'oom_engine', None)
    tk = getattr(nuke, 'oom_tk', None)
    context = getattr(nuke, 'oom_context', None)
    if engine and tk:
        return engine, tk, tk.shotgun, context
    try:
        import oom_sg_tk  # noqa: F401
        from oom_bootstrap import bootstrap
        engine, tk, sg = bootstrap()
        context = getattr(nuke, 'oom_context', None) or tk.context_empty()
        nuke.oom_engine = engine
        nuke.oom_tk = tk
        nuke.oom_context = context
        return engine, tk, sg, context
    except Exception as e:
        raise RuntimeError(f"Toolkit bootstrap failed: {e}")


def insert_write(name_hint='comp', version=1, file_ext='exr'):
    """Create a Write node with file path derived from template `oom_nuke_dir`.

    The final path is `<oom_nuke_dir>/<name_hint>.%04d.<ext>`.
    """
    engine, tk, sg, context = _ensure_toolkit()
    tmpl = tk.templates.get('oom_nuke_dir')
    if not tmpl:
        nuke.message('[oom] Missing template: oom_nuke_dir')
        return

    try:
        fields = context.as_template_fields(tmpl)
        # Ensure Step field maps properly
        step = context.step
        if step and 'Step' not in fields:
            fields['Step'] = step.get('code') or step.get('name')
        fields['name'] = name_hint
        fields['version'] = version
        base_dir = tmpl.apply_fields(fields)
        os.makedirs(base_dir, exist_ok=True)
        # Use Nuke-style frame token #### instead of %04d
        file_path = os.path.join(base_dir, f"{name_hint}.####.{file_ext}")
    except Exception as e:
        nuke.message(f"[oom] Failed resolving oom_nuke_dir: {e}")
        return

    node = nuke.createNode('Write', inpanel=False)
    try:
        node['file'].setValue(file_path)
    except Exception:
        pass
    try:
        if file_ext.lower() == 'exr' and 'file_type' in node.knobs():
            node['file_type'].setValue('exr')
    except Exception:
        pass
    nuke.tprint(f"[oom] Created Write node -> {file_path}")
