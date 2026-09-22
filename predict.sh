#!/bin/sh
set -eu
PASS_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -x "$PASS_DIR/.venv/bin/python" ]; then
    echo "First run: creating a local Python environment and installing Skyfield..." >&2
    python3 -m venv "$PASS_DIR/.venv"
fi
# Check the pinned distribution version as well as importability. A pre-existing
# environment with an older Skyfield can otherwise silently bypass requirements.txt.
if ! "$PASS_DIR/.venv/bin/python" -c 'import skyfield; from importlib.metadata import version; import sys; sys.exit(version("skyfield") != "1.55")' >/dev/null 2>&1; then
    "$PASS_DIR/.venv/bin/python" -m pip install -r "$PASS_DIR/requirements.txt" >&2
fi
exec "$PASS_DIR/.venv/bin/python" "$PASS_DIR/meteor_passes.py" "$@"
