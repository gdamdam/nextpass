#!/bin/sh
set -eu
PASS_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -x "$PASS_DIR/.venv/bin/python" ]; then
    echo "First run: creating a local Python environment and installing Skyfield..." >&2
    python3 -m venv "$PASS_DIR/.venv"
fi
# Confirm the installed Skyfield satisfies the supported 1.x range.
if ! "$PASS_DIR/.venv/bin/python" <<'PY' >/dev/null 2>&1
from importlib.metadata import version
import skyfield
parts = version('skyfield').split('.')
raise SystemExit(not (len(parts) >= 2 and parts[0] == '1' and int(parts[1]) >= 55))
PY
then
    "$PASS_DIR/.venv/bin/python" -m pip install -r "$PASS_DIR/requirements.txt" >&2
fi
cd "$PASS_DIR"
exec "$PASS_DIR/.venv/bin/python" -m nextpass "$@"
