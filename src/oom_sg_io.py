"""
ShotGrid publish query helpers reusable across DCCs (Houdini, Nuke, etc.).

These functions avoid importing DCC modules like `hou` or `nuke` so they can be
shared broadly. All DCC‑specific UI and node interactions should be handled by
callers.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence


def find_publishes(
    sg,
    project: dict,
    entity: dict,
    published_file_types: Sequence[str] | str,
    step: Optional[dict] = None,
    fields: Optional[Sequence[str]] = None,
    order_desc_version: bool = True,
):
    """Find publishes for a project/entity filtered by one or more PFT codes.

    - `published_file_types` can be a single code string or list/tuple of codes.
    - If `step` is provided, it filters via Task->Step.
    - Returns a list of dicts as returned by SG API.
    """
    if fields is None:
        fields = ["code", "name", "version_number", "path", "created_at", "task", "task.Task.step"]

    filters = [["project", "is", project], ["entity", "is", entity]]

    if isinstance(published_file_types, (list, tuple, set)):
        filters.append(["published_file_type.PublishedFileType.code", "in", list(published_file_types)])
    else:
        filters.append(["published_file_type.PublishedFileType.code", "is", published_file_types])

    if step:
        filters.append(["task.Task.step", "is", step])

    order = None
    if order_desc_version:
        order = [{"field_name": "version_number", "direction": "desc"}]

    return sg.find("PublishedFile", filters, list(fields), order=order)


def group_by_code(publishes: Iterable[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for pub in publishes:
        key = pub.get("code") or pub.get("name")
        if not key:
            # Fallback to id if code/name missing
            key = f"publish_{pub.get('id', 'unknown')}"
        grouped.setdefault(key, []).append(pub)
    return grouped


def latest_for_code(
    sg,
    project: dict,
    entity: dict,
    published_file_types: Sequence[str] | str,
    code: str,
    fields: Optional[Sequence[str]] = None,
):
    """Return the latest publish record for the given publish code."""
    pubs = find_publishes(sg, project, entity, published_file_types, step=None, fields=fields)
    # pubs already ordered by version desc by default
    for pub in pubs:
        c = pub.get("code") or pub.get("name")
        if c == code:
            return pub
    return None

