nix build ../#houdini-container --impure --option sandbox false
podman load -i ./result
podman tag localhost/houdini-runtime:testing ghcr.io/sneakyfoot/dcc-runtime:testing
podman push ghcr.io/sneakyfoot/dcc-runtime:testing
