"""Compatibility entry point; use nextpass --service instead."""
import sys
from nextpass import service_installer as _implementation
if __name__ == "__main__":
    sys.exit(_implementation.main(sys.argv[1:]))
sys.modules[__name__] = _implementation
