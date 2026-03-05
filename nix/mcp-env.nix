{ pkgs, src }:

let
  python = pkgs.python313;

  mcpEnv = python.withPackages (ps: [ ps.fastmcp ]);

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
