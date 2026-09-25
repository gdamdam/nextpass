"""Source-checkout compatibility wrapper; installed code lives in nextpass."""
import sys
from nextpass import meteor_passes as _implementation
if __name__ == "__main__":
    if hasattr(_implementation, "main"):
        sys.exit(_implementation.main())
    raise SystemExit("Run the nextpass command instead")
sys.modules[__name__] = _implementation
