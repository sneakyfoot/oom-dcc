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

in
{
  inherit
    houdiniFhsEnv
    houdiniWrapper
    mplayWrapper
    nukeWrapper;
}
