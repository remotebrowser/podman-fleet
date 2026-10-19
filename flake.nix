{
  description = "podman-fleet development environment";

  # nixos-unstable, the same channel ~/nix-config tracks — one nixpkgs to reason
  # about when a tool version here disagrees with the one on the global PATH.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "aarch64-darwin"
        "x86_64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      forEachSystem = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forEachSystem (pkgs: {
        default = pkgs.mkShell {
          packages = with pkgs; [
            # .python-version pins 3.11, which is also the requires-python floor.
            # Having it on PATH means uv resolves the venv against this
            # interpreter instead of downloading a build of its own.
            python311
            uv
            gnumake # every workflow is a make target — see the Makefile

            # The server drives containers by shelling out to the `podman` CLI,
            # so it is a hard runtime dependency, not just a convenience. On
            # macOS the CLI needs a Linux VM behind it; see the shellHook.
            podman
          ];

          # ruff, ty, pytest and yamlfix are deliberately absent: they are
          # dev-group dependencies in pyproject.toml and the Makefile invokes
          # them through `uv run`, so uv.lock is what pins their versions.

          shellHook = ''
            echo "podman-fleet dev shell · 'make dev' serves :8400 · 'make check' · 'make test'"
            if [ "$(uname)" = "Darwin" ] \
              && ! podman machine list --format '{{.Running}}' 2>/dev/null | grep -q true; then
              echo "  heads up: no podman machine is running, so launching a browser will fail"
              echo "  fix: podman machine start   (first time: podman machine init --cpus 6 --memory 8192)"
            fi
          '';
        };
      });
    };
}
