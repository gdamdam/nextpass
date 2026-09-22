#!/bin/sh
set -eu
PASS_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -x "$PASS_DIR/.venv/bin/python" ]; then
    echo "First run: creating a local Python environment and installing Skyfield..." >&2
    python3 -m venv "$PASS_DIR/.venv"
fi
# Check the pinned distribution version as well as importability. A pre-existing
# environment with an older Skyfield can otherwise silently bypass requirements.txt.
if ! "$PASS_DIR/.venv/bin/python" - "$PASS_DIR/requirements.txt" <<'PY' >/dev/null 2>&1
from importlib.metadata import version
from pathlib import Path
import sys

requirements = Path(sys.argv[1]).read_text().splitlines()
expected = next((line.split('==', 1)[1].strip() for line in requirements
                 if line.startswith('skyfield==')), None)
if expected is None:
    raise SystemExit('requirements.txt must pin skyfield with ==')
import skyfield
raise SystemExit(version('skyfield') != expected)
PY
then
    "$PASS_DIR/.venv/bin/python" -m pip install -r "$PASS_DIR/requirements.txt" >&2
fi
exec "$PASS_DIR/.venv/bin/python" "$PASS_DIR/meteor_passes.py" "$@"
