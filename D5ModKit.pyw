"""Double-click to start the D5 Mod Kit."""
import os, sys
KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
try:                                  # an update's files that were in use last time are swapped in first
    from d5lib.updater import apply_pending
    apply_pending(KIT)
except Exception:
    pass
from d5gui.app import main
main()
