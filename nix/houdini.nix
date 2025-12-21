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
, tkCorePath
, shaTag
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
    export PDG_HYTHON="$HFS/bin/hython"
    export PDG_PYTHON="$HFS/python/bin/python"
    export HOUDINI_PACKAGE_DIR=${packageDir}
    export OOM_TAG=${shaTag}
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


  ##################
  # Farm container #
  ##################

  skopeoPolicy = pkgs.writeText "containers-policy.json" ''
    {
      "default": [{ "type": "reject" }],
      "transports": {
        "docker-archive": { "": [{ "type": "insecureAcceptAnything" }] },
        "docker": { "ghcr.io/sneakyfoot/dcc-runtime": [{ "type": "insecureAcceptAnything" }] }
      }
    }
  '';

  publishHoudiniContainer =
    pkgs.writeShellScriptBin "publish-houdini-container" ''
      set -euo pipefail
  
      : "''${GITHUB_TOKEN:?GITHUB_TOKEN must be set to push to ghcr.io}"
  
      repo_root="$(git rev-parse --show-toplevel 2>/dev/null || printf '%s\n' "$PWD")"
      flake_ref="''${FLAKE_REF:-$repo_root}"
  
      image_tarball="$(nix build "''${flake_ref}#houdini-container" --impure --option sandbox false --no-link --print-out-paths)"
  
      registry_repo="ghcr.io/sneakyfoot/dcc-runtime"
      creds="''${GITHUB_ACTOR:-sneakyfoot}:''${GITHUB_TOKEN}"
  
      skopeo="${pkgs.skopeo}/bin/skopeo"
  
      # Push immutable tag from the nix-built docker archive tarball
      "$skopeo" copy --all --policy "${skopeoPolicy}" \
        "docker-archive:$image_tarball" \
        "docker://$registry_repo:${shaTag}" \
        --dest-creds "$creds"
  
      # Tag latest by copying within the registry (usually no layer re-upload)
      "$skopeo" copy --all --policy "${skopeoPolicy}" \
        "docker://$registry_repo:${shaTag}" \
        "docker://$registry_repo:latest" \
        --src-creds "$creds" \
        --dest-creds "$creds"
    '';

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

  prebuiltUvEnv = pkgs.runCommand "oom-uv-env" {
    buildInputs = [ uv python pkgs.cacert ];
    SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    NIX_SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
  } ''
    set -euo pipefail

    export UV_PYTHON=${uvPython}
    export UV_NO_MANAGED_PYTHON=1
    export UV_NO_PYTHON_DOWNLOADS=1
    export UV_PROJECT_ENVIRONMENT=$out${uvProjectEnv}
    export UV_CACHE_DIR=$out/var/uv/cache

    mkdir -p "$UV_PROJECT_ENVIRONMENT" "$UV_CACHE_DIR"
    ${uv}/bin/uv sync --project ${src} --frozen --no-dev
  '';

  houdiniContainerImage =
    pkgs.dockerTools.buildImage {
      name = "houdini-runtime";
      tag = "${shaTag}";
      copyToRoot = pkgs.buildEnv {
        name = "image-root";
        paths = [ pkgs.bash fhsLdLayer pkgs.git pkgs.openssh pkgs.cacert prebuiltUvEnv ] ++ houdiniDeps;
        pathsToLink = [ "/bin" "/usr/bin" "/usr/lib" "/usr/lib64" "/lib" "/lib64" "/etc" "/var" "/nix/store" ];
      };
      runAsRoot = ''
        mkdir -p /var/uv/venvs
        mkdir -p /var/uv/cache
        chmod -R 777 /var/uv/venvs
        chmod -R 777 /var/uv/cache
        # Ensure world-writable tmp so tk-core git descriptors can clone/resolve
        mkdir -p /tmp /var/tmp /usr/tmp
        chmod 1777 /tmp /var/tmp /usr/tmp
        '';
      # Prebuilt venv is already in the image; extraCommands no longer needed.
      extraCommands = "";
      config = {
        Env = [
          # "PATH=/bin:/usr/bin:/usr/local/bin"
          # Prefer system OpenCL (NVIDIA) over the bundled HFS libOpenCL.
          "LD_LIBRARY_PATH=/lib:/run/opengl-driver/lib:${pkgs.ocl-icd}/lib"
          "NVIDIA_OPENCL=/run/opengl-driver/etc/OpenCL/vendors"
          "INTEL_OPENCL=/etc/OpenCL/vendors"
          "OPENCL_VENDOR_PATH=/run/opengl-driver/etc/OpenCL/vendors"
          "HOUDINI_USE_HFS_OCL=0"
          "HOUDINI_OCL_DEVICETYPE=GPU"
          "HOUDINI_OCL_VENDOR="
          "OOM_CORE=${src}"
          "OOM=${src}"
          "OOM_TAG=${shaTag}"
          "SGTK_PATH=${tkCorePath}"
          "UV_PYTHON=${uvPython}"
          "UV_NO_MANAGED_PYTHON=1"
          "UV_NO_PYTHON_DOWNLOADS=1"
          "UV_PROJECT_ENVIRONMENT=${uvProjectEnv}"
          "UV_CACHE_DIR=/var/uv/cache"
          "HFS=${houdiniHostRoot}"
          "HHP=${houdiniHostRoot}/houdini/python3.11libs"
          "PDG_HYTHON=${houdiniHostRoot}/bin/hython"
          "PDG_PYTHON=${houdiniHostRoot}/python/bin/python"
          "HOUDINI_PACKAGE_DIR=${packageDir}"
          "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
          "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
          "REQUESTS_CA_BUNDLE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
          "CURL_CA_BUNDLE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
          "GIT_SSL_CAINFO=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        ];
        Entrypoint = [ "/bin/bash" ];
      };
    };

in
{
  inherit
    houdiniFhsEnv
    houdiniWrapper
    mplayWrapper
    nukeWrapper
    houdiniContainerImage
    publishHoudiniContainer;
}
