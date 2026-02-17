# Nix

- Local fhs-like environment for running DCCs on workstations
- Container output for farm jobs on k8s
- Cli tool wrappers

## Python notes
Builds are impure / unsandboxed as I'm using uv to manage my python environment. Uv venv gets built into a derivation, this step must be run with `--option sandbox relaxed`. 

## OCIO
Set `ocio.configPath` in `flake.nix` to the shared OCIO config path. The path must exist on workstations and farm nodes (the container expects the same host path, e.g. `/mnt/RAID`, to be mounted). Both the dev shell and farm container export `OCIO` from this setting.
