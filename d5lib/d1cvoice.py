"""Disgaea 1 voices -> D5 custom voices (lane VOICE1, 2026-11-10).

Who says which clip, and in which of the game's four per-character lists, is `importers/d1c-voice-map.json` (read
from the Disgaea 1 Complete executable by VOICEMAP1: names, list numbers and hashes, no audio).  The clip audio
is read from the Disgaea PC `DATA.DAT` voice banks (PSPFS_V1 -> VOICE01/02[_EN].PBD, DSARC FL -> Ogg Vorbis): the
clip names are the same in the PC, Switch and PS4 editions and PC is the edition ffmpeg can decode.

List 0 is the attack shout, lists 1 and 2 are skill shouts (see the map's `slot_evidence`); a clip follows the cue
route of `importers/drpg-voice-routes.json`.  Both dubs exist, so every line carries an English and a Japanese file.

VOICE2: the map covers every D1C pack with what Disgaea 1 does for that character id.  A monster's four lists hold
one shared sound effect (sound bank 1, `SUBDATA.DAT` -> START.DAT member 66): that effect is its voice.  A character
without a selector entry says nothing: the pack is linked to a voice without lines (`drpgvoice.link_silent`).
Disgaea 1 has no damage or death line for anybody (the map's `no_damage_death`), so none is built.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path

from . import drpgvoice

HERE = Path(__file__).resolve().parent
MAP_FILE = HERE / "importers/d1c-voice-map.json"
BANKS = {"JP": ("VOICE01.PBD", "VOICE02.PBD"), "EN": ("VOICE01_EN.PBD", "VOICE02_EN.PBD")}
SE_MEMBER = 66
_cache = {}

# D1CLIST3: list 3 is what Disgaea 1 plays when a unit CASTS a heal or support spell (script events 2000015 for Heal, Mega /
# Giga / Omega Heal, Espoir, Braveheart, Shield, Magic Boost, Magic Wall; 4009997 for the short-animation Heal, Espoir,
# Braveheart).  D5's own twins say the same on the caster: Heal / Mega Heal / Giga Heal play voice category 9, Espoir,
# Braveheart, Shield, Magic Boost, Magic Wall category 8 (`voice_play_actor 90000/80000`, actor 0 = the caster;
# Omega Heal has none).  A clip that only list 3 reaches, and nothing else routes, goes to exactly those two categories.
CAST_ROLE = "d1_heal_cast"
CAST_ROUTE = {CAST_ROLE: {"0": {"cats": [8, 9]}}}
CAST_LABEL = ("list 3 = Disgaea 1's heal/support spell cast line (script events 2000015 / 4009997), carried by D5 "
              "situations 9 (heal) and 8 (support) of the caster; this character learns no such spell natively")


def voice_map():
    if "map" not in _cache:
        _cache["map"] = json.loads(MAP_FILE.read_text())
    return _cache["map"]


def leases():
    """{mod folder: custom voice id}"""
    return {f: int(m["voice_id"]) for f, m in voice_map()["mods"].items()}


def voice_label(entry, where="d1c-voice-map"):
    """The pack name the voice record carries, resolved from the map's ``@text`` reference.

    TEXTHASH-D1C-DD2: the map stores the Disgaea 1 name as a SHA-256 reference and the product
    suffix (" (D1C)") as ``name_suffix``; the string comes from the prepared D1C source."""
    from . import textrefs
    name = entry["name"]
    if textrefs.has_refs(name):
        from .importers import _d1c_source
        name = textrefs.resolve(name, _d1c_source.text_pool().get, where)
    return name + (entry.get("name_suffix") or "")


def pc_clips(source):
    """{(dub, clip stem): ogg bytes} of the four voice banks in Disgaea PC's DATA.DAT."""
    if hasattr(source, "files"):               # SOURCEPREP4-D1C: the two verified archives, opened by exact path
        path, sub = source.files()
        key = ("clips", str(path), str(sub))
    else:                                      # a folder named by the caller (not a prepared source): searched
        sub, key = None, ("clips", str(source))
    if key in _cache:
        return _cache[key]
    if sub is None:
        path = next((p for p in sorted(Path(source).rglob("DATA.DAT")) if p.open("rb").read(8) == b"PSPFS_V1"), None)
        if path is None:
            raise FileNotFoundError(f"no Disgaea PC DATA.DAT (PSPFS_V1) under {source}")
        sub = path.with_name("SUBDATA.DAT")
    out = {}
    with path.open("rb") as f:
        n, = struct.unpack_from("<I", f.read(16), 8)
        table = f.read(n * 52)
        members = {}
        for i in range(n):
            row = table[i * 52:(i + 1) * 52]
            members[row[:44].split(b"\0", 1)[0].decode("ascii", "replace").upper()] = struct.unpack_from("<II", row, 44)
        for dub, names in BANKS.items():
            for name in names:
                size, offset = members[name]
                f.seek(offset)
                raw = f.read(size)
                if raw[:8] != b"DSARC FL":
                    raise ValueError(f"{name} is not a DSARC FL bank")
                count, = struct.unpack_from("<I", raw, 8)
                for k in range(count):
                    e = raw[16 + k * 48:64 + k * 48]
                    csize, coff = struct.unpack_from("<II", e, 40)
                    if not 16 + count * 48 <= coff < coff + csize <= len(raw):
                        raise ValueError(f"{name}: clip {k} outside the bank")
                    stem = e[:40].split(b"\0", 1)[0].decode("ascii", "replace").split(".")[0].lower()
                    out[(dub, stem)] = raw[coff:coff + csize]
    if sub.is_file():                                      # sound-effect bank 1 (the monsters' shared effects)
        from . import d1skill
        raw, _prov = d1skill.disgaea_pc_magic(sub, SE_MEMBER)
        if raw[:8] != b"DSARC FL":
            raise ValueError("START.DAT member %d is not the sound-effect bank" % SE_MEMBER)
        for k in range(struct.unpack_from("<I", raw, 8)[0]):
            e = raw[16 + k * 48:64 + k * 48]
            csize, coff = struct.unpack_from("<II", e, 40)
            out[("SE", e[:40].split(b"\0", 1)[0].decode("ascii", "replace").split(".")[0].lower())] = raw[coff:coff + csize]
    _cache[key] = out
    return out


