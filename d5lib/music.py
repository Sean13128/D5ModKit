"""New music tracks: songs of your own under new numbers, next to the game's (not instead of one).

The game plays background music by number: it opens "<number>.ogg" in Data/Sound_BGM/Sound_BGM_0.dat (the music
loader 0x1400bf9f0 knows that one archive; the name is made with "%d.ogg" and looked up in the archive's list, which
is kept sorted -- modsys._append_patch_psfs puts new names in their place).  A new track is therefore just a new
member of that archive under a number the game doesn't use (NEW_FIRST and up), and it plays wherever a number is
given: a stage's music, an event script's bgm_play, the in-game music list.

The in-game music list is music.dat (one 1048-byte row per entry: file number, titles and descriptions in every
language, unlock, track_id, dlc_group, list_order).  A new track gets a row of its own (listed=True):
    unlock 3        always available, like the game's own BGM 01 and the "random" entries (the others are unlocked
                    as the story goes and keep their state in the save by track_id)
    track_id        after the game's (0-73; the random entries use 100)
    dlc_group 100   the base game
    list_order      after every other entry
"""
from . import database, dbpatch, sound

ARCHIVE = "Sound_BGM/Sound_BGM_0.dat"
MUSIC_DB = "Database/Database_0.dat/music.dat"
NEW_FIRST = 600                 # the game's tracks are numbered 1-548
TEMPLATE_FILE = 1               # the music.dat row copied for a new entry (BGM 01: always available)
LANGS = ("JP", "EN", "FR", "CHN", "KOR")


def track_vpath(num):
    return f"{ARCHIVE}/{int(num)}.ogg"


def mod_tracks(mod):
    """[track number] the mod adds (its own members of the music archive that the game doesn't have)"""
    import os
    d = os.path.join(mod.files_dir, *ARCHIVE.split("/"))
    out = []
    if os.path.isdir(d):
        for f in os.listdir(d):
            n = f[:-4]
            if f.lower().endswith(".ogg") and n.isdigit() and int(n) >= NEW_FIRST:
                out.append(int(n))
    return sorted(out)


def game_tracks(fs):
    return sorted(int(e.name[:-4]) for e in fs.pack(ARCHIVE).entries
                  if e.name.lower().endswith(".ogg") and e.name[:-4].isdigit())


def free_number(fs, mods):
    """the first number from NEW_FIRST on that neither the game nor any mod uses"""
    used = set(game_tracks(fs))
    for m in mods:
        used.update(mod_tracks(m))
    n = NEW_FIRST
    while n in used:
        n += 1
    return n


def _tables(fs, mod):
    van = database.load_table("music.dat", fs.read(MUSIC_DB))
    ed = database.load_table("music.dat", fs.read(MUSIC_DB))
    p = mod.load_patch("db", "music.dat.json")
    if p:
        dbpatch.apply_patch(ed, p)
    return van, ed


def add_track(fs, mod, mods, loop, intro=b"", title="", name="", listed=True):
    """a new track in `mod` -> its number.  loop / intro: Ogg Vorbis (sound.build_track); title: the music list's
    label (default "MOD <n>"), name: the song name shown under it"""
    num = free_number(fs, mods)
    mod.write_file(track_vpath(num), sound.build_track(loop, intro))
    if listed:
        set_listing(fs, mod, num, title or f"MOD {num}", name or f"Track {num}")
    return num


def set_listing(fs, mod, num, title, name):
    """the track's row in the in-game music list (added, or renamed when it has one)"""
    van, ed = _tables(fs, mod)
    row = next((r for r in ed.rows if int(r["file"]) == int(num)), None)
    if row is None:
        tmpl = next((r for r in van.rows if int(r["file"]) == TEMPLATE_FILE), van.rows[0])
        row = tmpl.copy()
        game_ids = [int(r["track_id"]) for r in van.rows if int(r["track_id"]) < 100]
        mine = [int(r["track_id"]) for r in ed.rows[len(van.rows):]]
        row.set("file", int(num))
        row.set("unlock", 3)
        row.set("track_id", max(game_ids + mine) + 1)
        row.set("dlc_group", 100)
        row.set("list_order", max(int(r["list_order"]) for r in ed.rows) + 1)
        ed.rows.append(row)
    for lang in LANGS:
        row.set(f"title_{lang}", title, truncate=True)
        row.set(f"desc_{lang}", name, truncate=True)
    _save(mod, van, ed)


def _save(mod, van, ed):
    p = dbpatch.diff_table(van, ed)
    mod.save_patch("db", "music.dat.json", None if dbpatch.is_empty(p) else p)


def remove_track(fs, mod, num):
    """the mod's track and its music list row"""
    mod.remove_file(track_vpath(num))
    van, ed = _tables(fs, mod)
    n = len(van.rows)
    added = [r for r in ed.rows[n:] if int(r["file"]) != int(num)]
    if len(added) != len(ed.rows) - n:
        ed.rows[n:] = added
        _save(mod, van, ed)


def listing(fs, mod, num):
    """(title, name) of a track in the mod's music list, or None"""
    _, ed = _tables(fs, mod)
    r = next((r for r in ed.rows if int(r["file"]) == int(num)), None)
    return (r["title_EN"], r["desc_EN"]) if r is not None else None
