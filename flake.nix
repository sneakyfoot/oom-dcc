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
      pythonEnvNix = import ./nix/python-env.nix {
        inherit pkgs src;
      };
      pythonEnv = pythonEnvNix.pythonEnv;
      pythonPath = pythonEnvNix.pythonPath;
      pythonToolchain = pythonEnvNix.toolchain;

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

      houdini = import ./nix/houdini.nix {
        inherit
          pkgs
          pythonEnv
          pythonPath
          src
          shaTag
          ;
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

      agent_server = import ./nix/server.nix {
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
          OCIO = ocio.configPath;
        };

        shellHook = ''
          echo "OOM DCC Development Shell"
          echo "=========================="
          echo ""
          echo "Run agent server: python -m oom_agent.server"
          echo "Run MCP server:   python -m oom_agent.mcp_server"
          echo "Run MCP client:   python -m oom_agent.mcp_client_example"
          echo ""
        '';
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
        agent-server = agent_server.agentServer;
        mcp-server = agent_server.mcpServer;
      };
    };
}
