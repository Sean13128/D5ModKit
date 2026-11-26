"""Read-only D4 content inventory; output metadata belongs outside the source repository.

Uses the kit's existing source/archive/script readers. No game bytes are exported.
Record occurrences are retained even when source identifiers collide. Static edges
are evidence of stored references, never of native compatibility or fidelity.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import importlib.util
from pathlib import Path
import re
import struct

from . import d4source, fafs, script, sound

SCHEMA = "d4-content-inventory/1"
STAGES = ("extraction", "conversion", "implementation", "gameplay", "presentation")
# Command widths corroborated by the October 18 native constructor trace. Other
# commands inherit the D5 grammar and therefore remain provisional for D4.
D4_SIGNATURES = {
    0x4620: [1, 2], 0x4622: [1, 2, 1], 0x4410: [1, 1, 1, 1],
    0x4418: [1, 1, 1, 1, 1, 2], 0x646A: [2, 1], 0x7220: [1, 2, 2],
    0x7228: [1, 1], 0x72D0: [2, 2], 0x3700: [], 0x3701: [],
    0x668C: [2, 2], 0x7226: [],
    # SPECBULK1 (2026-11-20): read from each command's own operand parser (the
    # fifth entry of its registered vtable) by emulating it over a literal-only
    # operand stream; the twelve rows above come out identical the same way.
    # D4 differs from D5 here (4630 voice is a u16, sound 46xx channels are u8,
    # 64a0 has a fourth byte) or D5 has no such command. Pinned in
    # tests/test_d4_signatures.py against the original Disgaea4pc.exe.
    0x4600: [1], 0x4602: [1, 4], 0x4604: [1, 1], 0x4606: [1, 1],
    0x460A: [1], 0x460C: [1], 0x4630: [2, 1], 0x641C: [2, 2],
    0x64A0: [2, 2, 1, 1], 0x2816: [1, 4, 4, 1], 0x2817: [1, 1, 2, 1],
    0x32E0: [2], 0x3710: [1, 1, 1], 0x3711: [1, 1, 1], 0x6419: [1, 2, 2, 1],
    0x64F0: [2, 2], 0x6B00: [2, 2, 2, 2, 2], 0x6B02: [2, 2, 2, 2],
    0x6B05: [2, 2, 2], 0x6B07: [2, 2, 2], 0x6B0A: [2, 2, 2, 2],
    0x6B0C: [2, 2, 2], 0x6B0F: [2, 2], 0x72D2: [1, 1], 0x7897: [2, 1, 1],
    0x789A: [2], 0x78B4: [2], 0x78B9: [2], 0x78C0: [2], 0x78D0: [1],
}
LIMITATIONS = [
    "Semantic records are decoded for the selected database language; other localizations are resource-indexed.",
    "All character rows, including NPC/enemy/variant definitions, are retained; recruitability is not inferred.",
    "Family grouping uses decimal ID bands and is a candidate grouping, not a native class/unlock contract.",
    "Static call graphs cover literal references only; variable-selected calls/resources and engine dispatch remain unresolved.",
    "Twelve D4 command signatures are native-corroborated; remaining inherited D5 grammar is provisional. Byte roundtrip is not semantic proof.",
    "Unparsed events retain hashes/bounds and an explicit blocker; no prefix dependencies are treated as complete.",
    "Effect filenames resolve loads/preloads; internal model textures, material/motion dependencies and rendering contracts need conversion/validation.",
    "Body/portrait/illustration/voice associations include labeled numbering conventions; UI routes and runtime residency are not completely traced.",
    "SE filename links are candidates; opcode routing, sound situations, story-speaker attribution and dynamic audio remain unresolved.",
    "Evility parameter bytes do not specify engine behavior, stacking, eligibility, rounding or ordering.",
    "Growth, native damage/targeting/conditions, special actions, attachment semantics, timing, skip cleanup and save behavior require independent validation.",
    "No D5 identifiers are leased, no assets converted, no content installed, and no gameplay/presentation acceptance is implied by this inventory.",
]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def hash_range(path, offset=0, size=None):
    """Stream hashes; reject truncated ranges instead of accepting partial evidence."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        f.seek(offset)
        remaining = Path(path).stat().st_size - offset if size is None else size
        if offset < 0 or remaining < 0:
            raise ValueError("negative source range")
        while remaining:
            b = f.read(min(1024 * 1024, remaining))
            if not b:
                raise ValueError(f"truncated source range: {path}")
            h.update(b)
            remaining -= len(b)
    return h.hexdigest()


