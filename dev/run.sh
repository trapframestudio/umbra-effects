#!/usr/bin/env bash
# Run a command inside the zgo-dev container, from the mod's root folder.
#   dev/run.sh luajit tests/zgo_test_sp.lua 5
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
exec distrobox enter zgo-dev --no-workdir -- bash -lc 'cd "$0" && exec "$@"' "$root" "$@"
