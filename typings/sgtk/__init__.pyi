"""Type stubs for sgtk to satisfy static analysis.

tk-core installs modules under tank.*, and sgtk/__init__.py remaps sys.modules
at runtime. For type checkers, we mirror that layout explicitly.
"""

import tank.bootstrap as bootstrap

__all__ = ["bootstrap"]