def checked_rows(data, stride):
    if len(data) < 4:
        raise ValueError("truncated table header")
    count = struct.unpack_from("<I", data)[0]
    if len(data) != 4 + count * stride:
        raise ValueError(f"table size {len(data)} != 4 + {count} * {stride}")
    return [data[4 + i * stride:4 + (i + 1) * stride] for i in range(count)]


def default_status(extraction="metadata-verified"):
    return dict(extraction=extraction, conversion="not-started", implementation="not-started",
                gameplay="not-tested", presentation="not-tested")


def archive_entries(path):
    """Return all occurrences; never collapse archive duplicate names."""
    path = Path(path)
    size = path.stat().st_size
    with path.open("rb") as f:
        magic = f.read(8)
        f.seek(0)
        if magic[:4] == b"NSAC":
            # Nsac exposes a dict, so validate with it but retain occurrences from
            # its name records separately to make duplicate-name collisions visible.
            d4source.Nsac(path)
            h = f.read(28)
            _, _, count, _, data_at, idx_size, names_size, _ = struct.unpack("<4sHH5I", h)
            f.seek(28 + idx_size)
            names = f.read(names_size)
            out, pos = [], 0
            for _ in range(count):
                n, off, length = struct.unpack_from("<HII", names, pos)
                pos += 10
                if pos + n >= len(names) or names[pos + n] != 0:
                    raise ValueError("invalid NSAC member name")
                out.append((names[pos:pos + n].decode("ascii"), off, length))
                pos += n + 1
            if pos != names_size or any(off < data_at for _, off, _ in out):
                raise ValueError("invalid NSAC directory")
            kind = "NSAC-v2"
        elif magic == fafs.MAGIC:
            entries = fafs.read_index(f)
            out = [(e.name, e.offset, e.size) for e in entries]
            kind = "FAFULLFS"
        elif magic in (sound.MAGIC, sound.DSARC_MAGIC):
            pack = sound.PsfsPack(path)
            try:
                out = [(e.name, e.offset, e.size) for e in pack.entries]
            finally:
                pack.close()
            kind = magic.decode("ascii")
        else:
            return None, []
    if any(off < 0 or length < 0 or off + length > size for _, off, length in out):
        raise ValueError(f"archive member outside file: {path}")
    return kind, out


