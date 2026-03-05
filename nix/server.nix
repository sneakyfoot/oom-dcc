{
  pkgs,
  mcpEnv,
  mcpPythonPath,
  src,
}:

let
  mcpServer = pkgs.writeShellApplication {
    name = "mcp-server";
    text = ''
      export OOM=${src}
      export PYTHONPATH=${mcpPythonPath}
      exec ${mcpEnv}/bin/python -m oom_agent.mcp_server
    '';
  };

in
{
  inherit mcpServer;
}
