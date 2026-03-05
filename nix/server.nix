{
  pkgs,
  pythonEnv,
  pythonPath,
  src,
}:

let
  mcpServer = pkgs.writeShellApplication {
    name = "mcp-server";
    text = ''
      export OOM=${src}
      export PYTHONPATH=${pythonPath}

      exec ${pythonEnv}/bin/python -m oom_agent.mcp_server
    '';
  };

in
{
  inherit mcpServer;
}
