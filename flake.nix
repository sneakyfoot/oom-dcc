{
  description = "OOM DCC pipeline";

  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  inputs.tkcore = {
    url = "github:shotgunsoftware/tk-core";
    flake = false;
  };

  outputs = { self, nixpkgs, tkcore }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
        config.cudaSupport = true;
      };

      src = pkgs.lib.cleanSource ./.;

      python = pkgs.python311;
      uv = pkgs.uv;

      tkCorePath = "${tkcore}/python";
      uvProjectEnv = "/var/uv/venvs/oom-dcc";

      runtime = import ./nix/runtime.nix {
        inherit pkgs tkCorePath uvProjectEnv python uv src;
      };

      houdini = import ./nix/houdini.nix {
        inherit pkgs uvProjectEnv python uv src;
        runtimePkgs = runtime.runtimePkgs;
        runtimeProfile = runtime.runtimeProfile;
      };

      cli = import ./nix/cli.nix {
        inherit pkgs uvProjectEnv python uv src;
      };
    in
    {
      devShells.${system}.default = pkgs.mkShell {

        name = "oom-dcc-dev";
        packages = [ python uv ];

        shellHook = ''
          export UV_PYTHON=${python}/bin/python
          export UV_NO_MANAGED_PYTHON=1
          export UV_NO_PYTHON_DOWNLOADS=1
          repo_root="$(git rev-parse --show-toplevel 2>/dev/null || printf '%s\n' "$PWD")"
          export UV_PROJECT_ENVIRONMENT="$repo_root/.venv"
          export VIRTUAL_ENV="$UV_PROJECT_ENVIRONMENT"
          export PATH="$VIRTUAL_ENV/bin:$PATH"
          export SGTK_PATH=${tkCorePath}
          export PYTHONPATH="$SGTK_PATH:$PYTHONPATH"
        '';
      };

      packages.${system} = {
        dcc-runtime = runtime.dcc-runtime;
        houdini-fhs = houdini.houdiniFhsEnv;
        houdini = houdini.houdiniWrapper;
        houdini-container = houdini.houdiniContainerImage;
        mplay = houdini.mplayWrapper;
        oom = cli.oom;
      };
    };
}
