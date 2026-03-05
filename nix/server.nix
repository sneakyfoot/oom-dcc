{
  pkgs,
  pythonEnv,
  pythonPath,
  src,
}:

let
  serverEnv = pkgs.python311.withPackages (
    ps: with ps; [
      jinja2
      kubernetes
      pyyaml
      rich
      uv-build
      fastapi
      uvicorn
      pydantic
      pydantic-settings
      pillow
      jsonschema
    ]
  );

  agentServer = pkgs.writeShellApplication {
    name = "agent-server";
    text = ''
      export OOM=${src}
      export PYTHONPATH=${pythonPath}
      export HOST="0.0.0.0"
      export PORT="8080"

      exec ${serverEnv}/bin/uvicorn oom_agent.server:app \
        --host "$HOST" \
        --port "$PORT" \
        --log-level debug
    '';
  };

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
  inherit agentServer mcpServer serverEnv;
}
