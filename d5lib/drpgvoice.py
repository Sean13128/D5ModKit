"""Disgaea RPG battle voices -> D5 custom voices (lane VOICE1, 2026-11-10).

Source (read-only): `<source>/extracted/sdcard/Android/data/com.disgaearpg.forwardworks/files/assetbundle/sounds/
voice/battle/<id>/<id>_acb` + `<id>_awb`, one pair per character / costume id.  Each is a UnityFS bundle holding one
TextAsset: a CRI ACB cue sheet (`@UTF`) and its AFS2 wave bank of unencrypted mono HCA clips (Japanese).

The clip-to-situation map is the source game's own: the ACB names every cue (`voice_attack`, `voice_h_attack`,
`voice_damage`, `voice_dead`, `voice_magic`, `voice_recover`, `voice_turn`, `voice_get`, `voice_glad`,
`voice_spNN`).  Where a cue belongs in D5 is `importers/drpg-voice-routes.json`: measured, not guessed, from the 33
characters that exist in both games with the same recordings (see docs/DRPG_VOICES.md).

No audio lives in the kit: this module converts the user's own files into a mod's `patches/voices/`.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTES_FILE = HERE / "importers/drpg-voice-routes.json"
LEASES_FILE = HERE / "importers/drpg-voice-leases.json"
FILES = "extracted/sdcard/Android/data/com.disgaearpg.forwardworks/files"
BANKS = FILES + "/assetbundle/sounds/voice/battle"
LANGUAGE = "JP"                       # the only dub the source has; D5's English setting falls back to it (labelled)
PEAK_LIMIT = 0.85                     # same loudness adaptation as the D4 voices (d4voices.import_d4_voice)
MIN_SECONDS, MAX_SECONDS = 0.08, 20.0


# ------------------------------------------------------------------------------------------ containers
def lz4_block(src, size):
    """LZ4 block decode (UnityFS chunks); pure Python, the banks are a few hundred kB."""
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]; i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255:
                    break
        out += src[i:i + lit]; i += lit
        if i >= n:
            break
        off = src[i] | src[i + 1] << 8; i += 2
        if not 0 < off <= len(out):
            raise ValueError("LZ4: bad match offset")
        m = (token & 15) + 4
        if m == 19:
            while True:
                b = src[i]; i += 1; m += b
                if b != 255:
                    break
        start = len(out) - off
        if off >= m:
            out += out[start:start + m]
        else:                                     # overlapping match: the pattern repeats
            for k in range(m):
                out.append(out[start + k])
    if len(out) != size:
        raise ValueError("LZ4: size mismatch")
    return bytes(out)


def _unpack(data, flags, size):
    kind = flags & 0x3F
    if kind == 0:
        return bytes(data)
    if kind in (2, 3):
        return lz4_block(data, size)
    raise ValueError(f"UnityFS compression {kind} not supported")


def unityfs_payload(raw, magic):
    """The one TextAsset payload starting with `magic` inside a UnityFS bundle (no UnityPy needed: the bundle's
    data blocks are unpacked and the length-prefixed byte array is found by its magic)."""
    if raw[:8] != b"UnityFS\0":
        raise ValueError("not a UnityFS bundle")
    version, = struct.unpack_from(">I", raw, 8)
    p = 12
    for _ in range(2):
        p = raw.index(b"\0", p) + 1
    _size, csize, usize, flags = struct.unpack_from(">QIII", raw, p)
    p += 20
    if version >= 7:
        p = (p + 15) // 16 * 16
    info_at = len(raw) - csize if flags & 0x80 else p
    info = _unpack(raw[info_at:info_at + csize], flags, usize)
    if not flags & 0x80:
        p += csize
    if flags & 0x200:
        p = (p + 15) // 16 * 16
    count, = struct.unpack_from(">I", info, 16)
    data = bytearray()
    for k in range(count):
        u, c, f = struct.unpack_from(">IIH", info, 20 + 10 * k)
        data += _unpack(raw[p:p + c], f, u)
        p += c
    at = data.find(magic)
    while at >= 4:
        n, = struct.unpack_from("<I", data, at - 4)
        if 0 < n <= len(data) - at:
            return bytes(data[at:at + n])
        at = data.find(magic, at + 1)
    raise ValueError(f"no {magic!r} payload in the bundle")


_UTF_TYPES = {0: ">B", 1: ">b", 2: ">H", 3: ">h", 4: ">I", 5: ">i", 6: ">Q", 7: ">q", 8: ">f", 9: ">d"}


def utf(raw):
    """CRI @UTF table -> list of row dicts."""
    if raw[:4] != b"@UTF":
        raise ValueError("not a CRI @UTF table")
    b = raw[8:8 + struct.unpack_from(">I", raw, 4)[0]]
    _v, rows_off, str_off, data_off, _name, ncol, row_len, nrow = struct.unpack_from(">HHIIIHHI", b, 0)

    def text(o):
        return b[str_off + o:b.index(b"\0", str_off + o)].decode("utf8", "replace")

    def val(t, p):
        if t in _UTF_TYPES:
            return struct.unpack_from(_UTF_TYPES[t], b, p)[0], p + struct.calcsize(_UTF_TYPES[t])
        if t == 0xA:
            return text(struct.unpack_from(">I", b, p)[0]), p + 4
        if t == 0xB:
            o, n = struct.unpack_from(">II", b, p)
            return b[data_off + o:data_off + o + n], p + 8
        raise ValueError(f"@UTF column type {t}")

    cols, p = [], 24
    for _ in range(ncol):
        flag = b[p]
        name = text(struct.unpack_from(">I", b, p + 1)[0])
        p += 5
        const = None
        if flag >> 4 == 3:
            const, p = val(flag & 15, p)
        cols.append((name, flag & 15, flag >> 4, const))
    rows = []
    for r in range(nrow):
        q, row = rows_off + r * row_len, {}
        for name, t, storage, const in cols:
            if storage == 5:
                row[name], q = val(t, q)
            else:
                row[name] = const
        rows.append(row)
    return rows


def acb_cues(acb):
    """{cue name: [{'awb_id', 'rate', 'samples'}]} -- every waveform a named cue can play (its alternative takes)."""
    head = utf(acb)[0]
    t = {k: utf(head[k]) for k in ("CueNameTable", "CueTable", "SynthTable", "SequenceTable", "TrackTable",
                                   "TrackEventTable", "WaveformTable") if head.get(k)}

    def u16s(blob):
        return struct.unpack(f">{len(blob) // 2}H", blob)

    def ref(kind, index, depth=0):
        if depth > 8:
            raise ValueError("ACB reference loop")
        if kind == 1:
            return [t["WaveformTable"][index]]
        if kind == 2:
            items = u16s(t["SynthTable"][index]["ReferenceItems"])
            return [w for k, x in zip(items[::2], items[1::2]) for w in ref(k, x, depth + 1)]
        if kind == 3:
            out = []
            for track in u16s(t["SequenceTable"][index]["TrackIndex"]):
                cmd = t["TrackEventTable"][t["TrackTable"][track]["EventIndex"]]["Command"]
                p = 0
                while p + 3 <= len(cmd):
                    code, n = struct.unpack_from(">HB", cmd, p)
                    if code in (2000, 2003):                       # note on: (reference kind, index)
                        out += ref(*struct.unpack_from(">HH", cmd, p + 3), depth + 1)
                    p += 3 + n
            return out
        raise ValueError(f"ACB reference kind {kind} not supported")

    cues = {}
    for n in t.get("CueNameTable", []):
        c = t["CueTable"][n["CueIndex"]]
        cues[n["CueName"]] = [dict(awb_id=w["StreamAwbId"] if w["Streaming"] else w["MemoryAwbId"],
                                   rate=w["SamplingRate"], samples=w["NumSamples"])
                              for w in ref(c["ReferenceType"], c["ReferenceIndex"])]
    return cues


def awb_members(raw):
    """CRI AFS2 wave bank -> {wave id: stream bytes}."""
    if raw[:4] != b"AFS2":
        raise ValueError("not a CRI AFS2 wave bank")
    osz, isz = raw[5], raw[6]
    count, align = struct.unpack_from("<IH", raw, 8)
    p = 16
    ids = [int.from_bytes(raw[p + i * isz:p + (i + 1) * isz], "little") for i in range(count)]
    p += count * isz
    offs = [int.from_bytes(raw[p + i * osz:p + (i + 1) * osz], "little") for i in range(count + 1)]
    out = {}
    for i, wid in enumerate(ids):
        start = (offs[i] + align - 1) // align * align
        if not p <= start < offs[i + 1] <= len(raw):
            raise ValueError("AFS2 member outside the bank")
        out[wid] = raw[start:offs[i + 1]]
    return out


# ------------------------------------------------------------------------------------------ source bank
def source_manifest(source):
    """{local path: sha256} from the source extraction's own MANIFEST.json ({} when there is none)."""
    f = Path(source) / "extracted/MANIFEST.json"
    if not f.is_file():
        return {}
    return {r["local_path"]: r["sha256"] for r in json.loads(f.read_text()).get("raw_files", []) if r.get("sha256")}


