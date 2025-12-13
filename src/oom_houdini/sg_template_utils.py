"""
Lightweight helpers for building ShotGrid template fields for Houdini HDAs.

Centralizes common context → template field mapping so individual HDAs can
focus on their path-expression specifics (eg: wedge, frame tokens, etc.).
"""

import hou


def build_template_fields(template, publish_name: str | None = None, include_frame: bool = False) -> dict:

    # Base fields from the current SG context
    context = hou.session.oom_context
    fields = context.as_template_fields(template)

    # Add Step if available (some contexts may not have step)
    try:
        fields["Step"] = context.step["name"]
    except Exception:
        pass

    # Optional publish name override
    if publish_name is not None:
        fields["name"] = publish_name

    # Common defaults used by path templates
    fields["version"] = 1
    if include_frame:
        fields["frame"] = 1

    return fields

