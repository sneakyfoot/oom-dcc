{
  description = "OOM DCC pipeline";

  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;

      pyproject = builtins.fromTOML (builtins.readFile ./pyproject.toml);
      requiresPython = pyproject.project."requires-python" or "";
      pythonVersion = "3.11";

      _pythonVersionCheck =
        if nixpkgs.lib.hasInfix pythonVersion requiresPython then
          true
        else
          builtins.throw
            "pyproject.toml requires-python is '${requiresPython}'. Update flake.nix to use python${pythonVersion}.";
    in
    nixpkgs.lib.seq _pythonVersionCheck {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnfree = true;
          };
          lib = pkgs.lib;
          src = lib.cleanSource ./.;
          shaTag = self.shortRev or self.dirtyShortRev or "dirty";

          python = pkgs.python311.override {
            packageOverrides = _self: super:
              let
                fixTar = pkg: pkg.overridePythonAttrs (old: {
                  preUnpack = (old.preUnpack or "") + ''
                    export TAR_OPTIONS="--no-same-owner --no-same-permissions"
                  '';
                });
              in
              {
                "pytest-localserver" = fixTar super."pytest-localserver";
                "requests-oauthlib" = fixTar super."requests-oauthlib";
                oauthlib = fixTar super.oauthlib;
                "google-auth" = fixTar super."google-auth";
                adal = fixTar super.adal;
                kubernetes = fixTar super.kubernetes;
              };
          };
          pythonPkgs = python.pkgs;

          sgtk = pythonPkgs.callPackage ./nix/sgtk.nix { };

          runtimeDeps = with pythonPkgs; [
            kubernetes
            jinja2
            pyyaml
            rich
            setuptools
          ];

          pythonEnv = python.withPackages (_ps: runtimeDeps ++ [ sgtk ]);

          oom = pythonPkgs.buildPythonPackage {
            pname = "oom-dcc";
            version = pyproject.project.version or "0.0.0";
            src = src;
            format = "other";
            dontBuild = true;
            doCheck = false;
            propagatedBuildInputs = runtimeDeps ++ [ sgtk ];
            nativeBuildInputs = [ pkgs.makeWrapper ];

            installPhase = ''
              runHook preInstall

              mkdir -p $out/${python.sitePackages}
              cp -r src/* $out/${python.sitePackages}/

              install -Dm755 /dev/stdin $out/bin/oom <<'SCRIPT'
              #!${python.interpreter}
              from oom_context import main

              if __name__ == "__main__":
                  main()
              SCRIPT

              runHook postInstall
            '';
          };

          runtime = import ./nix/runtime.nix {
            inherit pkgs python pythonEnv src;
          };

          houdini = import ./nix/houdini.nix {
            inherit pkgs python pythonEnv src shaTag;
            runtimePkgs = runtime.runtimePkgs;
            runtimeProfile = runtime.runtimeProfile;
          };
        in
        {
          default = oom;
          oom = oom;
          dcc-runtime = runtime.dcc-runtime;
          houdini = houdini.houdiniWrapper;
          mplay = houdini.mplayWrapper;
          nuke = houdini.nukeWrapper;
        }
      );

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnfree = true;
          };
          python = pkgs.python311.override {
            packageOverrides = _self: super:
              let
                fixTar = pkg: pkg.overridePythonAttrs (old: {
                  preUnpack = (old.preUnpack or "") + ''
                    export TAR_OPTIONS="--no-same-owner --no-same-permissions"
                  '';
                });
              in
              {
                "pytest-localserver" = fixTar super."pytest-localserver";
                "requests-oauthlib" = fixTar super."requests-oauthlib";
                oauthlib = fixTar super.oauthlib;
                "google-auth" = fixTar super."google-auth";
                adal = fixTar super.adal;
                kubernetes = fixTar super.kubernetes;
              };
          };
          pythonPkgs = python.pkgs;
          sgtk = pythonPkgs.callPackage ./nix/sgtk.nix { };
          runtimeDeps = with pythonPkgs; [
            kubernetes
            jinja2
            pyyaml
            rich
            setuptools
          ];
          pythonEnv = python.withPackages (_ps: runtimeDeps ++ [ sgtk ]);
          tyPkg = pkgs.ty;
        in
        {
          default = pkgs.mkShell {
            name = "oom-dcc-dev";
            packages = [
              pythonEnv
              pkgs.ruff
              tyPkg
            ];
            shellHook = ''
              export OOM_CORE="$PWD"
              export PYTHONPATH="$PWD/src:$PWD/stubs:$PYTHONPATH"
            '';
          };
        }
      );

      checks = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnfree = true;
          };
          lib = pkgs.lib;
          src = lib.cleanSource ./.;
          tyPkg = pkgs.ty;
        in
        {
          ruff = pkgs.runCommand "ruff-check" {
            inherit src;
            nativeBuildInputs = [ pkgs.ruff ];
          } ''
            cd $src
            export HOME="$TMPDIR"
            export RUFF_CACHE_DIR="$TMPDIR/ruff-cache"
            mkdir -p "$RUFF_CACHE_DIR"
            ruff check src
            mkdir -p $out
          '';

          ruff-format = pkgs.runCommand "ruff-format" {
            inherit src;
            nativeBuildInputs = [ pkgs.ruff ];
          } ''
            cd $src
            export HOME="$TMPDIR"
            export RUFF_CACHE_DIR="$TMPDIR/ruff-cache"
            mkdir -p "$RUFF_CACHE_DIR"
            ruff format --check src
            mkdir -p $out
          '';

          ty = pkgs.runCommand "ty-check" {
            inherit src;
            nativeBuildInputs = [ tyPkg ];
          } ''
            cd $src
            export HOME="$TMPDIR"
            ty check src \
              --ignore unresolved-import \
              --extra-search-path stubs \
              --extra-search-path src
            mkdir -p $out
          '';
        }
      );
    };
}