def decode_ogg(ogg):
    import numpy as np
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("Disgaea PC voices are Ogg Vorbis: install ffmpeg (and add it to PATH) to convert them.")
    r = subprocess.run([exe, "-v", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", "48000", "pipe:1"],
                       input=ogg, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode or not r.stdout:
        raise ValueError("Ogg decode failed: " + r.stderr.decode("utf8", "replace")[:200])
    return np.frombuffer(r.stdout, dtype="<f4")


def clip_roles(clip):
    """([cue roles], why) of one mapped clip: the role of every routed list it is in (the game plays it wherever a
    script asks for one of those lists), else its Disgaea RPG cue; ([], why) when neither."""
    slot_routes = voice_map()["slot_routes"]
    slots = [s for s in sorted(clip["slots"]) if str(s) in slot_routes]
    if slots:
        return sorted({slot_routes[str(s)] for s in slots}), "list " + ", ".join(map(str, slots))
    if clip.get("drpg_cue") and drpgvoice.cue_role(clip["drpg_cue"]):
        return [drpgvoice.cue_role(clip["drpg_cue"])], f"same recording as Disgaea RPG {clip['drpg_cue']}"
    if clip["slots"] == [3]:
        return [CAST_ROLE], CAST_LABEL
    return [], "in no list"


def import_voice(mod_dir, source, voice_id, class_):
    """Write the pack's Disgaea 1 voice into the mod as custom voice `voice_id`.  -> receipt dict."""
    from . import modsys, voices
    entry = voice_map()["mods"][Path(mod_dir).name]
    bank, table = pc_clips(source), {**drpgvoice.routes(), **CAST_ROUTE}
    mod = modsys.Mod(str(mod_dir))
    folder = Path(voices.folder(mod))
    lines, clips, unrouted, writes = [], [], [], {}
    for stem, clip in entry["clips"].items():
        roles, why = clip_roles(clip)
        if not roles:
            unrouted.append(dict(clip=stem, reason=why))
            continue
        files = {}
        for dub in ("SE",) if clip.get("bank") == "se" else ("EN", "JP"):
            raw = bank.get((dub, stem))
            if raw is None:
                if dub == "SE":
                    raise FileNotFoundError(f"sound effect {stem} not found (SUBDATA.DAT beside the Disgaea PC DATA.DAT)")
                continue
            if clip["sha256"].get(dub) != hashlib.sha256(raw).hexdigest():
                raise ValueError(f"{stem} ({dub}) is not the clip the voice map was read from")
            pcm = decode_ogg(raw)
            seconds = len(pcm) / 48000
            if not drpgvoice.MIN_SECONDS <= seconds <= drpgvoice.MAX_SECONDS or float(abs(pcm).max()) < 0.01:
                unrouted.append(dict(clip=stem, dub=dub, reason=f"not an audible clip ({seconds:.2f} s)"))
                continue
            vag, peak, samples = drpgvoice._encode(pcm)
            fn = f"d1_{voice_id}_{stem}_{dub}.vag"
            writes[fn] = vag
            files[dub] = fn
            clips.append(dict(clip=stem, dub=dub, roles=roles, why=why, lists=clip["slots"], file=fn,
                              ogg_sha256=clip["sha256"][dub], seconds=round(samples / 48000, 3), peak=round(peak, 4)))
        if "SE" in files:                             # a sound effect has no dub: the one file serves both settings
            files = {"EN": files["SE"], "JP": files["SE"]}
        if not files:
            continue
        dests = {}                                    # one line per D5 kind, with the situations of all its roles
        for role in roles:
            for kind, dest in table[role].items():
                dests.setdefault(int(kind), set()).update(dest["cats"])
        volume = voices.DEFAULT_VOLUME
        if clip.get("bank") == "se":                  # a sound effect: battle only, at the source's own gain ratio
            dests = {0: dests[0]}
            volume = round(volume * clip.get("gain", 168) / 168)
        for kind, cats in sorted(dests.items()):
            line = dict(kind=kind, cats=sorted(cats), volume=volume, files=files,
                        missing_locale="silence", clip=stem, roles=roles)
            if not class_:
                line["personality"] = 0               # a class says the same lines in all three personalities
            lines.append(line)
    if not lines:
        raise ValueError("no routed audible clip")
    folder.mkdir(parents=True, exist_ok=True)
    for fn, raw in writes.items():
        (folder / fn).write_bytes(raw)
    data = voices.load(mod)
    data["voices"][str(int(voice_id))] = dict(
        name=voice_label(entry, f"d1c-voice-map.mods.{Path(mod_dir).name}").replace(" (D1C)", "")
             + (" (Disgaea 1 monster sound effect)" if entry.get("sound_effect")
                                                      else " (Disgaea 1, English + Japanese)"), lines=lines,
        source=dict(game="Disgaea PC DATA.DAT voice banks; lists from Disgaea 1 Complete", source_id=entry["source_id"],
                    clip_prefix=entry["clip_prefix"], native_alias=entry["native_alias"], languages=["EN", "JP"],
                    map="importers/d1c-voice-map.json -> importers/drpg-voice-routes.json",
                    silent_situations="damage, death: Disgaea 1 has no such line for any character"))
    voices.save(mod, data)
    return dict(source_id=entry["source_id"], voice_id=int(voice_id), clips=clips, lines=len(lines),
                unrouted=unrouted, native_alias=entry["native_alias"], native_tested=False)


def apply(mod_dir, source):
    """Give a D1C pack its own source voice (every added char row).  -> receipt, also written beside voices.json."""
    mod_dir = Path(mod_dir)
    done, kept, silent = [], [], []
    try:
        if mod_dir.name in voice_map().get("silent", {}):
            why = voice_map()["silent"][mod_dir.name]["reason"]
            silent.append(dict(rows=sorted(drpgvoice.link_silent(mod_dir, "Disgaea 1: " + why)), reason=why))
            return dict(schema="d1c-voice-receipt/1", mod=mod_dir.name, voices=[], donor_kept=[], silent=silent)
        if mod_dir.name not in voice_map()["mods"]:
            raise KeyError((voice_map().get("unchanged", {}).get(mod_dir.name) or {}).get("reason")
                           or "this pack is not in importers/d1c-voice-map.json")
        vid = leases()[mod_dir.name]
        rows = [int(r["id"]) for r in json.loads((mod_dir / "patches/db/char.dat.json")
                                                 .read_text(encoding="utf-8-sig")).get("added", [])]
        done.append(dict(import_voice(mod_dir, source, vid, mod_dir.name.startswith("D1C_Class_")), rows=rows))
        drpgvoice.link_rows(mod_dir, {r: vid for r in rows})
        meta_f = mod_dir / "mod.json"
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        cast = [c["clip"] for v in done for c in v["clips"] if CAST_ROLE in c["roles"]]
        meta.setdefault("source_import", {})["voice"] = (
            "own (the shared monster sound effect Disgaea 1 plays for this monster)"
            if voice_map()["mods"][mod_dir.name].get("sound_effect") else
            "own (Disgaea 1, EN + JP: attack and skill shouts, all Disgaea 1 voices; no damage / death line in the game)"
            + (f"; clip {', '.join(sorted(set(cast)))}: {CAST_LABEL}" if cast else ""))
        meta_f.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    except (FileNotFoundError, ValueError, KeyError) as exc:
        kept.append(dict(mod=mod_dir.name, voice="donor (unchanged)", reason=f"{type(exc).__name__}: {exc}"))
    receipt = dict(schema="d1c-voice-receipt/1", mod=mod_dir.name, voices=done, donor_kept=kept, silent=silent,
                   map_sha256=hashlib.sha256(MAP_FILE.read_bytes()).hexdigest())
    if done:
        (mod_dir / "patches/voices/d1c-voice-receipt.json").write_text(json.dumps(receipt, indent=1) + "\n")
    return receipt
