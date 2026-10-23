"""New tracks in the in-game music list (the Jukebox / BGM selection), whatever the save.

The list (built by 0x1407e7a00) shows a music.dat row when the save's unlock byte for its track_id (state + 0x878BDC
+ track_id, track_id < 152) has bit 1.  The row's own 'unlock' field (+0x0C) is copied into those bytes only when a
NEW game starts (0x1401b7f60), and playing a track sets its bit (0x1407c865e, 0x1401b82a2).  So a track a mod adds
with unlock 3 ("always available") stayed out of the list of every save made before it, until something played it.

The install patches the list's test (code section ".d5ml") when an enabled mod adds a music.dat row: a row whose
unlock field has bit 1 counts as unlocked too.  The game's own rows with unlock 3 are unlocked in every save already,
so nothing else changes.
"""
from .exepatch import add_hook_section
from .gamefs import EXE_FILE
from .modsys import Mod, register_finalizer

SECTION = b".d5ml"
# movzx eax, byte ptr [rax + rdx + 0x878bdc] / and al, 1   (rsi = the row + 0x40c; je follows)
SITE = 0x1407E7B14
ORIG = bytes.fromhex("0fb68410dc8b87002401")
RET = 0x1407E7B1E


def _src():
    return "\n".join([
        "    movzx eax, byte ptr [rax + rdx + 0x878bdc]",
        "    or al, byte ptr [rsi - 0x400]",
        "    and al, 1",
        f"    jmp {RET:#x}",
    ])


def build(exe):
    return add_hook_section(exe, SECTION, [(SITE, ORIG, _src(), 0xE9)])


def adds_rows(mod):
    """does the mod add rows to the music list?"""
    p = mod.load_patch("db", "music.dat.json") or {}
    return bool(p.get("added"))


def _finalize(ctx):
    mods = [Mod(f) for f in getattr(ctx, "mod_folders", []) or []]
    users = [m for m in mods if adds_rows(m)]
    if not users:
        return
    ctx.put(EXE_FILE, build(ctx.get(EXE_FILE)))
    ctx.log(f"  music list: new tracks listed in every save ({', '.join(m.name for m in users)})")


register_finalizer(_finalize)
