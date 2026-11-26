"""D4SIG6: Tyrant Guard 667 keeps the lethal exception (wrap_firstimp); its row says what is and is not the D4 rule."""
import json
import struct
from pathlib import Path

from d5lib import evility as ev

from d4rules import overlay_path as _overlay_path
OVERLAY = _overlay_path()


def _mods():
    return json.loads(OVERLAY.read_text())["mods"]


def test_first_impression_wrapper_site():
    tag, target, sites = ev.wrapper("first_impression")
    assert (tag, target, sites) == (0xE7001D, ev.HAS_EVILITY, [0x1401FE3B3])
    assert ev.HAS_EVILITY == 0x1402068B0
    assert len(ev.TAGS) == len(ev.WRAPPERS) and len(set(ev.TAGS)) == len(ev.TAGS)


def test_site_is_the_6047_call_inside_the_predicate():
    exe = Path("/Volumes/Data/Projects/D5/D5Modkit/state/games/Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")
    if not exe.exists():
        return
    raw = exe.read_bytes()
    site = 0x1401FE3B3
    off = ev._offset(raw, site)
    assert raw[off - 8:off] == bytes.fromhex("ba9f170000498bcd")   # mov edx, 6047; mov rcx, r13
    assert raw[off] == 0xE8 and site + 5 + struct.unpack_from("<i", raw, off + 1)[0] == 0x1402068B0
    assert 0x1401FE0D0 <= site < 0x1401FE0D0 + 2655                             # inside damage_nullify_predicate


def test_tyrant_guard_row_and_label():
    m = _mods()["D4_Unique_210"]
    assert m["behaviors"]["evilities"]["8667"] == {"family": "rearm_first_damage"}
    assert m["aliases"]["8667"] == 6047
    line = next(a for a in m["adaptations"] if a.startswith("evility Tyrant Guard (667)"))
    assert "exact rule" in line and "wrap_firstimp" in line and "adapted" not in line
    assert "Not measured" in line and "Tyrant Cult (669)" in line
