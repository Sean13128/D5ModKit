"""Disgaea D2 voices -> D5 custom voices (lane VOICE1, 2026-11-10).

Source (read-only): the PS3 disc's `SndPakVoiceEN_*.pak` / `SndPakVoiceJP_*.pak` (big-endian VAGp PS-ADPCM, 22050 Hz).
Which clip a character says in which selector column is the game's own table (`importers/dd2-voice-map.json`:
indices and offsets read from the executable by VOICEMAP1, no audio).  What a column means in D5 is
`importers/dd2-voice-routes.json`: measured on the 25 characters both games share with the same recordings; only
columns that pass the leave-one-character-out rule are used, the rest stay silent.

Both dubs exist, so every line carries an English and a Japanese file (the D4 way); nothing is borrowed.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from . import drpgvoice

HERE = Path(__file__).resolve().parent
MAP_FILE = HERE / "importers/dd2-voice-map.json"
ROUTES_FILE = HERE / "importers/dd2-voice-routes.json"
_cache = {}


def voice_map():
    if "map" not in _cache:
        _cache["map"] = json.loads(MAP_FILE.read_text())
    return _cache["map"]


def routes():
    """{'category:column': {kind: [situations]}} of the columns that are used."""
    return {k: {int(kind): v["cats"] for kind, v in r["kinds"].items()}
            for k, r in json.loads(ROUTES_FILE.read_text())["routes"].items() if r["shipped"]}


ADAPTED = "adapted: cue position inside the skill not matched one to one"
BLOCKING = ("unproven", "unknown")          # reasons that hold a character at partial (DD2VOICE5); the others do not count
REASON_ORDER = ("unproven", "unknown", "no_d5_situation", "no_place_found", "not_called_in_source")   # a clip is counted once, first match


def route_doc():
    return json.loads(ROUTES_FILE.read_text())["routes"]


def leases():
    """{voice key: custom voice id}"""
    return {int(k): int(c["voice_id"]) for k, c in voice_map()["characters"].items()}


def voice_name(char, where="dd2-voice-map"):
    """The character name the voice record carries, resolved from the map's ``@text`` reference.

    TEXTHASH-D1C-DD2: the map stores the Disgaea D2 character name as a SHA-256 reference; the
    string comes from the prepared DD2 source (``START_4.dat`` char table)."""
    from . import textrefs
    name = char.get("name")
    if textrefs.has_refs(name):
        from .importers import _dd2_source
        name = textrefs.resolve(name, _dd2_source.text_pool().get, where)
    return name


def _pak(source, dub, number):
    """bytes of a voice pak, found by file name under the source folder and checked against the recorded sha256."""
    key = (str(source), dub, int(number))
    if key not in _cache:
        info = voice_map()["paks"][dub][str(number)]
        hits = sorted(Path(source).rglob(info["file"]))
        if not hits:
            raise FileNotFoundError(f"{info['file']} not found under {source}")
        raw = hits[0].read_bytes()
        if hashlib.sha256(raw).hexdigest() != info["sha256"]:
            raise ValueError(f"{info['file']} is not the BLUS31313 disc file the voice map was read from")
        _cache[key] = raw
    return _cache[key]


def decode_vag(vag):
    """VAGp clip -> mono float32 at 48 kHz (ffmpeg)."""
    import numpy as np
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("Disgaea D2 voices are PS-ADPCM audio: install ffmpeg (and add it to PATH) to convert them.")
    if vag[:4] != b"VAGp":
        raise ValueError("not a VAGp clip")
    r = subprocess.run([exe, "-v", "error", "-f", "vag", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", "48000",
                        "pipe:1"], input=vag, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode or not r.stdout:
        raise ValueError("VAGp decode failed: " + r.stderr.decode("utf8", "replace")[:200])
    return np.frombuffer(r.stdout, dtype="<f4")


def import_voice(mod_dir, source, key, voice_id, class_, name=""):
    """Write DD2 voice key `key` into the mod as custom voice `voice_id`.  A class keeps its three source variants as
    the three D5 personalities; a unique character uses variant 0.  -> receipt dict."""
    from . import modsys, voices
    char = voice_map()["characters"][str(int(key))]
    clip_index, table = voice_map()["clips"], routes()
    dest = {}                                             # (personality, source voice id, kind) -> situations
    unrouted = set()
    for row, ids in char["rows"].items():
        cat, variant, column = row.split(":")
        if int(variant) > (2 if class_ else 0):
            continue
        r = table.get(f"{cat}:{column}")
        if r is None:
            unrouted.add(f"{cat}:{column}")
            continue
        for vid in ids:
            for kind, cats in r.items():
                dest.setdefault((int(variant), int(vid), kind), set()).update(cats)
    shipped_ids = {v for _p, v, _k in dest}
    doc = route_doc()
    held = {}                                             # DD2VOICE5: column -> clips only held columns list (any variant, any category)
    also = {}                                             # column -> clips it lists that another column routes
    for row, ids in char["rows"].items():
        cat, variant, column = row.split(":")
        col = f"{cat}:{column}"
        if col in table:
            continue
        for vid in ids:
            (also if vid in shipped_ids else held).setdefault(col, set()).add(vid)
    reason_of = {c: doc.get(c, {}).get("hold_reason", "unknown") for c in set(held) | set(also)}
    held_back = {c: dict(reason=reason_of[c], clips=sorted(held.get(c, ())), also_routed=sorted(also.get(c, ())))
                 for c in sorted(set(held) | set(also))}
    by_reason, seen = {}, set()                           # distinct clips per reason, each clip once, first reason in REASON_ORDER
    for reason in REASON_ORDER:
        ids = {v for c, h in held_back.items() if h["reason"] == reason for v in h["clips"]} - seen
        seen |= ids
        if ids:
            by_reason[reason] = len(ids)
    roles = {}                                            # (personality, clip) -> {column: role} over shipped battle columns
    for row, ids in char["rows"].items():
        cat, variant, column = row.split(":")
        r = doc.get(f"{cat}:{column}")
        if cat != "0" or not r or not r.get("shipped") or int(variant) > (2 if class_ else 0):
            continue
        for vid in ids:
            roles.setdefault((int(variant), int(vid)), {})[f"{cat}:{column}"] = r["role"]
    dual_use = [dict(personality=p, clip=v, columns=sorted(c),
                     destinations={col: {k: r_["cats"] for k, r_ in doc[col]["kinds"].items()} for col in sorted(c)},
                     label="one source clip listed in several columns: it plays in each destination (" +
                           ", ".join(f"{col} = {c[col]}" for col in sorted(c)) + ")")
                for (p, v), c in sorted(roles.items()) if len(set(c.values())) > 1]
    routes_used = {col: dict(role=doc[col]["role"], destinations={k: r_["cats"] for k, r_ in doc[col]["kinds"].items()},
                             label=doc[col].get("label", "proven in both games"), evidence=doc[col].get("evidence", "see routes file basis"))
                   for col in sorted({f"{r.split(':')[0]}:{r.split(':')[2]}" for r in char["rows"]})
                   if col in doc and doc[col].get("shipped") and doc[col].get("role") and col.startswith("0:")}
    mod = modsys.Mod(str(mod_dir))
    folder = Path(voices.folder(mod))
    writes, files, clips, silent = {}, {}, [], []
    for vid in sorted({v for _p, v, _k in dest}):
        for dub, (pak, offset, size, gain) in sorted(clip_index[str(vid)].items()):
            raw = _pak(source, dub, pak)[offset:offset + size]
            pcm = decode_vag(raw)
            seconds = len(pcm) / 48000
            if seconds < drpgvoice.MIN_SECONDS or float(abs(pcm).max()) < 0.01:
                silent.append(dict(voice_id=vid, dub=dub, seconds=round(seconds, 3)))
                continue
            if seconds > drpgvoice.MAX_SECONDS:
                raise ValueError(f"clip {vid} ({dub}): {seconds:.2f} s is not a sane voice clip")
            vag, peak, samples = drpgvoice._encode(pcm)
            fn = f"dd2_{voice_id}_{vid}_{dub}.vag"
            writes[fn] = vag
            files.setdefault(vid, {})[dub] = fn
            clips.append(dict(source_voice_id=vid, dub=dub, pak=pak, offset=offset, size=size, gain_raw=gain,
                              vag_sha256=hashlib.sha256(raw).hexdigest(), file=fn, seconds=round(samples / 48000, 3),
                              peak=round(peak, 4)))
    lines = [dict(kind=kind, cats=sorted(cats), personality=p, volume=voices.DEFAULT_VOLUME, files=files[vid],
                  missing_locale="silence", source_voice_id=vid)
             for (p, vid, kind), cats in sorted(dest.items()) if vid in files]
    if not lines:
        raise ValueError(f"voice key {key} has no audible clip in a used column")
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob(f"dd2_{voice_id}_*.vag"):       # a re-stage on an installed pack: clips of columns that
        if old.name not in writes:                         # are no longer routed must not stay behind
            old.unlink()
    for fn, raw in writes.items():
        (folder / fn).write_bytes(raw)
    data = voices.load(mod)
    data["voices"][str(int(voice_id))] = dict(
        name=(name or voice_name(char, f"dd2-voice-map.characters.{int(key)}"))
             + " (Disgaea D2, English + Japanese)", lines=lines,
        source=dict(game="Disgaea D2 PS3 BLUS31313 (disc)", voice_key=int(key), languages=["EN", "JP"],
                    map="selector columns -> importers/dd2-voice-routes.json",
                    silent_columns=sorted(unrouted),
                    silent_situations="damage, KO, defend: not voiced in the source (DD2LOGGER2: no selector pick, no direct play)",
                    silent_columns_why={c: json.loads(ROUTES_FILE.read_text())["routes"].get(c, {}).get(
                        "silenced", "not a battle situation / preview column") for c in sorted(unrouted)}))
    voices.save(mod, data)
    return dict(voice_key=int(key), voice_id=int(voice_id), clips=clips, lines=len(lines), silent_clips=silent,
                unrouted_columns=sorted(unrouted),
                held_back=held_back, held_by_reason=by_reason, routes_used=routes_used, dual_use=dual_use,
                personalities=sorted({p for p, _v, _k in dest}),
                native_tested=False)


def apply(mod_dir, source):
    """Give a DD2 pack its own source voice (every added char row).  -> receipt, also written beside voices.json."""
    mod_dir = Path(mod_dir)
    meta_f = mod_dir / "mod.json"
    meta = json.loads(meta_f.read_text(encoding="utf-8"))
    done, kept, silent = [], [], []
    rows = [int(r["id"]) for r in json.loads((mod_dir / "patches/db/char.dat.json").read_text(encoding="utf-8-sig"))
            .get("added", [])]
    try:
        cid = ((meta.get("source_import") or {}).get("identity") or {}).get("character_id")
        key = voice_map()["source_ids"].get(str(cid))
        if str(cid) in voice_map().get("silent", {}):        # VOICE2: no selector row for its voice key in DD2
            why = voice_map()["silent"][str(cid)]["reason"]
            silent.append(dict(rows=sorted(drpgvoice.link_silent(mod_dir, "Disgaea D2: " + why)), reason=why))
            return dict(schema="dd2-voice-receipt/1", mod=mod_dir.name, voices=[], donor_kept=[], silent=silent)
        if key is None or str(key) not in voice_map()["characters"]:
            raise KeyError(f"Disgaea D2 character {cid} has no voice rows in the game's selector table (or none recorded)")
        vid = leases()[key]
        done.append(dict(import_voice(mod_dir, source, key, vid, mod_dir.name.startswith("DD2_Class_"),
                                      meta.get("name", "").split("(")[0].strip()), rows=rows))
        drpgvoice.link_rows(mod_dir, {r: vid for r in rows})
        meta.setdefault("source_import", {})["voice"] = (
            "own (Disgaea D2 disc, EN + JP; attack, move, lift, throw, deployment, spell-cast and heal-cast shouts "
            "(DD2LOGGER2-proven), special-skill cues 1 / 4 / 9 (DD2LOGGER3-proven, " + ADAPTED + "). Listed, not routed, with a "
            "reason in the receipt's held_back: support attack, level up / reaction, cinematic, menu and screen voices, "
            "previews; no damage / KO line: not voiced in the source (DD2LOGGER2))")
        meta_f.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    except (FileNotFoundError, ValueError, KeyError) as exc:
        kept.append(dict(mod=mod_dir.name, voice="donor (unchanged)", reason=f"{type(exc).__name__}: {exc}"))
    receipt = dict(schema="dd2-voice-receipt/1", mod=mod_dir.name, voices=done, donor_kept=kept, silent=silent,
                   routes_sha256=hashlib.sha256(ROUTES_FILE.read_bytes()).hexdigest())
    if done:
        (mod_dir / "patches/voices/dd2-voice-receipt.json").write_text(json.dumps(receipt, indent=1) + "\n")
    return receipt