def read_bank(source, look, manifest=None):
    """-> (cues, {wave id: hca bytes}, provenance).  Refuses a file that differs from the source manifest.

    ``source`` is the importer's verified ``_drpg_source.DrpgData`` (SOURCEPREP4-DRPG): exactly the two manifest rows
    ``assetbundle/sounds/voice/battle/<look>/<look>_acb|awb``, hash-checked in the read; no other file is consulted.
    A plain folder (tools and tests only) is read by those two exact paths, unverified except against ``manifest``."""
    blobs, prov = {}, {}
    if hasattr(source, "voice_bank"):
        from .importers import _drpg_source
        files = source.voice_bank(look)
        for part, magic in (("acb", b"@UTF"), ("awb", b"AFS2")):
            raw = source.read(files[part])
            blobs[part] = unityfs_payload(raw, magic)
            prov[part] = dict(path=f"{_drpg_source.LABEL}/{files[part]}", sha256=source.sha256(files[part]), verified=True)
        return acb_cues(blobs["acb"]), awb_members(blobs["awb"]), prov
    folder = Path(source) / BANKS / str(look)
    for part, magic in (("acb", b"@UTF"), ("awb", b"AFS2")):
        f = folder / f"{look}_{part}"
        if not f.is_file():
            raise FileNotFoundError(f"no Disgaea RPG battle voice bank for id {look} ({f.name})")
        raw = f.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        rel = f.relative_to(Path(source) / "extracted").as_posix()
        if manifest and manifest.get(rel) not in (None, sha):
            raise ValueError(f"{rel} differs from the source manifest (damaged or replaced file)")
        blobs[part] = unityfs_payload(raw, magic)
        prov[part] = dict(path=rel, sha256=sha, verified=bool(manifest and rel in manifest))
    return acb_cues(blobs["acb"]), awb_members(blobs["awb"]), prov


