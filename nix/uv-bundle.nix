{ pkgs, src, pythonSpec ? "3.11", appName ? "oom-dcc" }:

let
  toolchain =
    [ pkgs.uv pkgs.ruff pkgs.ty pkgs.cacert pkgs.makeWrapper pkgs.zlib pkgs.openssl pkgs.stdenv.cc ];

  uvBundle =
    pkgs.stdenvNoCC.mkDerivation {
      pname = "${appName}-uv-bundle";
      version = "0.1.0";
      inherit src;

      # Build with: --option sandbox relaxed
      __noChroot = true;
      preferLocalBuild = true;
      allowSubstitutes = false;
      dontFixup = true;

      nativeBuildInputs = toolchain;

      installPhase = ''
        set -euo pipefail

        export HOME="$TMPDIR/home"
        mkdir -p "$HOME"

        export UV_CACHE_DIR="$TMPDIR/uv-cache"
        export UV_MANAGED_PYTHON=1
        export UV_PYTHON_INSTALL_DIR="$out/python"
        export UV_PROJECT_ENVIRONMENT="$out/venv"

        uv python install ${pythonSpec}
        uv venv --python ${pythonSpec}
        # Keep the local project editable so entrypoints resolve modules.
        uv sync --project ${src} --frozen --no-dev

        mkdir -p "$out/bin"
        find "$UV_PROJECT_ENVIRONMENT/bin" -maxdepth 1 -type f -executable -exec ln -sf {} "$out/bin/" \;
      '';
    };
in {
  inherit uvBundle toolchain;
}
