#!/usr/bin/env python3
"""
Command-line utility to discover and cook a TOP/PDG network in a Houdini hip file.

This script forks itself into the background to avoid blocking your shell,
but inherits stdout/stderr so progress messages still appear in your terminal.
Bootstrap of the Houdini Python API is handled via `oom_houdini.oom_hou`, so
this can be run under the system Python (3.11+) with the `oom-core` root on
`PYTHONPATH` and Houdini environment variables set.

Usage:
    cook_top_cli.py <hip_name> <node_description>

Environment:
    OOM_CLI_SUBPROCESS=1      internal flag to avoid re-forking
    OOM_CLI_DEBUG=1           enable debug traces (node discovery, filtering)
"""
import os
import sys
# Detach into a background subprocess on first invocation
if __name__ == '__main__' and not os.environ.get('OOM_CLI_SUBPROCESS'):
    # Relaunch in a detached session so the cook can continue if the terminal closes
    import subprocess
    env = os.environ.copy()
    env['OOM_CLI_SUBPROCESS'] = '1'
    subprocess.Popen(
        [sys.executable] + sys.argv,
        env=env,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
    )
    sys.exit(0)

import re
from glob import glob
# enable debug logs when set
DEBUG = bool(os.environ.get('OOM_CLI_DEBUG'))

# Bootstrap Houdini Python API (must be done before importing hou)
import oom_houdini.oom_hou  # noqa: E402
import hou  # noqa: E402

from oom_houdini.cook_top import _cook_node


def find_hip_path(hip_name: str) -> str:
    """Find the most recent hip file matching <hip_name> under the current shot context."""
    shot_path = os.environ.get('OOM_SHOT_PATH')
    if not shot_path:
        print('Error: OOM_SHOT_PATH not set. Run oom-context first.', file=sys.stderr)
        sys.exit(1)
    # Look for HIP files in any step-specific houdini task folder (per shotgun templates)
    tasks_root = os.path.join(shot_path, 'tasks')
    # patterns: try .hip first, then .hiplc
    patterns = [f"{hip_name}.v*.hip", f"{hip_name}.v*.hiplc"]
    candidates: list[str] = []
    # search under tasks/<Step>/houdini
    for houdini_dir in glob(os.path.join(tasks_root, '*', 'houdini')):
        for pat in patterns:
            found = glob(os.path.join(houdini_dir, pat))
            if found:
                candidates = found
                break
        if candidates:
            break
    if not candidates:
        print(
            f"No hip files found matching {hip_name}.v*.hip(.hiplc) in any houdini task under {tasks_root}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Choose the highest numeric version (e.g. v005)
    def version_key(path: str) -> int:
        m = re.search(r"\.v(\d+)\.hip", path)
        return int(m.group(1)) if m else -1

    return max(candidates, key=version_key)


def find_top_nodes() -> list[hou.Node]:
    """Recursively collect all TOP nodes under /obj."""
    root = hou.node('/obj')
    if not root:
        return []
    result: list[hou.Node] = []

    def walk(node: hou.Node) -> None:
        for child in node.children():
            # accept any node in a TOP/PDG context (covers Topnet and PDG networks)
            cat = child.type().category().name().lower()
            if 'top' in cat or 'pdg' in cat:
                result.append(child)
                # debug: log node type and category
                print(f"[oom:debug] found TOP/PDG node: {child.path()} (type={child.type().name()}, cat={cat})", file=sys.stderr)
            walk(child)

    walk(root)
    return result


def find_node(description: str) -> str:
    """Find a single TOP node matching the given description (type or substring)."""
    desc = description.lower()
    nodes = find_top_nodes()
    if DEBUG:
        print(f"[oom:debug] found {len(nodes)} TOP/PDG nodes: {[n.path() for n in nodes]}",
              file=sys.stderr)
    # Filter by common type keywords
    if 'null' in desc:
        nodes = [n for n in nodes if 'null' in n.type().name().lower()]
    # Filter by matching name or path substrings
    candidates = [n for n in nodes if desc in n.name().lower() or desc in n.path().lower()]
    if DEBUG:
        print(f"[oom:debug] matching '{description}': {[n.path() for n in candidates]}",
              file=sys.stderr)
    if not candidates:
        print(f'No TOP nodes found matching description: {description}', file=sys.stderr)
        sys.exit(1)
    if len(candidates) > 1:
        paths = ', '.join(n.path() for n in candidates)
        print(f"Ambiguous description '{description}', candidates: {paths}", file=sys.stderr)
        sys.exit(1)
    return candidates[0].path()


def main(argv: list[str]) -> None:
    if len(argv) != 3:
        print(f"Usage: {os.path.basename(argv[0])} <hip_name> <node_description>", file=sys.stderr)
        sys.exit(1)

    hip_name, description = argv[1], argv[2]
    hip_path = find_hip_path(hip_name)
    print(f"[oom] Loading hip file: {hip_path}")
    try:
        hou.hipFile.load(hip_path)
    except Exception as e:
        print(f"Failed to load hip file: {e}", file=sys.stderr)
        sys.exit(1)

    node_path = find_node(description)
    print(f"[oom] Cooking node: {node_path}")
    _cook_node(node_path, block=True)
    print("[oom] Cook complete.")


if __name__ == '__main__':
    main(sys.argv)
