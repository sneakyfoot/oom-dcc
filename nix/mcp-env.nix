{ pkgs, src }:

let
  python = pkgs.python313;

  rpyc410 = python.pkgs.buildPythonPackage rec {
    pname = "rpyc";
    version = "4.1.0";
    format = "setuptools";
    src = pkgs.fetchPypi {
      inherit pname version;
      sha256 = "sha256-BecEwFApMlcZYIEvXPqsOuaRSe3Nls5GRJYcFwQE6d8=";
    };
    propagatedBuildInputs = [ python.pkgs.plumbum ];
    doCheck = false;
  };

  mcpEnv = python.withPackages (ps: [ ps.fastmcp rpyc410 ]);

  mcpSitePkgs = "${mcpEnv}/${python.sitePackages}";

  mcpPythonPath = pkgs.lib.concatStringsSep ":" [
    "${src}/mcp-server"
    mcpSitePkgs
  ];
in
{
  inherit
    python
    mcpEnv
    mcpPythonPath
    ;
}
