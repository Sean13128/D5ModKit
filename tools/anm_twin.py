"""Compare an imported animation bank with D5's own bank for the same character: structure, not pixels.

The art differs between games, so this compares what the game reads (docs/ANM.md section 8.1), three ways:

* twin: per motion both banks have, the node tree, keys, length, control commands, cells, and the spread of flip,
  cell +4 attribute, blend, depth group, key +3 modes, scale/rotation ranges and attachments; plus the motions only one
  side has.  Native humanoids keep their standard motions in anm_resident block 1 (section 5): their set is that block
  plus their own file.  A pack is paired by its mod.json source_import name with char.dat's EN name; one with no
  same-named D5 sprite is paired with its lease template (d5lib/importers/dd2-leases.json) and marked TEMPLATE.
* novel: byte values the import stores that no D5 bank uses anywhere (all of ANM_HI_JP), field by field.
* source (--d2): the same per-motion profile against the D2 source bank (mod.json identity.body), so a departure the
  source also has reads as faithful, not as a mapping error.

    python tools/anm_twin.py --game "<clean D5 folder>" [--d2 "<D2 Data folder>"] --pack <mod> [--pack ...] --out <dir>

Writes <out>/twin.json and <out>/twin.md.  Reads only; the corpus value table and the parsed anm_resident are cached
in --cache (git-ignored cache/ by default).
"""
import argparse
import collections
import glob
import json
import os
import pickle
import struct
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)

from d5lib import anm, d2anm, lzs, nispack  # noqa: E402

RESIDENT_MOTIONS = 1          # anm_resident block id holding the shared humanoid motions
OWN_MOTIONS_MIN = 20          # a body with fewer animations plays the shared set (anm.find_character_anm's rule)
D2_COMMON = 1                 # D2's shared humanoid motion bank, anm00001
LEASES = os.path.join(KIT, "d5lib", "importers", "dd2-leases.json")
FIELDS = ["nodes", "depth", "named", "binding", "mesh", "keys", "length", "loop", "control", "cells", "layers",
          "flip_x", "flip_y", "attr4", "blend", "depth_group", "cell17", "key_modes", "interp",
          "sx", "sy", "rot", "attach", "attach_missing"]
CELL_BYTES = {"attr4": lambda c: c.unk2 & 255, "blend": lambda c: c.unk2 >> 8, "flip_x": lambda c: c.flags & 255,
              "flip_y": lambda c: c.flags >> 8, "depth_group": lambda c: c.unk8 & 255, "cell17": lambda c: c.unk8 >> 8}


def _set(xs):
    return sorted(set(xs))


def _range(xs):
    return [min(xs), max(xs)] if xs else []


def node_word(n):
    """D5 reads node id + flags as one u32: bits 0-23 asset id (binding key when 24-27 != 0), 28-31 draw mode."""
    return n.id | n.flags << 16


# ------------------------------------------------------------------------------------------------ profiles
def profile(b, a, ids):
    """What the game reads for one animation a of block b; ids: every motion id the bank holds."""
    info = anm.animation_info(b, a)
    walk = list(b.walk(a.root))
    nodes = [b.nodes[i] for i, _, _ in walk]
    root_keys = b.node_keys(b.nodes[a.root])
    keys = [k for n in nodes for k in b.node_keys(n)]
    layer_keys = [k for n in nodes[1:] for k in b.node_keys(n)]
    cells = [b.cells[k.cell] for k in keys if 0 < k.cell < len(b.cells)]
    xf = [b.transforms[k.xform] for k in keys if k.xform < len(b.transforms)]
    attach = [b.params[k.param] for k in keys if k.flags >> 8 == 1 and 0 <= k.param < len(b.params)]
    p = dict(
        nodes=len(nodes), depth=max(d for _, d, _ in walk) - walk[0][1] if walk else 0,
        named=_set(node_word(n) & 0xFFFFFF for n in nodes if node_word(n) & 0xFFFFFF),
        binding=_set(n.flags >> 8 for n in nodes if n.flags >> 8),
        mesh=sum(1 for n in nodes if n.mesh), keys=len(keys), length=info["length"], loop=info["loop"],
        control=[k.flags & 255 for k in root_keys], cells=len(set(k.cell for k in keys if k.cell)),
        layers=info["layers"], key_modes=_set(k.flags >> 8 for k in keys), interp=_set(k.flags & 255 for k in layer_keys),
        sx=_range([t.sx for t in xf]), sy=_range([t.sy for t in xf]), rot=_range([t.rot for t in xf]),
        attach=_set(attach), attach_missing=_set(m for m in attach if m not in ids))
    for name, get in CELL_BYTES.items():
        p[name] = _set(get(c) for c in cells)
    return p


