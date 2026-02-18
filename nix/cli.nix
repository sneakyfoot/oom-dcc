{
  pkgs,
  pythonEnv,
  pythonPath,
  src,
}:
let
  oom = pkgs.writeShellApplication {
    name = "oom";
    runtimeInputs = [
      pkgs.bashInteractive
      pythonEnv
    ];
    text = ''
            set -euo pipefail
            echo "[oom] Setting up environment"
            export PYTHONPATH="${pythonPath}:''${PYTHONPATH:-}"
            ${pythonEnv}/bin/python - "$@" <<'PY'
      from oom_context import main

      main()
      PY
            # shellcheck disable=SC1091
            if [ -f /tmp/oom.env ]; then
              source /tmp/oom.env
              echo "[oom] Entering environment"
              cd "$OOM_SHOT_PATH"
              exec ${pkgs.bashInteractive}/bin/bash
            else
              echo "[oom] /tmp/oom.env not found" >&2
            fi
    '';
  };
in
{
  inherit oom;
}
