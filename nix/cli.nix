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
      if [ -z "''${UV_PROJECT_ENVIRONMENT:-}" ]; then
        UV_PROJECT_ENVIRONMENT="$HOME/.cache/uv/venvs/oom-dcc"
      fi
      if [ -z "''${UV_CACHE_DIR:-}" ]; then
        UV_CACHE_DIR="$HOME/.cache/uv/cache"
      fi
      export UV_PROJECT_ENVIRONMENT
      export UV_CACHE_DIR
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