def motions(blocks):
    """{motion id: profile}; the first block holding an id wins (own file before the shared set)."""
    ids = {a.id for b in blocks for a in b.animations}
    out = {}
    for b in blocks:
        for a in b.animations:
            if a.id not in out:
                out[a.id] = profile(b, a, ids)
    return out


def compare(native, imported):
    """{shared, diffs: {motion: {field: [native, import]}}, native_only, import_only, score}.
    score = differing fields per shared motion + native motions the import lacks (the game asks for those)."""
    shared = sorted(set(native) & set(imported))
    diffs = {}
    for m in shared:
        d = {k: [native[m][k], imported[m][k]] for k in FIELDS if native[m][k] != imported[m][k]}
        if d:
            diffs[m] = d
    native_only = sorted(set(native) - set(imported))
    n = sum(len(d) for d in diffs.values())
    return dict(shared=len(shared), diffs=diffs, native_only=native_only,
                import_only=sorted(set(imported) - set(native)),
                score=round(n / max(len(shared), 1) + len(native_only), 2))


def by_field(cmp):
    """[(field, motions that differ, first motion, native, import)], most motions first."""
    acc = {}
    for m, d in cmp["diffs"].items():
        for k, (nv, iv) in d.items():
            acc.setdefault(k, []).append((m, nv, iv))
    return sorted(((k, len(v), *v[0]) for k, v in acc.items()), key=lambda r: (-r[1], FIELDS.index(r[0])))


def values(blocks):
    """{field: Counter(value)} of the stored byte fields D5 reads (root keys = control commands)."""
    v = collections.defaultdict(collections.Counter)
    for b in blocks:
        roots = {a.root for a in b.animations if 0 <= a.root < len(b.nodes)}
        for i, n in enumerate(b.nodes):
            v["node +2 (flags low)"][n.flags & 255] += 1
            v["node +3 (flags high)"][n.flags >> 8] += 1
            v["node mesh"][n.mesh] += 1
            for k in b.node_keys(n):
                v["key +2 root" if i in roots else "key +2 layer"][k.flags & 255] += 1
                v["key +3"][k.flags >> 8] += 1
        for c in b.cells[1:]:
            for name, get in CELL_BYTES.items():
                v["cell " + name][get(c)] += 1
        for t in b.transforms:
            v["transform +6"][t.unk] += 1
    return v


def novel(imported, corpus, source=None):
    """{field: {value: [count in import, count in source or None]}} for values no D5 bank stores."""
    out = {}
    for k, c in imported.items():
        new = {x: [n, source[k][x] if source is not None else None] for x, n in sorted(c.items())
               if str(x) not in corpus.get(k, {})}
        if new:
            out[k] = new
    return out


# ------------------------------------------------------------------------------------------------ inputs
def load(raw):
    """An LZS member ('dat' header) or a pack's uncompressed bank."""
    return anm.AnmFile.parse(lzs.decompress(raw) if raw[:4] == b"dat\0" else raw)


class Game:
    """Clean D5 copy: banks from Data/Anime/ANM_HI_JP.dat, names from Database_0.dat char.dat."""

    def __init__(self, game_dir, cache_dir):
        self.pk = nispack.NisPack(os.path.join(game_dir, "Data", "Anime", "ANM_HI_JP.dat"))
        self.cache_dir = cache_dir
        with nispack.NisPack(os.path.join(game_dir, "Data", "Database", "Database_0.dat")) as db:
            raw = db.read("char.dat")
        count = struct.unpack_from("<I", raw)[0]
        rec = (len(raw) - 4) // count
        self.chars = []
        for i in range(count):
            r = raw[4 + i * rec:4 + (i + 1) * rec]
            gid = struct.unpack_from("<H", r, anm.CHAR_GRAPHICS_OFFSET)[0]
            self.chars.append((i, anm._cstr(r, anm.CHAR_NAME_OFFSETS[1], 52), anm._cstr(r, anm.CHAR_TITLE_OFFSETS[1], 68),
                               gid - gid % 10))
        self._resident = None

    def bank(self, n):
        name = "anm%05d.lzs" % n
        return load(self.pk.read(name)) if name in self.pk.by_name else None

    def _cached(self, name, make):
        p = os.path.join(self.cache_dir, name)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                return pickle.load(fh)
        obj = make()
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(p, "wb") as fh:
            pickle.dump(obj, fh)
        return obj

    def resident(self):
        """anm_resident's blocks (it is 415 MB decompressed; images are not kept)."""
        if self._resident is None:
            self._resident = self._cached("anm_twin_resident.pickle",
                                          lambda: load(self.pk.read("anm_resident.lzs")).blocks)
        return self._resident

    def resident_block(self, block_id):
        return next((b for b in self.resident() if b.id == block_id), None)

    def corpus_values(self):
        """values() over every bank of ANM_HI_JP (keys as strings, as JSON keeps them)."""
        def make():
            total = collections.defaultdict(collections.Counter)
            for e in self.pk.entries:
                if e.name.startswith("anm") and e.name.endswith(".lzs"):
                    for k, c in values(load(self.pk.read(e)).blocks).items():
                        total[k].update({str(x): n for x, n in c.items()})
            return {k: dict(c) for k, c in total.items()}
        return self._cached("anm_twin_corpus_values.pickle", make)

    def native_sets(self, n):
        """[(bank role, blocks)] for D5 sprite n: body (+ the shared motions when it has few of its own), cut-in
        bank 10000+n, resident icon block n+2."""
        out = []
        body = self.bank(n)
        if body:
            shared = self.resident_block(RESIDENT_MOTIONS) if len(body.blocks[0].animations) < OWN_MOTIONS_MIN else None
            out.append(("body", body.blocks + ([shared] if shared else [])))
        cut = self.bank(10000 + n)
        if cut:
            out.append(("cut-in", cut.blocks))
        icon = self.resident_block(n + 2)
        if icon:
            out.append(("icon", [icon]))
        return out


