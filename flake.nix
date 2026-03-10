{
  description = "OOM DCC pipeline";

  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

  # Pin for VFX python3.11 packages (kubernetes etc.) whose dep closure
  # breaks when nixpkgs moves sphinx past python 3.11 support.
  inputs.nixpkgs-py311.url = "github:nixos/nixpkgs/a82ccc39b39b621151d6732718e3e250109076fa";

  outputs =
    {
      self,
      nixpkgs,
      nixpkgs-py311,
    }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
        config.cudaSupport = true;
      };

      pkgs-py311 = import nixpkgs-py311 {
        inherit system;
      };

      src = pkgs.lib.cleanSource ./.;
      pythonEnvNix = import ./nix/python-env.nix {
        inherit pkgs pkgs-py311 src;
      };
      pythonEnv = pythonEnvNix.pythonEnv;
      pythonPath = pythonEnvNix.pythonPath;
      pythonToolchain = pythonEnvNix.toolchain;

      mcpEnvNix = import ./nix/mcp-env.nix {
        inherit pkgs src;
      };
      mcpEnv = mcpEnvNix.mcpEnv;
      mcpPythonPath = mcpEnvNix.mcpPythonPath;

      shaTag = self.shortRev or self.dirtyShortRev;

      ocio = {
        configPath = "/mnt/RAID/Assets/studio-config-all-views-v3.0.0_aces-v2.0_ocio-v2.4.ocio";
      };

      runtime = import ./nix/runtime.nix {
        inherit
          pkgs
          pythonEnv
          pythonPath
          src
          ;
      };

      agent_server = import ./nix/server.nix {
        inherit
          pkgs
          mcpEnv
          mcpPythonPath
          src
          ;
      };

      houdini = import ./nix/houdini.nix {
        inherit
          pkgs
          pythonEnv
          pythonPath
          src
          shaTag
          mcpEnv
          ;
        mcpServer = agent_server.mcpServer;
        runtimePkgs = runtime.runtimePkgs;
        runtimeProfile = runtime.runtimeProfile;
        ocioConfigPath = ocio.configPath;
      };

      cli = import ./nix/cli.nix {
        inherit
          pkgs
          pythonEnv
          pythonPath
          src
          ;
      };
    in
    {
      checks.${system} = {
        oom-python-env = pythonEnv;
        ruff = pkgs.runCommand "oom-ruff" { nativeBuildInputs = [ pkgs.ruff ]; } ''
          cd ${src}
          export XDG_CACHE_HOME="$TMPDIR"
          export RUFF_CACHE_DIR="$TMPDIR/ruff-cache"
          export PYTHONPATH=${pythonPath}
          ruff check src
          touch $out
        '';
        ty =
          pkgs.runCommand "oom-ty"
            {
              nativeBuildInputs = [
                pkgs.ty
                pythonEnv
              ];
            }
            ''
              cd ${src}
              export XDG_CACHE_HOME="$TMPDIR"
              export TY_CACHE_DIR="$TMPDIR/ty-cache"
              export PYTHONPATH=${pythonPath}
              ty check src
              touch $out
            '';
      };

      devShells.${system}.default = pkgs.mkShell {

        name = "oom-dcc-dev";
        packages = pythonToolchain;

        env = {
          PYTHONPATH = pythonPath;
        };

        shellHook = "";
      };

      packages.${system} = {
        oom-python-env = pythonEnv;
        dcc-runtime = runtime.dcc-runtime;
        houdini-fhs = houdini.houdiniFhsEnv;
        houdini = houdini.houdiniWrapper;
        houdini-container = houdini.houdiniContainerImage;
        publish-houdini-container = houdini.publishHoudiniContainer;
        mplay = houdini.mplayWrapper;
        oom = cli.oom;
        mcp-server = agent_server.mcpServer;
      };
    };
}
