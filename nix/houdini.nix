{ pkgs
, runtimePkgs
, runtimeProfile
, houdiniHostRoot ? "/mnt/RAID/Assets/DCCs/houdini/latest"
, nukeHostRoot ? "/mnt/RAID/Assets/DCCs/nuke/latest"
, houdiniContainerRoot ? "/opt/houdini"
, uvProjectEnv
, python
, uv
, src
}:

let
  uvPython = "${python}/bin/python";

  houdiniDeps = runtimePkgs pkgs;

  packageDir = "${src}/dcc/oom-houdini/packages";

  mkHoudiniProfile = { hfsRoot }: ''
    ${runtimeProfile}
    export HFS=${hfsRoot}
    export PATH="$HFS/bin:$PATH"
    export OOM=${src}
    export HOUDINI_PATH="$HFS/houdini:&"
    export HOUDINI_USE_HFS_OCL=0
    export HHP="$HFS/houdini/python3.11libs"
    export HOUDINI_PACKAGE_DIR=${packageDir}
  '';

  houdiniHostProfile = mkHoudiniProfile {
    hfsRoot    = houdiniHostRoot;
  };

  houdiniContainerProfile = mkHoudiniProfile {
    hfsRoot    = houdiniContainerRoot;
  };

  # Simple launcher: run the provided command as-is, otherwise drop into bash.
  fhsLauncher = pkgs.writeShellScript "houdini-fhs-launch" ''
    if [ "$#" -gt 0 ]; then
      exec "$@"
    else
      exec ${pkgs.bashInteractive}/bin/bash
    fi
  '';

  houdiniFhsEnv =
    pkgs.buildFHSEnv {
      name = "houdini-fhs";
      targetPkgs = runtimePkgs;
      profile = houdiniHostProfile;
      runScript = fhsLauncher;
    };

  houdiniWrapper =
    pkgs.writeShellScriptBin "houdini" ''
      exec ${houdiniFhsEnv}/bin/houdini-fhs ${houdiniHostRoot}/bin/houdini "$@"
    '';

  mplayWrapper =
    pkgs.writeShellScriptBin "mplay" ''
      exec ${houdiniFhsEnv}/bin/houdini-fhs ${houdiniHostRoot}/bin/mplay "$@"
    '';

  nukeWrapper =
    pkgs.writeShellScriptBin "nuke" ''
      exec ${houdiniFhsEnv}/bin/houdini-fhs ${nukeHostRoot}/Nuke16.0 "$@"
    '';


  # Farm container

    ldSoConf = ''
      include /etc/ld.so.conf.d/*.conf
    '';
    baseLdConf = ''
      /lib
      /lib64
      /usr/lib
      /usr/lib64
    '';

  mkFhsLdLayer =
    { glibc ? pkgs.glibc }:
    pkgs.runCommand "fhs-ld-layer" { inherit glibc ldSoConf baseLdConf; } ''
      mkdir -p $out/etc/ld.so.conf.d
      printf '%s\n' "${ldSoConf}" > $out/etc/ld.so.conf
      printf '%s\n' "${baseLdConf}" > $out/etc/ld.so.conf.d/00-base.conf
      : > $out/etc/ld.so.cache

      glibcEtc="${glibc}/etc"
      mkdir -p $out''${glibcEtc}
      ln -sf /etc/ld.so.cache $out''${glibcEtc}/ld.so.cache
      ln -sf /etc/ld.so.conf $out''${glibcEtc}/ld.so.conf
      ln -sf /etc/ld.so.conf.d $out''${glibcEtc}/ld.so.conf.d

      # Provide the dynamic linker at the legacy FHS locations so
      # /lib64/ld-linux-x86-64.so.2 can be found by kernels inside the
      # container when launching host Houdini binaries.
      mkdir -p $out/lib $out/lib64
      ln -sf ${glibc}/lib/ld-linux-x86-64.so.2 $out/lib/ld-linux-x86-64.so.2
      ln -sf ${glibc}/lib/ld-linux-x86-64.so.2 $out/lib64/ld-linux-x86-64.so.2
    '';

  fhsLdLayer = mkFhsLdLayer { };
  houdiniContainerImage =
    pkgs.dockerTools.buildImage {
      name = "houdini-runtime";
      copyToRoot = pkgs.buildEnv {
        name = "image-root";
        paths = [ pkgs.bash fhsLdLayer ] ++ houdiniDeps;
        pathsToLink = [ "/bin" "/usr/bin" "/usr/lib" "/usr/lib64" "/lib" "/lib64" "/etc" "/nix/store" ];
      };
      config = {
        # Ensure basic utilities like dirname are reachable even when PATH
        # is not populated by the caller environment.
        Env = [ "PATH=/bin:/usr/bin:/usr/local/bin" ];
      };
    };


in
{
  inherit
    houdiniFhsEnv
    houdiniWrapper
    mplayWrapper
    nukeWrapper
    houdiniContainerImage;
}
