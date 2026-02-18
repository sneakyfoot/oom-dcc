{
  description = "OOM DCC pipeline";

  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
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

      shaTag = self.shortRev or self.dirtyShortRev;

      ocio = {
        configPath = "/mnt/RAID/Assets/studio-config-all-views-v3.0.0_aces-v2.0_ocio-v2.4.ocio";
      };

      runtime = import ./nix/runtime.nix {
        inherit pkgs uvBundle src;
      };

      houdini = import ./nix/houdini.nix {
        inherit
          pkgs
          uvBundle
          src
          shaTag
          ;
        runtimePkgs = runtime.runtimePkgs;
        runtimeProfile = runtime.runtimeProfile;
        ocioConfigPath = ocio.configPath;
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
          OCIO = ocio.configPath;
        };

        shellHook = "";
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
