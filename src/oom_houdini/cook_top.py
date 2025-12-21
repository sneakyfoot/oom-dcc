import hou
import sys
from oom_houdini import oom_cache


# Helpers
def _normalized_op_name(hou_node):
    """
    Return the operator name regardless of namespacing/versioning.

    Examples
    - "oom::oom_fetch::0.1" -> "oom_fetch"
    - "oom_fetch" -> "oom_fetch"
    """
    try:
        raw_name = hou_node.type().name()
    except Exception:
        return None

    # Split on Houdini HDA namespace/version separators
    parts = [p for p in raw_name.split("::") if p]

    # Prefer the last non-version token (avoids selecting "0.1")
    non_version = [p for p in parts if not p.replace(".", "").isdigit()]
    if non_version:
        return non_version[-1]

    # Fallback to last part if everything looked like a version
    return parts[-1] if parts else None


def find_all_upstream_nodes(node_path):
    start_node = hou.node(node_path)
    visited = set()
    result = []

    def walk(node):
        if node.path() in visited:
            return
        visited.add(node.path())
        result.append(node)
        for input_node in node.inputs():
            if input_node is not None:
                walk(input_node)

    walk(start_node)
    return result


def pre_update_cache(upstream_nodes):
    for cache_node in upstream_nodes:
        # Normalize node type so both "oom::oom_fetch::0.1" and "oom_fetch" match
        node_type = _normalized_op_name(cache_node)
        if node_type == "oom_fetch":
            if not cache_node.parm("enable").eval():
                continue
            target = cache_node.parm("node").evalAsString()
            target_node = hou.node(target)
        elif node_type == "oom_cache" or node_type == "oom_lop_publish":
            target_node = cache_node
        else:
            return
        # refresh versions (disambiguate by publish type based on filename)
        cache_name = target_node.parm("name").eval()
        pf_code = None
        try:
            fname_expr = target_node.parm("filename").unexpandedString()
            if ".usd" in fname_expr.lower():
                pf_code = "oom_usd_publish"
            else:
                pf_code = oom_cache.CACHE_PUBLISHED_TYPE_CODE
        except Exception:
            # Fallback to cache type if filename parm missing
            pf_code = oom_cache.CACHE_PUBLISHED_TYPE_CODE

        versions = oom_cache.get_versions(cache_name, pf_code)
        # append pending version to list
        if not versions:
            new_version = 0
        else:
            new_version = versions[-1]
        new_version += 1
        versions.append(new_version)
        # set version parms to new version
        oom_cache.store_versions(target_node, versions)
        target_node.parm("selected_version").set(str(new_version))
        target_node.parm("version").set(0)
        # spare_versions = target_node.parm("spare_versions").eval()
        # print(spare_versions)


def _cook_node(node_path: str, *, block: bool = True) -> None:
    """Cook the given TOP node in the current Houdini session.

    Parameters
    ----------
    node_path
        Path to the TOP node to cook.
    block
        If ``True`` this function blocks until cooking completes. When
        ``False`` the cook happens asynchronously.
    """
    node = hou.node(node_path)
    if not node:
        raise RuntimeError(f"Node {node_path} not found!")

    print("[oom] Cooking work items")
    node.dirtyAllWorkItems(False)
    node.generateStaticWorkItems(True, nodes=[node])
    node.cookWorkItems(block, False, False, False, nodes=[node])
    print("[oom] Finished cooking")


def cook(hip_file: str, node_path: str) -> None:
    """Load ``hip_file`` and cook ``node_path`` in a background hython."""
    hou.hipFile.load(hip_file)
    _cook_node(node_path, block=True)
    print("[oom] Exiting")
    sys.exit()


def cook_in_session(node_path: str) -> None:
    """Cook ``node_path`` without loading a new HIP file."""
    _cook_node(node_path, block=False)


def agent_cook(node_path: str):
    upstream_nodes = find_all_upstream_nodes(node_path)
    pre_update_cache(upstream_nodes)
    hou.hipFile.saveAndBackup()

    try:
        cook_in_session(node_path)
    except Exception as e:
        return f"Failed to cook: {e}"