class D2Source:
    """D2 (PS3) banks through d5lib.d2anm; an add-on archive's copy wins over ANM_HI.dat's, as the importer reads."""

    def __init__(self, data_dir):
        archives = sorted(glob.glob(os.path.join(glob.escape(data_dir), "ANM_HI*.dat")),
                          key=lambda p: (len(os.path.basename(p)), p))
        self.index = {}
        for path in archives[1:][::-1] + archives[:1]:
            with open(path, "rb") as fh:
                count = struct.unpack_from(">I", fh.read(16), 12)[0]
                table = fh.read(count * 44)
            for i in range(count):
                name = table[i * 44:i * 44 + 32].split(b"\0")[0].decode("ascii")
                self.index.setdefault(name, (path, *struct.unpack_from(">II", table, i * 44 + 32)))

    def bank(self, n):
        hit = self.index.get("anm%05d.lzs" % n)
        if not hit:
            return None
        path, off, size = hit
        with open(path, "rb") as fh:
            fh.seek(off)
            f = d2anm.parse(lzs.decompress(fh.read(size)))
        d2anm.swap_pivots(f)                       # pivot index where D5 keeps it, so transform +6 compares
        d2anm.d5_node_words(f)                     # node words as D5 reads them, as the importer writes them
        d2anm.d5_palette_counts(f)                 # palette counts as D5 reads them (WRITEWATCH1)
        return f

    def body_blocks(self, n):
        f = self.bank(n)
        if f is None:
            return None
        common = self.bank(D2_COMMON) if len(f.blocks[0].animations) < OWN_MOTIONS_MIN else None
        return f.blocks + (common.blocks[:1] if common else [])


def pack_banks(pack):
    """{bank role: blocks} of a pack: body P (its lowest anm id below 10000), cut-in 10000+P, icon P+2."""
    d = os.path.join(pack, "files", "Anime", "ANM_HI_JP.dat")
    ids = sorted(int(x[3:8]) for x in os.listdir(d) if x.startswith("anm") and x.endswith(".lzs"))
    p = min(i for i in ids if i < 10000)
    out = {}
    for role, n in (("body", p), ("cut-in", 10000 + p), ("icon", p + 2)):
        if n in ids:
            with open(os.path.join(d, "anm%05d.lzs" % n), "rb") as fh:
                out[role] = load(fh.read()).blocks
    return out


def identity(pack):
    with open(os.path.join(pack, "mod.json"), encoding="utf-8") as fh:
        return json.load(fh).get("source_import", {}).get("identity", {})


def pair(game, pack, name, leases):
    """[(D5 sprite id, evidence)]: char.dat sprites with the import's EN name, else the lease template."""
    out, seen, bankless = [], set(), []
    for r, nm, title, n in game.chars:
        if nm == name and n and n not in seen:
            seen.add(n)
            (out if game.bank(n) else bankless).append((n, f"char.dat record {r} '{nm}' ({title}): same EN name"))
    if not out:
        lease = leases.get(os.path.basename(os.path.normpath(pack)), {})
        why = f"char.dat '{name}' has no sprite bank anm{bankless[0][0]:05d}" if bankless else f"no char.dat '{name}'"
        if lease.get("template"):
            out.append((lease["template"], f"TEMPLATE, not the same character ({why}); lease template"))
    return out


