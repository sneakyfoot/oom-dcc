# Shim that re-exports the real scheduler from oom-core.


from oom_houdini.oom_scheduler import oom_scheduler, registerTypes


__all__ = [
    "oom_scheduler",
    "registerTypes",
]
