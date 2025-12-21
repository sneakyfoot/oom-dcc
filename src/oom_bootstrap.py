import sys, os
import sgtk
from oom_sg_auth import oom_auth
from sgtk.bootstrap import ToolkitManager

def bootstrap(project=None):
    sg_user = oom_auth()
    
    mgr = ToolkitManager(sg_user)
    mgr.plugin_id = "basic.oom"
    mgr.pipeline_configuration = "Primary"
    
    if project is None:
        engine = mgr.bootstrap_engine("tk-shell", entity=None)
    else:
        engine = mgr.bootstrap_engine("tk-shell", entity=project)
    tk = engine.sgtk
    sg = tk.shotgun
    return engine,tk,sg
