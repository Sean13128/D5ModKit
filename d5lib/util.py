import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
from .paths import game_dir as _game_dir

GAME = _game_dir() or os.path.abspath(os.path.join(KIT, ".."))
DATA = os.path.join(GAME, "Data")
EXTRACTED = os.path.join(KIT, "_extracted")


def hexdump(b: bytes, base: int = 0, width: int = 16) -> str:
    lines = []
    for j in range(0, len(b), width):
        c = b[j:j + width]
        lines.append("%08x %-*s %s" % (base + j, width * 3, c.hex(" "),
                                       "".join(chr(x) if 32 <= x < 127 else "." for x in c)))
    return "\n".join(lines)
