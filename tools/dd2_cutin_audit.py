#!/usr/bin/env python3
"""DD2 source-versus-built cut-in audit: report and gate (DD2CUTIN1).  The logic is d5lib/dd2cutinaudit.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib.dd2cutinaudit import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
