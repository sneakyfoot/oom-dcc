import os,socket
import oom_sg_tk,oom_sg_auth
from oom_bootstrap import bootstrap
import sgtk

# 3de Tags #
# 3DE4.script.startup: true

print('[oom] Running Startup Script')

# set shotgun home env var for shared /home
hostname = socket.gethostname()
os.environ["SHOTGUN_HOME"] = os.path.expanduser(f"~/.shotgun-{hostname}")
os.environ["SSL_CERT_FILE"] = "/mnt/RAID/Assets/shotgun/certs/cacert.pem"
print(f"[oom] Set SSL Cert for hou, and SHOTGUN_HOME set for {hostname}")

# Get context from environment
project_id = os.getenv("OOM_PROJECT_ID")
shot_id = os.getenv("OOM_SHOT_ID")

if not project_id or not shot_id:
    print("[oom] Missing OOM_PROJECT_ID or OOM_SHOT_ID — skipping bootstrap.")
else:
    project_id = int(project_id)
    shot_id = int(shot_id)

    # Bootstrap
    user = oom_sg_auth.oom_auth()
    sg = user.create_sg_connection()
    project = sg.find_one("Project", [["id", "is", project_id]], ["id"])
    engine,tk,sg = bootstrap(project)

    # set context from shot
    context = tk.context_from_entity("Shot", shot_id)

    # Query cut information from ShotGrid
    shot = sg.find_one(
        "Shot",
        [["id", "is", shot_id]],
        ["sg_cut_in", "sg_cut_out"],
    )
    cut_in = shot.get("sg_cut_in") if shot else None
    cut_out = shot.get("sg_cut_out") if shot else None
    if cut_in is not None and cut_out is not None:
        os.environ["CUT_IN"] = str(cut_in)
        os.environ["CUT_OUT"] = str(cut_out)

    print(f"[oom] Bootstrapped context for Shot ID {shot_id}")
