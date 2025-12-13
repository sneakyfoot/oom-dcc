{ pkgs, uvProjectEnv, python, uv, src }:
let
  oom = pkgs.writeShellApplication {
    name = "oom";
    runtimeInputs = [ uv python pkgs.stdenv.cc.cc.lib ];
    text = ''
      set -euo pipefail
      export UV_PYTHON=${python}/bin/python
      export UV_NO_MANAGED_PYTHON=1
      export UV_NO_PYTHON_DOWNLOADS=1
      export UV_PROJECT_ENVIRONMENT=${uvProjectEnv}
      export UV_CACHE_DIR=/var/uv/cache
      uv sync --project ${src} --frozen --no-dev
      echo "[oom] Setting up environment"
      uv run --project ${src} --frozen --no-dev --no-sync oom "$@" # &> /dev/null
      # shellcheck disable=SC1091
      source /tmp/oom.env
      echo "[oom] Entering environment"
      cd "$OOM_SHOT_PATH"
      bash
    '';
  };
in {
  inherit oom;
}
