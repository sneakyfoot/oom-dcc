# Nix

- Local fhs-like environment for running DCCs on workstations
- Container output for farm jobs on k8s
- Cli tool wrappers

## Python notes
Builds are impure / unsandboxed as I'm using uv to manage my python environment. Uv venv gets built into a derivation, this step must be run with `--option sandbox relaxed`. 