SILENT_VOICE_ID = 5999     # VOICE2: a voice id without lines = the unit says nothing.  D5's own table has 231 char
#                            rows like that (no line row, no pack); 5999 is above the game's ids (they end at 5321)
#                            and below the custom ids (6000+), so no mod can define it.


def _json_layout(raw):
    """(indent, trailing newline) a JSON text was written with, so an edit can keep every other byte (VOICESILENT1)"""
    indent = 1
    for line in raw.splitlines()[1:3]:
        stripped = line.lstrip(" ")
        if stripped and stripped != line:
            indent = len(line) - len(stripped)
            break
    return indent, raw.endswith("\n")


def link_silent(mod_dir, why, keep_layout=False):
    """The source game plays no voice for this character: link every added char row to SILENT_VOICE_ID and say so in
    mod.json (a D5 donor's voice would be an unlabelled borrowed voice).  -> {row: (old, new)}
    keep_layout=True writes mod.json with the indent and final newline it already had (VOICESILENT1: Politan's
    mod.json is indent 2); the default keeps the VOICE2 layout (indent 1 + newline)."""
    mod_dir = Path(mod_dir)
    rows = [int(r["id"]) for r in json.loads((mod_dir / "patches/db/char.dat.json").read_text(encoding="utf-8-sig"))
            .get("added", [])]
    changed = link_rows(mod_dir, {r: SILENT_VOICE_ID for r in rows})
    meta_f = mod_dir / "mod.json"
    raw = meta_f.read_text(encoding="utf-8")
    indent, newline = _json_layout(raw) if keep_layout else (1, True)
    meta = json.loads(raw)
    meta.setdefault("source_import", {})["voice"] = f"silent, as in the source game ({why})"
    meta_f.write_text(json.dumps(meta, indent=indent, ensure_ascii=False) + ("\n" if newline else ""), encoding="utf-8")
    return changed


