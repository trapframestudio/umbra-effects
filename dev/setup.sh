#!/usr/bin/env bash
# Create (or re-create after editing dev/distrobox.ini) the zgo-dev container.
# Everything builds and tests inside it:  dev/run.sh <command>
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
distrobox assemble create --replace --file "$here/distrobox.ini"
"$here/run.sh" true
echo "zgo-dev ready: $("$here/run.sh" x86_64-w64-mingw32-gcc --version | head -1)"
