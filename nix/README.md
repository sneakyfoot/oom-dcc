# Nix

- Local fhs-like environment for running DCCs on workstations
- Container output for farm jobs on k8s
- Cli tool wrappers

## Python notes
Python environment is built with nixpkgs (pure). The only non-nixpkgs input is ShotGrid tk-core,
fetched from GitHub and packaged as a Python module in `nix/python-env.nix`.

If you change the tk-core revision, update `sgtkRev` and refresh `sgtkHash` in `nix/python-env.nix`
using the hash reported by `nix build` (fetchFromGitHub will print the expected hash on failure).

## OCIO
Set `ocio.configPath` in `flake.nix` to the shared OCIO config path. The path must exist on workstations and farm nodes (the container expects the same host path, e.g. `/mnt/RAID`, to be mounted). Both the dev shell and farm container export `OCIO` from this setting.
