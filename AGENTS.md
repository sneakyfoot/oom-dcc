This repo is for my vfx pipeline glue code.

Contains nix flake for building nixos runtimes for dccs, and container ouputs for running farm jobs on kubernetes.

There's python code for sgtk integration, and there is a custom houdini pdg scheduler for dispatching farm jobs to k8s as individual job objects.

The kubernetes cluster I use is self hosted and managed by me.

Use ruff, ty, and uv (astrals awesome python toolchain) as well as nix tools to format and check code.