def script_reader():
    """An isolated copy of the existing parser; D5 SIGS are never mutated."""
    spec = importlib.util.spec_from_file_location("d5lib._d4_inventory_script", script.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SIGS.update({k: list(v) for k, v in D4_SIGNATURES.items()})
    return module


def event_records(raw):
    """Yield occurrence, ID, byte range, parse evidence, references and gaps."""
    if len(raw) < 4:
        raise ValueError("truncated event directory")
    count = struct.unpack_from("<I", raw)[0]
    base = 4 + count * 8
    if base > len(raw):
        raise ValueError("truncated event directory")
    offsets = struct.unpack_from(f"<{count}I", raw, 4)
    ids = struct.unpack_from(f"<{count}I", raw, 4 + count * 4)
    code = raw[base:]
    if count and (offsets[0] != 0 or list(offsets) != sorted(offsets) or offsets[-1] > len(code)):
        raise ValueError("invalid event offsets")
    reader = script_reader()
    for i, (eid, lo, hi) in enumerate(zip(ids, offsets, (*offsets[1:], len(code)))):
        b = code[lo:hi]
        info = dict(id=eid, row_index=i, offset=base + lo, bytes=len(b), sha256=sha256(b),
                    decoded=False, references=[], dynamic=[], native_opcodes=[])
        try:
            e = reader.parse_event(eid, code, lo, hi)
            if e.encode() != b:
                raise ValueError("event byte roundtrip mismatch")
            info.update(decoded=True, byte_exact_roundtrip=True, instruction_count=len(e.code))
            pos = 0
            native = Counter()
            for ins in e.code:
                if ins.cid in (0x0100, 0x0104, 0x0106):
                    relation, slot = "calls-event", 0
                elif ins.cid == 0x3C00:
                    relation, slot = "loads-effect", 1
                elif ins.cid == 0x3CF4:
                    relation, slot = "preloads-effect", 0
                elif ins.cid in (0x4610, 0x4612, 0x4618):
                    relation, slot = "sound-filename-candidate", 0
                else:
                    relation = None
                if relation:
                    value = ins.args[slot]
                    ref = dict(relation=relation, opcode=f"{ins.cid:04x}", instruction_offset=pos)
                    if isinstance(value, int):
                        info["references"].append(dict(ref, id=value))
                    else:
                        info["dynamic"].append(dict(ref, variable_id=value.id, variable_kind=value.kind))
                if ins.cid >> 8 in (0x72, 0x78):
                    native[f"{ins.cid:04x}"] += 1
                pos += ins.size()
            info["native_opcodes"] = dict(sorted(native.items()))
        except (ValueError, IndexError, KeyError, struct.error, OverflowError) as ex:
            info["decode_error"] = str(ex)
        yield info


class Inventory:
    def __init__(self, root, lang="EN"):
        self.root = Path(root).resolve()
        self.lang = lang.upper()
        self.data = dict(schema=SCHEMA, source_edition="Disgaea 4 Complete+ PC installed files",
                         source_root=str(self.root), language=self.lang,
                         evidence_scope="Stored bytes and provisional static interpretation; no runtime acceptance",
                         items=[], edges=[], collisions=[], unresolved=[], limitations=list(LIMITATIONS))
        self.items = {}
        self.lookup = defaultdict(list)
        self.resources = defaultdict(list)

    def add(self, kind, uid, source=None, **fields):
        if uid in self.items:
            raise ValueError(f"duplicate inventory uid: {uid}")
        item = dict(uid=uid, kind=kind, source=source or {}, status=default_status(),
                    fidelity="partial", target=None, **fields)
        self.items[uid] = item
        self.data["items"].append(item)
        return item

    def edge(self, source, target, relation, confidence="observed", **evidence):
        targets = target if isinstance(target, list) else [target]
        targets = [t for t in targets if t]
        resolution = "resolved" if len(targets) == 1 else "ambiguous" if targets else "unresolved"
        edge = dict(source=source, targets=targets, relation=relation,
                    confidence=confidence, resolution=resolution, **evidence)
        self.data["edges"].append(edge)
        if resolution != "resolved":
            self.data["unresolved"].append(edge)

    def files(self):
        # These are game-provided save templates, not content definitions. Never
        # inspect save bytes; preserve an explicit exclusion instead of omitting it.
        excluded = []
        for path in sorted(p for p in self.root.rglob("*") if p.is_file()):
            rel = path.relative_to(self.root).as_posix()
            if "SAVEDATA" in (x.upper() for x in path.relative_to(self.root).parts):
                excluded.append(dict(path=rel, reason="save bytes excluded"))
                continue
            uid = f"d4:file:{rel}"
            self.add("source-file", uid, dict(path=rel, bytes=path.stat().st_size, sha256=hash_range(path)))
            try:
                kind, entries = archive_entries(path)
            except (ValueError, IndexError, struct.error, UnicodeError) as ex:
                self.items[uid]["archive_error"] = str(ex)
                self.items[uid]["fidelity"] = "blocked"
                continue
            if not kind:
                continue
            self.items[uid]["archive_format"] = kind
            self.items[uid]["member_count"] = len(entries)
            names = defaultdict(list)
            for i, (name, off, length) in enumerate(entries):
                mid = f"d4:resource:{rel}::{name}:entry:{i}"
                self.add("resource", mid, dict(path=rel, member=name, entry_index=i, offset=off,
                                               bytes=length, sha256=hash_range(path, off, length)),
                         resource_type=self.resource_type(rel, name))
                self.resources[(rel, name.lower())].append(mid)
                names[name.lower()].append(mid)
                self.edge(mid, uid, "contained-in")
            for name, occurrences in names.items():
                if len(occurrences) > 1:
                    self.data["collisions"].append(dict(namespace=f"archive:{rel}", identifier=name,
                                                         items=occurrences))
        self.data["excluded"] = excluded

    @staticmethod
    def resource_type(path, name):
        if path.endswith("/voice.dat"):
            return "battle-voice"
        if path.endswith("/msg.dat"):
            return "message-voice-unattributed"
        if path.endswith("/se.dat"):
            return "sound-effect"
        if "EFFECT" in path:
            return "effect-bank"
        if "ANM" in path or name.lower().endswith(".anm"):
            return "animation-or-illustration"
        if path.endswith("/WF.dat"):
            return "face-portrait"
        if "DATABASE" in path:
            return "database-table"
        return "shared-or-unclassified"

    def member(self, path, name):
        return self.resources[(path, name.lower())]

    def table_rows(self, d4, name, stride, kind, decoder, id_offset, id_format):
        raw = d4.db.read(name)
        dbrel = d4.db.path.relative_to(self.root).as_posix()
        for i, row in enumerate(checked_rows(raw, stride)):
            sid = struct.unpack_from("<" + id_format, row, id_offset)[0]
            uid = f"d4:{self.lang}:{kind}:{sid}:row:{i}"
            item = self.add(kind, uid, dict(path=dbrel, member=name, row_index=i, offset=4 + i * stride,
                                           bytes=stride, sha256=sha256(row)), source_id=sid, data=decoder(row))
            self.lookup[(kind, sid)].append(uid)
            self.edge(uid, self.member(dbrel, name), "record-in")
            yield item

    def tables(self):
        d4 = d4source.D4Data(self.root, self.lang)
        def character(r):
            decoded = d4source.decode_char(r)
            # Keep original slot pairing even when unused codes occur in the middle.
            decoded["weapon_skill_entries"] = [dict(slot=i, stored_code=code, threshold=threshold)
                for i, (code, threshold) in enumerate(zip(struct.unpack_from("<16H", r, 0x94),
                                                          struct.unpack_from("<16H", r, 0x114))) if code]
            return decoded
        self.chars = list(self.table_rows(d4, "char.dat", d4source.CHAR_STRIDE, "character",
                                         character, 0x194, "H"))
        def evility(r):
            text = d4source._texts(r[12:])
            return dict(name=text[0] if text else "", desc=" ".join(text[1:2]),
                        mana=struct.unpack_from("<I", r)[0], value=r[13],
                        native_behavior="unresolved; parameter bytes do not define the rule")
        def skill(r):
            return dict(name=r[184:248].split(b"\0", 1)[0].decode("utf-8", "replace"),
                        desc=r[56:184].split(b"\0", 1)[0].decode("utf-8", "replace"))
        self.evilities = list(self.table_rows(d4, "mskill.dat", d4source.EVILITY_STRIDE,
                                              "evility", evility, 8, "H"))
        self.skills = list(self.table_rows(d4, "magic.dat", d4source.SKILL_STRIDE,
                                          "skill", skill, 40, "I"))
        if "charhelp.dat" in d4.db.members:
            list(self.table_rows(d4, "charhelp.dat", d4source.HELP_STRIDE, "character-help",
                                 lambda r: {}, 0, "H"))
        if "charPersonal.dat" in d4.db.members:
            list(self.table_rows(d4, "charPersonal.dat", 70, "personality",
                                 lambda r: dict(index=struct.unpack_from("<H", r, 2)[0]), 0, "H"))
        if "script.dat" in d4.db.members:
            dbrel = d4.db.path.relative_to(self.root).as_posix()
            for record in event_records(d4.db.read("script.dat")):
                sid, i = record["id"], record["row_index"]
                uid = f"d4:{self.lang}:event:{sid}:row:{i}"
                loc = {k: record.pop(k) for k in ("row_index", "offset", "bytes", "sha256")}
                self.add("event", uid, dict(path=dbrel, member="script.dat", **loc),
                         source_id=sid, data=record)
                self.lookup[("event", sid)].append(uid)
                self.edge(uid, self.member(dbrel, "script.dat"), "record-in")
        for (kind, sid), occurrences in self.lookup.items():
            # Personality family keys legitimately repeat with distinct indices.
            if len(occurrences) > 1 and kind != "personality":
                self.data["collisions"].append(dict(namespace=kind, identifier=sid, items=occurrences))

    def voices(self):
        self.voice_groups = defaultdict(list)
        for path in sorted((self.root / "Data/SOUND").glob("SoundData_Voice_*.dat")):
            lang = path.stem.removeprefix("SoundData_Voice_")
            raw = path.read_bytes()
            if len(raw) < 12:
                raise ValueError(f"truncated voice table: {path}")
            stride, count, _ = struct.unpack_from("<III", raw)
            if stride != 64 or len(raw) != 12 + count * stride:
                raise ValueError(f"invalid voice table: {path}")
            rel = path.relative_to(self.root).as_posix()
            for i in range(count):
                row = raw[12 + i * stride:12 + (i + 1) * stride]
                line, group, volume, *flags = struct.unpack("<IIf13I", row)
                uid = f"d4:{lang}:voice-line:{line}:row:{i}"
                self.add("voice-line", uid, dict(path=rel, row_index=i, offset=12 + i * stride,
                                                 bytes=stride, sha256=sha256(row)), source_id=line,
                         data=dict(group=group, volume=volume, flags=flags, situation_semantics="unresolved"))
                self.voice_groups[group].append(uid)
                self.edge(uid, f"d4:file:{rel}", "record-in")
                pack = f"Data/SOUND/{lang}/voice.dat"
                # Line width differs among archives; match numeric identity rather than padding.
                candidates = []
                for (archive, name), refs in self.resources.items():
                    if archive == pack and re.fullmatch(rf"{lang.lower()}/{group}/voice_0*{line}\.nlsd", name):
                        candidates.extend(refs)
                self.edge(uid, candidates, "voice-recording", line=line, group=group)

    def dependencies(self):
        families = defaultdict(list)
        anm, face = "Data/DATA/ANM_HI.dat", "Data/DATA/WF.dat"
        for c in self.chars:
            d, uid = c["data"], c["uid"]
            sid = c["source_id"]
            base = sid // 10 * 10
            families[base].append(uid)
            for sk, level in d["learnset"]:
                self.edge(uid, self.lookup[("skill", sk)], "learns-skill", level=level, source_id=sk)
            for entry in d["weapon_skill_entries"]:
                encoded, threshold = entry["stored_code"], entry["threshold"]
                self.edge(uid, self.lookup[("skill", encoded - 10000)], "weapon-skill-candidate",
                          "inferred", stored_code=encoded, source_id_candidate=encoded - 10000,
                          threshold=threshold, threshold_unit="unresolved")
            for ev in sorted(set(d["evilities"] + ([d["innate_evility"]] if d["innate_evility"] else []))):
                self.edge(uid, self.lookup[("evility", ev)], "innate-evility" if ev == d["innate_evility"] else "learnable-evility", source_id=ev)
            self.edge(uid, self.lookup[("character-help", d["help_id"])], "help-text", "parser-established", source_id=d["help_id"])
            self.edge(uid, self.member(anm, f"anm{d['body']:05d}.lzs"), "body-animation", "parser-established", body=d["body"])
            self.edge(uid, self.member(face, f"swf{d['color_id']:04d}.nltx"), "face-candidate", "inferred", color=d["color_id"])
            self.edge(uid, self.member(anm, f"anm{10000 + d['color_id']:05d}.lzs"), "illustration-candidate", "inferred", color=d["color_id"])
            if d["kind_gender"] in (1, 2, 11, 12):
                self.edge(uid, self.member(anm, "anm00001.lzs"), "shared-humanoid-actions", "parser-established")
            groups = range(base, base + 3) if 1000 <= sid < 2400 else [sid]
            for group in groups:
                self.edge(uid, self.voice_groups.get(group, []), "voice-group-candidate", "inferred", group=group,
                          many_targets_expected=True)
            if 1000 <= sid < 2400:
                self.edge(uid, self.lookup[("personality", base // 10)], "personality-family-candidate",
                          "inferred", many_targets_expected=True)
        for base, members in sorted(families.items()):
            uid = f"d4:{self.lang}:family-candidate:{base}"
            item = self.add("family-candidate", uid, source_id=base,
                            data=dict(rule="floor(character_id / 10) * 10; native family contract unverified",
                                      members=members, generic_range_candidate=1000 <= base < 2400))
            item["status"]["extraction"] = "metadata-derived"
            for member in members:
                self.edge(uid, member, "includes-character", "inferred")
        for skill in self.skills:
            sid = skill["source_id"]
            for mode, bias in (("normal", 12000000), ("short", 12100000), ("mid-skip", 12200000)):
                self.edge(skill["uid"], self.lookup[("event", bias + sid)], "skill-wrapper", "native-traced-rule",
                          mode=mode, event_id=bias + sid)
            # These shared tables are dependencies, not decoded complete mechanics.
            for name in ("magicpower.dat", "magicspendSP.dat", "magic_lv.dat", "AttackMap.dat", "AnimeInfo.dat"):
                db = d4source.DATABASE.format(lang=self.lang)
                self.edge(skill["uid"], self.member(db, name), "shared-combat-table", "parser-established")
        for event in [x for x in self.data["items"] if x["kind"] == "event"]:
            d, uid = event["data"], event["uid"]
            if not d["decoded"]:
                event["fidelity"] = "blocked"
                event["blockers"] = ["unknown-event-grammar"]
            for ref in d["references"]:
                relation, sid = ref["relation"], ref["id"]
                if relation == "calls-event":
                    target = self.lookup[("event", sid)]
                    confidence = "observed-literal/provisional-grammar"
                elif relation in ("loads-effect", "preloads-effect"):
                    target = self.member(f"Data/DATA/{self.lang}/EFFECT.dat", f"effect{sid:03d}.lzs")
                    confidence = "native-traced-rule/provisional-grammar"
                else:
                    target = self.member("Data/SOUND/se.dat", f"{sid}.vag")
                    confidence = "filename-candidate"
                self.edge(uid, target, relation, confidence, source_id=sid, opcode=ref["opcode"],
                          instruction_offset=ref["instruction_offset"])
            for ref in d["dynamic"]:
                self.edge(uid, [], ref["relation"], "dynamic-unresolved", **{k: v for k, v in ref.items() if k != "relation"})
        # Multiple voice recordings/personality rows are sets, not ID collisions.
        for edge in self.data["edges"]:
            if edge.get("many_targets_expected") and edge["targets"]:
                edge["resolution"] = "resolved-set"
        self.data["unresolved"] = [e for e in self.data["edges"] if e["resolution"] in ("unresolved", "ambiguous")]

    def frontiers(self):
        """Conservative literal dependency closure for every skill/mode occurrence."""
        by_uid = self.items
        outgoing = defaultdict(list)
        for edge in self.data["edges"]:
            if edge["relation"] in ("calls-event", "loads-effect", "preloads-effect", "sound-filename-candidate"):
                outgoing[edge["source"]].append(edge)
        frontiers = []
        for skill in self.skills:
            modes = {}
            for mode, bias in (("normal", 12000000), ("short", 12100000), ("mid-skip", 12200000)):
                roots = self.lookup[("event", bias + skill["source_id"])]
                todo, seen, resources, unresolved, undecoded, dynamic, native = list(roots), set(), set(), [], [], [], Counter()
                while todo:
                    uid = todo.pop()
                    if uid in seen:
                        continue
                    seen.add(uid)
                    event = by_uid[uid]
                    if not event["data"]["decoded"]:
                        undecoded.append(uid)
                    native.update(event["data"]["native_opcodes"])
                    for edge in outgoing[uid]:
                        if edge["resolution"] in ("unresolved", "ambiguous"):
                            unresolved.append(edge)
                        if edge["confidence"] == "dynamic-unresolved":
                            dynamic.append(edge)
                        if edge["relation"] == "calls-event":
                            todo.extend(edge["targets"])
                        else:
                            resources.update(edge["targets"])
                modes[mode] = dict(wrapper_id=bias + skill["source_id"], roots=roots,
                                   wrapper_resolution="missing" if not roots else "ambiguous" if len(roots) > 1 else "resolved",
                                   events=sorted(seen), resources=sorted(resources), undecoded_events=sorted(undecoded),
                                   unresolved_edges=unresolved, dynamic_references=dynamic,
                                   native_opcodes=dict(sorted(native.items())),
                                   closure_complete=False,
                                   closure_scope="literal stored references only; native and dynamic dependencies unresolved")
            frontiers.append(dict(skill_uid=skill["uid"], source_id=skill["source_id"], modes=modes))
        self.data["skill_frontiers"] = frontiers

    def finish(self):
        self.frontiers()
        self.data["summary"] = summarize(self.data)
        return self.data


def summarize(data):
    kinds = Counter(x["kind"] for x in data["items"])
    events = [x for x in data["items"] if x["kind"] == "event"]
    characters = [x for x in data["items"] if x["kind"] == "character"]
    families = [x for x in data["items"] if x["kind"] == "family-candidate"]
    return dict(items=len(data["items"]), by_kind=dict(sorted(kinds.items())), edges=len(data["edges"]),
                unresolved_edges=len(data["unresolved"]), collisions=len(data["collisions"]),
                character_kind_codes=dict(sorted(Counter(x["data"]["kind_gender"] for x in characters).items())),
                generic_range_family_candidates=sum(x["data"]["generic_range_candidate"] for x in families),
                generic_range_character_rows=sum(1000 <= x["source_id"] < 2400 for x in characters),
                events_decoded=sum(x["data"]["decoded"] for x in events),
                events_undecoded=sum(not x["data"]["decoded"] for x in events),
                dynamic_references=sum(len(x["data"].get("dynamic", [])) for x in events),
                status_by_stage={stage: dict(Counter(x["status"][stage] for x in data["items"])) for stage in STAGES},
                fidelity=dict(Counter(x["fidelity"] for x in data["items"])))


def build_inventory(root, lang="EN"):
    inv = Inventory(root, lang)
    inv.files()
    inv.tables()
    inv.voices()
    inv.dependencies()
    return inv.finish()


def validate_allocations(allocations, occupied=None):
    """Validate proposed receiving IDs without claiming native support or leasing IDs.

    Each allocation: {uid, namespace, target_id, minimum, maximum}. Namespace must
    distinguish every native resource domain (e.g. body versus portrait). Occupied
    is a namespace -> list[int] snapshot from the receiving original + active mods.
    """
    errors, seen, sources = [], {}, set()
    occupied = occupied or {}
    for a in allocations:
        namespace, value, uid = a["namespace"], a["target_id"], a["uid"]
        key = namespace, value
        source_key = uid, namespace
        if source_key in sources:
            errors.append(dict(uid=uid, reason="duplicate-source-allocation"))
        sources.add(source_key)
        if type(value) is not int or not a["minimum"] <= value <= a["maximum"]:
            errors.append(dict(uid=uid, reason="outside-declared-range"))
        if value in occupied.get(namespace, []):
            errors.append(dict(uid=uid, reason="occupied-target-id", namespace=namespace, target_id=value))
        if key in seen:
            errors.append(dict(uid=uid, reason="target-id-collision", other=seen[key], namespace=namespace, target_id=value))
        seen[key] = uid
    return errors


def apply_progress(data, progress):
    """Apply a separate evidence ledger; changing source hashes invalidates progress.

    Ledger is {uid: {source_sha256, status: {...}, fidelity, evidence: [paths/links]}}.
    Inventories can be regenerated without overwriting review/acceptance evidence.
    """
    items = {x["uid"]: x for x in data["items"]}
    allowed = {"not-started", "not-tested", "metadata-verified", "metadata-derived", "partial", "blocked", "passed", "failed", "adapted"}
    updates = []
    for uid, record in progress.items():
        if uid not in items:
            raise ValueError(f"progress for missing item: {uid}")
        item = items[uid]
        if not item["source"].get("sha256") or record.get("source_sha256") != item["source"]["sha256"]:
            raise ValueError(f"stale or missing source hash for progress: {uid}")
        if not record.get("evidence"):
            raise ValueError(f"progress requires evidence: {uid}")
        status = record.get("status", {})
        if any(k not in STAGES or v not in allowed for k, v in status.items()):
            raise ValueError(f"invalid stage status: {uid}")
        fidelity = record.get("fidelity", item["fidelity"])
        if fidelity not in ("faithfully-reproduced", "adapted", "partial", "blocked"):
            raise ValueError(f"invalid fidelity: {uid}")
        merged = dict(item["status"], **status)
        if fidelity == "faithfully-reproduced" and any(merged[s] != "passed" for s in ("conversion", "implementation", "gameplay", "presentation")):
            raise ValueError(f"faithful claim lacks completed independent stages: {uid}")
        updates.append((item, merged, fidelity, record["evidence"]))
    for item, status, fidelity, evidence in updates:
        item.update(status=status, fidelity=fidelity, evidence=evidence)
    data["summary"] = summarize(data)
