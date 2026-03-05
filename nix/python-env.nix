{
  pkgs,
  src,
  sgtkRev ? "62d128a8a3e06fe37cc9de5c6a699415c6b51c70",
  sgtkHash ? "sha256-gMA264hx7AOyjGUzkSlX2O7zFq5H6LAeGh68vMyUl2k=",
}:

let
  python = pkgs.python311;

  sgtkSrc = pkgs.fetchFromGitHub {
    owner = "shotgunsoftware";
    repo = "tk-core";
    rev = sgtkRev;
    hash = sgtkHash;
  };

  sgtkPkg = python.pkgs.buildPythonPackage {
    pname = "sgtk";
    version = sgtkRev;
    src = sgtkSrc;
    format = "other";
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/${python.sitePackages}"
      cp -R "$src/python/"* "$out/${python.sitePackages}/"
      runHook postInstall
    '';
  };

  pythonEnv = python.withPackages (ps: [
    ps.jinja2
    ps.kubernetes
    ps.pyyaml
    ps.rich
    ps.uv-build
    sgtkPkg
    # Agent server dependencies
    ps.fastapi
    ps.uvicorn
    ps.pydantic
    ps.pydantic-settings
    ps.pillow
    ps.jsonschema
    # MCP dependencies
    ps.fastmcp
  ]);

  pythonSitePkgs = "${pythonEnv}/${python.sitePackages}";

  pythonPath = pkgs.lib.concatStringsSep ":" [
    "${src}/src"
    pythonSitePkgs
  ];

  toolchain = [
    pkgs.git
    pkgs.ruff
    pkgs.ty
    pkgs.cacert
    pkgs.makeWrapper
    pkgs.zlib
    pkgs.openssl
    pkgs.stdenv.cc
    pythonEnv
  ];
in
{
  inherit
    python
    pythonEnv
    pythonPath
    pythonSitePkgs
    sgtkSrc
    sgtkPkg
    toolchain
    ;
}
