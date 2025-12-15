{ pkgs, tkCorePath, uvProjectEnv, python, uv, src}:

let
  cuda = pkgs.cudaPackages_12_8;
  uvPython = "${python}/bin/python";
in rec {
  inherit uvProjectEnv uvPython tkCorePath;

  runtimePkgs = (_pkgs: with _pkgs; [
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

    python
    uv
  ]);

  runtimeProfile = ''
    export LD_LIBRARY_PATH=${pkgs.ocl-icd}/lib:$LD_LIBRARY_PATH
    export OPENCL_VENDOR_PATH=/tmp/opencl/vendors
    mkdir -p /tmp/opencl/vendors

    cp -L /run/opengl-driver/etc/OpenCL/vendors/*.icd \
      /tmp/opencl/vendors/ 2>/dev/null || true

    cp -L /etc/OpenCL/vendors/*.icd \
      /tmp/opencl/vendors/ 2>/dev/null || true

    export OOM_CORE=${src}

    export PYTHONPATH=${uvProjectEnv}/lib/python3.11/site-packages:$PYTHONPATH
    export PYTHONPATH=${tkCorePath}:$PYTHONPATH
    export SGTK_PATH=${tkCorePath}

    # uv defaults (adjustable by caller)
    export UV_PYTHON=${uvPython}
    export UV_NO_MANAGED_PYTHON=1
    export UV_NO_PYTHON_DOWNLOADS=1
    export UV_PROJECT_ENVIRONMENT=${uvProjectEnv}
    export UV_CACHE_DIR=/var/uv/cache
    # mkdir -p "$UV_PROJECT_ENVIRONMENT" "$UV_CACHE_DIR"
    uv sync --project ${src} --frozen --no-dev
  '';
  dcc-runtime = 
    pkgs.buildFHSEnv {
      name = "dcc-runtime";
      targetPkgs = runtimePkgs;
      profile = runtimeProfile;
    };
}
