import os
import socket
import sys

# ruff: noqa: I001
import oom_sg_tk
import sgtk

import oom_sg_auth
from oom_bootstrap import bootstrap


def main():
    # Environment Setup
    hostname = socket.gethostname()
    os.environ["SHOTGUN_HOME"] = os.path.expanduser(f"~/.shotgun-{hostname}")
    ssl_cert = (
        os.environ.get("SSL_CERT_FILE")
        or os.environ.get("OOM_SSL_CERT_FILE")
        or "/mnt/RAID/Assets/shotgun/certs/cacert.pem"
    )
    os.environ["SSL_CERT_FILE"] = ssl_cert

    # Argument Parsing
    def parse_args(argv):
        arg_count = len(argv) - 1

        if arg_count == 1:
            return argv[1], None, None

        if arg_count == 3:
            return argv[1], argv[2], argv[3]

        print("Usage: oom <Project> [<Sequence> <Shot>]")
        sys.exit(1)

    def resolve_project_path(tk_instance, project_entity):
        tank_name = (project_entity.get("tank_name") or "").strip()

        if not tank_name:
            return None

        data_roots = tk_instance.pipeline_configuration.get_data_roots() or {}

        for root_path in data_roots.values():
            if not root_path:
                continue

            normalized = os.path.normpath(root_path)

            if os.path.basename(normalized) == tank_name:
                return normalized

            candidate = os.path.join(normalized, tank_name)

            if os.path.isdir(candidate):
                return candidate

            return candidate

        return None

    project_name, sequence_name, shot_name = parse_args(sys.argv)

    # ShotGrid Connection Setup
    user = oom_sg_auth.oom_auth()
    sg = user.create_sg_connection()

    project = sg.find_one(
        "Project", [["name", "is", project_name]], ["id", "tank_name"]
    )
    if project is None:
        print("Not a project")
        sys.exit(1)

    # Toolkit Bootstrap
    engine, tk, sg = bootstrap(project)

    # Context Resolution
    sequence = None
    shot = None

    if sequence_name:
        sequence = sg.find_one(
            "Sequence",
            [["project", "is", project], ["code", "is", sequence_name]],
            ["id"],
        )

        if sequence is None:
            print("Not a sequence")
            sys.exit(1)

    if shot_name:
        if sequence is None:
            print("Sequence name required when specifying a shot")
            sys.exit(1)

        shot = sg.find_one(
            "Shot",
            [
                ["project", "is", project],
                ["sg_sequence", "is", sequence],
                ["code", "is", shot_name],
            ],
            ["id", "sg_cut_in", "sg_cut_out"],
        )

        if shot is None:
            print("Not a shot")
            sys.exit(1)

    # Context Application
    if shot:
        context = tk.context_from_entity("Shot", shot["id"])
    else:
        context = tk.context_from_entity("Project", project["id"])

    engine.change_context(context)
    print(engine)

    # Filesystem Preparation
    tk.synchronize_filesystem_structure()

    if shot:
        tk.create_filesystem_structure("Shot", shot["id"])
    else:
        tk.create_filesystem_structure("Project", project["id"])

    # Path Resolution
    project_path = resolve_project_path(tk, project)
    shot_path = None

    if shot:
        template = tk.templates.get("shot_dir")

        if template:
            fields = {
                "Project": project_name,
                "Sequence": sequence_name,
                "Shot": shot_name,
            }

            shot_path = template.apply_fields(fields)

    # Environment File Export
    def write_env_file():
        env_file = "/tmp/oom.env"
        with open(env_file, "w") as handle:
            handle.write(f'export OOM_PROJECT_ID="{project["id"]}"\n')

            if project_path:
                handle.write(f'export OOM_PROJECT_PATH="{project_path}"\n')

            if sequence:
                handle.write(f'export OOM_SEQUENCE_ID="{sequence["id"]}"\n')

            if shot:
                handle.write(f'export OOM_SHOT_ID="{shot["id"]}"\n')

                if shot_path:
                    handle.write(f'export OOM_SHOT_PATH="{shot_path}"\n')

                cut_in = shot.get("sg_cut_in")
                cut_out = shot.get("sg_cut_out")

                if cut_in is not None and cut_out is not None:
                    handle.write(f'export CUT_IN="{cut_in}"\n')
                    handle.write(f'export CUT_OUT="{cut_out}"\n')
        os.chmod(env_file, 0o777)

    write_env_file()
