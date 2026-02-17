{ pkgs
, python
, pythonEnv
, runtimePkgs
, runtimeProfile
, houdiniHostRoot ? "/mnt/RAID/Assets/DCCs/houdini/latest"
, nukeHostRoot ? "/mnt/RAID/Assets/DCCs/nuke/latest"
, src
, shaTag
}:

let
  pythonSitePkgs = "${pythonEnv}/${python.sitePackages}";

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
    export PDG_HYTHON="$HFS/bin/hython"
    export PDG_PYTHON="$HFS/python/bin/python"
    export HOUDINI_PACKAGE_DIR=${packageDir}
    export OOM_TAG=${shaTag}
    export PYTHONPATH="${pythonSitePkgs}:${src}/src:$PYTHONPATH"
  '';

  houdiniHostProfile = mkHoudiniProfile {
    hfsRoot    = houdiniHostRoot;
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