# ------------------------------------------------------------------------------------------------ run
def run(game, packs, out_dir, d2=None, natives=None):
    leases = {}
    if os.path.exists(LEASES):
        with open(LEASES, encoding="utf-8") as fh:
            leases = json.load(fh)["entries"]
    corpus = game.corpus_values()
    results = []
    for pack in packs:
        ident = identity(pack)
        name, folder = ident.get("name", ""), os.path.basename(os.path.normpath(pack))
        mine = pack_banks(pack)
        own = {role: motions(blocks) for role, blocks in mine.items()}
        src = d2.body_blocks(ident["body"]) if d2 and "body" in ident else None
        r = dict(pack=folder, name=name, body=ident.get("body"), pairs=[],
                 novel=novel(values(mine["body"]), corpus, values(src) if src else None))
        if src:
            c = compare(motions(src), own["body"])
            r["source"] = dict(c, fields=by_field(c))
        for n, evidence in ([(n, "given with --native") for n in natives] if natives else pair(game, pack, name, leases)):
            for role, blocks in game.native_sets(n):
                if role in own:
                    c = compare(motions(blocks), own[role])
                    r["pairs"].append(dict(native=n, evidence=evidence, bank=role, **c, fields=by_field(c)))
        results.append(r)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "twin.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1, default=str)
    with open(os.path.join(out_dir, "twin.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown(results))
    return results


def _short(v, n=60):
    s = json.dumps(v, default=str)
    return s if len(s) <= n else s[:n - 3] + "..."


def _table(fields, a="native", b="import"):
    return ["", f"| Field | Motions differing | e.g. motion | {a} | {b} |", "|---|---|---|---|---|"] + \
        [f"| {k} | {n} | {m} | {_short(x)} | {_short(y)} |" for k, n, m, x, y in fields]


def markdown(results):
    pairs = sorted(((r, p) for r in results for p in r["pairs"]), key=lambda rp: -rp[1]["score"])
    L = ["# Imports vs D5's own banks (structure)", "",
         "Score = differing fields per shared motion + native motions the import lacks. "
         "Novel = stored values no D5 bank uses (count in import / in D2 source).", "",
         "| Pack | Name | D5 | Bank | Shared | Native only | Import only | Score | Pairing |",
         "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['pack']} | {r['name']} | {p['native']} | {p['bank']} | {p['shared']} | {len(p['native_only'])} | "
          f"{len(p['import_only'])} | {p['score']} | {p['evidence']} |" for r, p in pairs]
    L += [f"| {r['pack']} | {r['name']} | - | - | | | | | unpaired |" for r in results if not r["pairs"]]
    for r in results:
        L += ["", f"## {r['pack']} {r['name']}"]
        if r["novel"]:
            L += ["", "Novel values: " + "; ".join(f"{k} {v}" for k, v in r["novel"].items())]
        for p in sorted(r["pairs"], key=lambda p: -p["score"]):
            L += ["", f"### vs D5 {p['native']} {p['bank']} (score {p['score']})"]
            if p["native_only"]:
                L.append(f"Native motions the import lacks: {', '.join(map(str, p['native_only']))}  ")
            if p["import_only"]:
                L.append(f"Import-only motions: {', '.join(map(str, p['import_only']))}")
            L += _table(p["fields"])
        if r.get("source"):
            s = r["source"]
            L += ["", f"### vs D2 source anm{r['body']:05d} (score {s['score']})"]
            if s["native_only"]:
                L.append(f"Source motions the import lacks: {', '.join(map(str, s['native_only']))}")
            L += _table(s["fields"], "D2 source", "import")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game", required=True, help="clean D5 folder holding Data/ (never the modded install)")
    ap.add_argument("--d2", help="D2 Data folder (ANM_HI*.dat): adds the import-vs-source comparison")
    ap.add_argument("--pack", action="append", required=True, help="mod folder with files/Anime/ANM_HI_JP.dat/")
    ap.add_argument("--native", type=int, action="append", help="D5 sprite id(s) to compare with instead of pairing")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default=os.path.join(KIT, "cache"))
    a = ap.parse_args(argv)
    results = run(Game(a.game, a.cache), a.pack, a.out, D2Source(a.d2) if a.d2 else None, a.native)
    for r in results:
        best = max((p["score"] for p in r["pairs"] if p["bank"] == "body"), default=None)
        print(f"{r['pack']:18} {r['name']:14} body score {best}  novel fields {len(r['novel'])}"
              + (f"  vs source {r['source']['score']}" if r.get("source") else ""))
    print("wrote", os.path.join(a.out, "twin.md"))


if __name__ == "__main__":
    main()
