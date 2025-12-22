{
  description = "OOM DCC pipeline";

  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
        config.cudaSupport = true;
      };

      src = pkgs.lib.cleanSource ./.;
      uvBundleNix = import ./nix/uv-bundle.nix {
        inherit pkgs src;
        pythonSpec = "3.11";
        appName = "oom-dcc";
      };
      uvBundle = uvBundleNix.uvBundle;
      uvToolchain = uvBundleNix.toolchain;

      shaTag =
        self.shortRev
        or self.dirtyShortRev;

      runtime = import ./nix/runtime.nix {
        inherit pkgs uvBundle src;
      };

      houdini = import ./nix/houdini.nix {
        inherit pkgs uvBundle src shaTag;
        runtimePkgs = runtime.runtimePkgs;
        runtimeProfile = runtime.runtimeProfile;
      };

      cli = import ./nix/cli.nix {
        inherit pkgs uvBundle src;
      };
    in
    {
      devShells.${system}.default = pkgs.mkShell {

        name = "oom-dcc-dev";
        packages = uvToolchain;

        env = {
          UV_MANAGED_PYTHON = "1";
          UV_PROJECT_ENVIRONMENT = ".venv";
          UV_CACHE_DIR = ".uv-cache";
        };

        shellHook = ''
          export SGTK_PATH="$UV_PROJECT_ENVIRONMENT/lib/python3.11/site-packages"
          export PYTHONPATH="$SGTK_PATH:$PYTHONPATH"
        '';
      };

      packages.${system} = {
        oom-uv-bundle = uvBundle;
        dcc-runtime = runtime.dcc-runtime;
        houdini-fhs = houdini.houdiniFhsEnv;
        houdini = houdini.houdiniWrapper;
        houdini-container = houdini.houdiniContainerImage;
        publish-houdini-container = houdini.publishHoudiniContainer;
        mplay = houdini.mplayWrapper;
        oom = cli.oom;
      };
    };
}
