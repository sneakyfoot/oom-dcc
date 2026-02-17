# OOM DCC pipeline

## Nix usage

- `nix develop` drops you into a dev shell with Python 3.11, project deps, `ruff`, and `ty`.
- `nix build` builds the Python package (default output). The `oom` CLI is at `./result/bin/oom`.
- `nix flake check` runs `ruff check`, `ruff format --check`, and `ty check` in a pure environment.

## Houdini integration

Houdini itself is not provided by Nix. The Houdini modules are expected to run inside a Houdini runtime.
The dev shell only provides stubs (see `stubs/`) for type checking. If you want wrappers for a
host Houdini install, build the `houdini`/`mplay`/`nuke` outputs and ensure the host paths in
`nix/houdini.nix` match your environment.