def routes():
    return json.loads(ROUTES_FILE.read_text())["routes"]


def leases():
    """{look id: custom voice id}"""
    return {int(k): int(v) for k, v in json.loads(LEASES_FILE.read_text())["voice_ids"].items()}


def cue_role(name):
    """'voice_sp07' -> 'voice_sp'; a cue the route table does not know -> None (kept in the receipt, never routed)."""
    base = re.sub(r"\d+$", "", name)
    return base if base in routes() else None


def decode_hca(hca):
    """HCA stream -> mono float32 at 48 kHz, through ffmpeg (the kit's existing optional audio dependency)."""
    import numpy as np
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("Disgaea RPG voices are CRI HCA audio: install ffmpeg (and add it to PATH) to convert them.")
    r = subprocess.run([exe, "-v", "error", "-f", "hca", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", "48000",
                        "pipe:1"], input=hca, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode or not r.stdout:
        raise ValueError("HCA decode failed: " + r.stderr.decode("utf8", "replace")[:200])
    return np.frombuffer(r.stdout, dtype="<f4")


def _encode(pcm):
    """48 kHz float -> .vag, peak-limited (never trimmed or normalised up).  -> (bytes, peak, samples)"""
    import numpy as np
    from . import sfx, sound
    peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
    pcm = pcm * min(1.0, PEAK_LIMIT / peak) if peak else pcm
    for _ in range(4):                               # ADPCM can overshoot the limiter: gain-only retries
        raw = sfx.make_vag(pcm, sfx.RATE, normalize=False, trim=False)
        out, rate = sfx.decode_msadpcm(sound.parse_se(raw)["wav"])
        peak = float(np.max(np.abs(out))) if out.size else 0.0
        if peak <= PEAK_LIMIT + 1e-5:
            break
        pcm = pcm * (PEAK_LIMIT / peak * 0.98)
    if rate != sfx.RATE or peak > PEAK_LIMIT + 1e-5 or not np.isfinite(out).all():
        raise ValueError("converted clip fails the rate / peak / finite checks")
    return raw, peak, len(out)


# ------------------------------------------------------------------------------------------ import
def import_voice(mod_dir, source, look, voice_id, name="", manifest=None):
    """Write Disgaea RPG id `look`'s battle voice into the mod as custom voice `voice_id`.  -> receipt dict.

    Every routed cue becomes one line per D5 kind it is routed to; the takes of a cue stay alternatives (D5 picks at
    random).  Lines are Japanese with an explicit JP fallback for the English setting: no donor line is mixed in.
    """
    from . import modsys, voices
    if not voices.CUSTOM_FIRST <= int(voice_id) <= voices.CUSTOM_LAST:
        raise ValueError("a custom voice id (6000-9999) is required")
    cues, waves, prov = read_bank(source, look, manifest)
    table = routes()
    mod = modsys.Mod(str(mod_dir))
    folder = Path(voices.folder(mod))
    lines, clips, unrouted, writes = [], [], [], {}
    for cue in sorted(cues):
        role = cue_role(cue)
        if role is None or not cues[cue]:
            unrouted.append(dict(cue=cue, takes=len(cues[cue]),
                                 reason="no takes" if role else "cue name outside the reviewed route table"))
            continue
        for take in cues[cue]:
            hca = waves[take["awb_id"]]
            pcm = decode_hca(hca)
            seconds = len(pcm) / 48000
            if seconds < MIN_SECONDS or float(abs(pcm).max()) < 0.01:      # the source's own silent placeholder
                unrouted.append(dict(cue=cue, awb_id=take["awb_id"], seconds=round(seconds, 3),
                                     reason="silent placeholder clip in the source bank"))
                continue
            if seconds > MAX_SECONDS:
                raise ValueError(f"{cue} take {take['awb_id']}: {seconds:.2f} s is not a sane voice clip")
            raw, peak, samples = _encode(pcm)
            fn = f"drpg_{voice_id}_{cue}_{take['awb_id']}.vag"
            writes[fn] = raw
            dests = {int(k): v["cats"] for k, v in table[role].items()}
            for kind, cats in sorted(dests.items()):
                lines.append(dict(kind=kind, cats=cats, personality=0, volume=voices.DEFAULT_VOLUME,
                                  files={LANGUAGE: fn}, fallback_language=LANGUAGE, cue=cue))
            clips.append(dict(cue=cue, role=role, awb_id=take["awb_id"], source_rate=take["rate"],
                              source_samples=take["samples"], hca_sha256=hashlib.sha256(hca).hexdigest(),
                              file=fn, seconds=round(samples / 48000, 3), peak=round(peak, 4),
                              destinations={str(k): c for k, c in sorted(dests.items())}))
    if not lines:
        raise ValueError(f"bank {look} holds no audible routed clip (the character does not speak in Disgaea RPG)")
    folder.mkdir(parents=True, exist_ok=True)                 # nothing is written unless the whole bank converted
    for fn, raw in writes.items():
        (folder / fn).write_bytes(raw)
    data = voices.load(mod)
    data["voices"][str(int(voice_id))] = dict(
        name=(name or f"Disgaea RPG {look}") + " (Disgaea RPG, Japanese)", lines=lines,
        source=dict(game="Disgaea RPG JP (Android)", bank=int(look), language=LANGUAGE, files=prov,
                    map="ACB cue names -> importers/drpg-voice-routes.json", english_setting="plays the Japanese line"))
    voices.save(mod, data)
    return dict(look=int(look), voice_id=int(voice_id), language=LANGUAGE, clips=clips, unrouted=unrouted,
                lines=len(lines), source=prov, native_tested=False)


def link_rows(mod_dir, row_voice):
    """char.dat.json added rows: id -> voice id.  -> {row id: (old, new)}"""
    f = Path(mod_dir) / "patches/db/char.dat.json"
    doc = json.loads(f.read_text(encoding="utf-8-sig"))
    changed = {}
    for r in doc.get("added", []):
        if int(r["id"]) in row_voice:
            changed[int(r["id"])] = (r.get("voice_id"), row_voice[int(r["id"])])
            r["voice_id"] = row_voice[int(r["id"])]
    missing = set(row_voice) - set(changed)
    if missing:
        raise ValueError(f"char rows {sorted(missing)} are not added rows of {Path(mod_dir).name}")
    f.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed


def mod_looks(mod_dir):
    """{char row id: Disgaea RPG id} of a DRPG pack, from its own mod.json (base row + costume rows)."""
    meta = json.loads((Path(mod_dir) / "mod.json").read_text(encoding="utf-8"))
    si = meta.get("source_import") or {}
    a = si.get("leased_ids") or {}
    base = ((si.get("source") or {}).get("row") or {}).get("base_id")
    if base is None or a.get("row") is None:
        raise ValueError(f"{Path(mod_dir).name}: mod.json has no Disgaea RPG base id / row lease")
    out = {int(a["row"]): int(base)}
    for c in a.get("costumes") or []:
        out[int(c["row"])] = int(c["look"])
    return out


def apply(mod_dir, source, manifest=None, lease=None):
    """Give every look of a DRPG pack its own source voice.  A look without a readable bank keeps its donor voice and
    is reported.  -> receipt (also written to patches/voices/drpg-voice-receipt.json)."""
    mod_dir = Path(mod_dir)
    lease = lease or leases()
    meta_f = mod_dir / "mod.json"
    meta = json.loads(meta_f.read_text(encoding="utf-8"))
    looks, done, kept, link = mod_looks(mod_dir), [], [], {}
    for row, look in sorted(looks.items()):
        try:
            if look not in lease:
                raise ValueError("no recorded voice lease")
            done.append(dict(import_voice(mod_dir, source, look, lease[look], meta.get("name", "").split("(")[0].strip(),
                                          manifest), row=row))
            link[row] = lease[look]
        except (FileNotFoundError, ValueError, KeyError, IndexError, struct.error) as exc:
            kept.append(dict(row=row, look=look, voice="donor (unchanged)", reason=f"{type(exc).__name__}: {exc}"))
    # VOICE1b: the installer makes an outfit row follow its character's row, voice included (outfits._follow_base),
    # unless the pack declares the outfit's own voice.  A costume with its own bank is declared; one without follows.
    of = mod_dir / "patches/outfits/outfits.json"
    if of.is_file():
        doc = json.loads(of.read_text(encoding="utf-8"))
        own = sorted(int(b) for _a, b in doc.get("pairs", []) if int(b) in link)
        for a, b in doc.get("pairs", []):
            if int(b) not in link and int(a) in link:
                link[int(b)] = link[int(a)]
                for k in kept:
                    if k["row"] == int(b):
                        k["voice"] = "follows its character's voice (no own bank)"
        if own != sorted(int(x) for x in doc.get("own_voice") or []):
            doc.pop("own_voice", None)
            if own:
                doc["own_voice"] = own
            of.write_text(json.dumps(doc), encoding="utf-8")
    if link:
        link_rows(mod_dir, link)
        label = "own (Disgaea RPG JP battle bank, cue-name map)" if not kept else "own for some looks; donor for the rest"
        meta.setdefault("source_import", {})["voice"] = label
        meta_f.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    silent = []
    if not done and kept and all("holds no audible routed clip" in k["reason"] for k in kept):
        # VOICE2: the bank exists and holds only the source's silent placeholder (master cv_name "-"): the character
        # does not speak in Disgaea RPG, so it does not speak here either (it used to keep a D5 donor's voice)
        why = "Disgaea RPG: no voice actor, the battle bank holds only a silent placeholder"
        silent.append(dict(rows=sorted(link_silent(mod_dir, why)), reason=why))
        kept = []
    receipt = dict(schema="drpg-voice-receipt/1", mod=mod_dir.name, voices=done, donor_kept=kept, silent=silent,
                   routes_sha256=hashlib.sha256(ROUTES_FILE.read_bytes()).hexdigest())
    if done:
        (mod_dir / "patches/voices/drpg-voice-receipt.json").write_text(json.dumps(receipt, indent=1) + "\n")
    return receipt


# ------------------------------------------------------------------------------------------ gate
def voice_gate(mod_dir):
    """Every situation a char row is linked to resolves to a present, decodable clip of sane duration.

    -> (ok, problems, stats).  Checks, for each added char row with a custom voice id: the voice is defined in this
    mod; every line names a file that exists, decodes (48 kHz, finite, peak within the limit) and lasts
    MIN_SECONDS..MAX_SECONDS; both language settings resolve every line; no stray .vag; a battle attack line
    (kind 0, situation 0) exists.  A pack with no custom voice passes with stats['voices'] == 0.
    """
    import numpy as np
    from . import modsys, sfx, sound, voices
    mod_dir = Path(mod_dir)
    problems, stats = [], dict(voices=0, lines=0, files=0, seconds=0.0, situations={})
    mod = modsys.Mod(str(mod_dir))
    data = voices.load(mod)
    folder = Path(voices.folder(mod))
    chf = mod_dir / "patches/db/char.dat.json"
    rows = json.loads(chf.read_text(encoding="utf-8-sig")).get("added", []) if chf.is_file() else []
    linked = {int(r["voice_id"]) for r in rows if int(r.get("voice_id") or 0) >= voices.CUSTOM_FIRST}
    quiet = [r for r in rows if int(r.get("voice_id") or 0) == SILENT_VOICE_ID]
    label = str((json.loads((mod_dir / "mod.json").read_text(encoding="utf-8")).get("source_import") or {}).get("voice"))
    if quiet or label.startswith("silent"):          # VOICE2: silent as in the source = every row, no voice defined
        stats["silent_rows"] = len(quiet)
        if len(quiet) != len(rows) or data["voices"] or not label.startswith("silent"):
            problems.append("silent pack: every added char row must link the voice without lines, no custom voice "
                            "may be defined, and mod.json must say 'silent'")
        if str(SILENT_VOICE_ID) in data["voices"]:
            problems.append(f"voice {SILENT_VOICE_ID} is the voice without lines and must not be defined")
    for vid in sorted(linked):
        if str(vid) not in data["voices"]:
            problems.append(f"char row links custom voice {vid}, which this mod does not define")
    seen, used = {}, set()
    for vid, voice in data["voices"].items():
        stats["voices"] += 1
        if int(vid) not in linked:
            problems.append(f"voice {vid} is defined but no char row uses it")
        sits = set()
        for lang in voices.TABLES:
            try:
                resolved = voices.custom_lines(int(vid), voice, lang=lang)
            except ValueError as exc:
                problems.append(f"voice {vid} ({lang}): {exc}")
                continue
            spoken = [ln for ln in voice.get("lines", [])       # a line may be declared silent in one dub
                      if not ("files" in ln and lang not in ln["files"] and ln.get("missing_locale") == "silence"
                              and not ln.get("fallback_language"))]
            expected = sum(1 if "personality" in ln else voices.PERSONALITIES for ln in spoken)
            if len(resolved) != expected:
                problems.append(f"voice {vid} ({lang}): {expected} lines expected, {len(resolved)} resolve")
            if resolved and not any(voices.split_set(line.group)[0] == 0 and 0 in line.cats for line, _s in resolved):
                problems.append(f"voice {vid} ({lang}): no battle attack line (kind 0, situation 0)")
            per_set = {}
            for line, (kind, ref) in resolved:
                per_set[line.group] = per_set.get(line.group, 0) + 1
                if kind != "file":
                    continue
                used.add(ref)
                sits |= {(voices.split_set(line.group)[0], c) for c in line.cats}
                if not line.cats:
                    problems.append(f"voice {vid}: line {ref} has no situation")
                if ref in seen:
                    continue
                p = folder / ref
                if not p.is_file():
                    seen[ref] = None
                    problems.append(f"voice {vid}: missing clip {ref}")
                    continue
                try:
                    a, rate = sfx.decode_msadpcm(sound.parse_se(p.read_bytes())["wav"])
                except Exception as exc:                                  # noqa: BLE001
                    seen[ref] = None
                    problems.append(f"voice {vid}: {ref} does not decode ({type(exc).__name__})")
                    continue
                seconds = len(a) / rate if rate else 0
                seen[ref] = seconds
                peak = float(np.max(np.abs(a))) if len(a) else 0.0
                if rate != sfx.RATE or not np.isfinite(a).all():
                    problems.append(f"voice {vid}: {ref} is not finite 48 kHz audio")
                if not MIN_SECONDS <= seconds <= MAX_SECONDS:
                    problems.append(f"voice {vid}: {ref} lasts {seconds:.2f} s")
                if peak > PEAK_LIMIT + 1e-3 or peak < 0.01:
                    problems.append(f"voice {vid}: {ref} peak {peak:.3f}")
            if any(n > 512 for n in per_set.values()):
                problems.append(f"voice {vid}: more than 512 lines in one voice set (the game's scan limit)")
        stats["lines"] += len(voice.get("lines", []))
        stats["situations"][str(vid)] = sorted(f"{k}:{c}" for k, c in sits)
    stray = sorted(f.name for f in folder.glob("*.vag") if f.name not in used) if folder.is_dir() else []
    if stray:
        problems.append(f"{len(stray)} clip file(s) no line uses: {stray[:3]}")
    stats["files"] = len([s for s in seen.values() if s is not None])
    stats["seconds"] = round(sum(s for s in seen.values() if s), 1)
    return not problems, problems, stats
