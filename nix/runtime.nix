{
  pkgs,
  uvBundle,
  src,
}:

let
  cuda = pkgs.cudaPackages_12_8;
  uvPython = "${uvBundle}/python/bin/python";
  defaultUvProjectEnv = "${uvBundle}/venv";
  uvSitePkgs = "${defaultUvProjectEnv}/lib/python3.11/site-packages";
in
rec {
  inherit uvPython;

  runtimePkgs = (
    _pkgs: with _pkgs; [
      stdenv.cc.cc.lib
      glibc
      zlib
      libGLU
      libGL
      krb5
      alsa-lib
      fontconfig
      fontconfig.lib
      zlib
      libpng
      dbus
      dbus.lib
      nss
      nspr
      expat
      pciutils
      libxkbcommon
      libudev0-shim
      tbb
      xwayland
      qt5.qtwayland
      nettools
      bintools
      glib

      cuda.libcublas
      cuda.cudnn
      cuda.libcufft
      cuda.libcurand
      cuda.cuda_nvrtc
      cuda.cuda_opencl

      ocl-icd
      opencl-headers
      clinfo
      intel-ocl
      numactl
      zstd
      # libdrm's default output is "bin"; add "out" so libdrm.so.* land in /lib
      libdrm.out
      libdrm.bin
      libxshmfence
      libxkbfile

      xorg.libICE
      xorg.libSM
      xorg.libXmu
      xorg.libXi
      xorg.libXt
      xorg.libXext
      xorg.libX11
      xorg.libXrender
      xorg.libXcursor
      xorg.libXfixes
      xorg.libXcomposite
      xorg.libXdamage
      xorg.libXtst
      xorg.libxcb
      xorg.libXScrnSaver
      xorg.libXrandr
      xorg.xcbutil
      xorg.xcbutilimage
      xorg.xcbutilrenderutil
      xorg.xcbutilcursor
      xorg.xcbutilkeysyms
      xorg.xcbutilwm

      coreutils
      bashInteractive
      findutils
      gawk
      gnused
      gnugrep
      which
      procps
      uvBundle
    ]
  );

  runtimeProfile = ''
    export LD_LIBRARY_PATH=${pkgs.ocl-icd}/lib:$LD_LIBRARY_PATH
    export OPENCL_VENDOR_PATH=/run/opengl-driver/etc/OpenCL/vendors
    # mkdir -p /tmp/opencl/vendors

    # cp -L /run/opengl-driver/etc/OpenCL/vendors/*.icd \
    #   /tmp/opencl/vendors/ 2>/dev/null || true

    # cp -L /etc/OpenCL/vendors/*.icd \
    #   /tmp/opencl/vendors/ 2>/dev/null || true

    export OOM_CORE=${src}

    if [ -z "''${UV_PROJECT_ENVIRONMENT:-}" ]; then
      UV_PROJECT_ENVIRONMENT="${defaultUvProjectEnv}"
    fi
    if [ -z "''${UV_CACHE_DIR:-}" ]; then
      UV_CACHE_DIR="$HOME/.cache/uv/cache"
    fi

    export UV_PYTHON=${uvPython}
    export UV_PROJECT_ENVIRONMENT
    export UV_CACHE_DIR

    export PYTHONPATH="''${UV_PROJECT_ENVIRONMENT}/lib/python3.11/site-packages:$PYTHONPATH"
    export SGTK_PATH=${uvSitePkgs}

  '';
  dcc-runtime = pkgs.buildFHSEnv {
    name = "dcc-runtime";
    targetPkgs = runtimePkgs;
    profile = runtimeProfile;
  };
}
