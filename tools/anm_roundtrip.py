"""Round-trip and byte-coverage check of d5lib.anm on the game's own animation banks.

For every anmNNNNN.lzs bank in Data/Anime/ANM_HI_*.dat, as the game shipped it:
  decompress -> anm.AnmFile.parse -> to_bytes  and compare with the decompressed original;
  map every byte of the original to a header, table, image or padding region and list the bytes
  nothing claims or that hold non-zero data where padding/reserved zeros are expected.

Original bytes only.  An archive the kit Installer has patched (append mode) still holds every original
member below its recorded vanilla size; its original member directory and first bytes are in the
Installer's backup prefix (state/games/<game>/backups/*.hdr), so members are read through that.
Archives the Installer never touched are read as they are.  Nothing is written to the game folder.

    python tools/anm_roundtrip.py --kit "<installed kit folder holding state/>" --out <dir>
    python tools/anm_roundtrip.py ... --update-baseline     # record the identical banks
Exit status 1 when a bank in the baseline (same original bytes) no longer round-trips, 2 on a corpus error.
"""
import argparse
import glob
import hashlib
import json
import os
import struct
import sys
import time
from concurrent.futures import ProcessPoolExecutor

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)

from d5lib import anm, crypt, lzs, modsys, nispack, util  # noqa: E402

TABLE_NAMES = ["animations", "nodes", "keys", "palette_infos", "texture_infos",
               "cells", "transforms", "pivots", "colors", "params"]


# ---------------------------------------------------------------------------------------- corpus
def original_members(game_dir, state_dir):
    """[(vpath, name, how, path, offset, size, prefix_path, prefix_len)] for every original ANM member.
    how: 'untouched archive' | 'unchanged member' (same place in the patched archive) |
         'original bytes of a replaced member' (the kit appended a new copy; the old bytes are still there)."""
    index = {}
    ip = os.path.join(state_dir, "backups.json")
    if os.path.exists(ip):
        with open(ip, encoding="utf-8") as f:
            index = json.load(f)
    out = []
    for path in sorted(glob.glob(os.path.join(game_dir, "Data", "Anime", "ANM_HI_*.dat"))):
        vpath = "Anime/" + os.path.basename(path)
        rec = index.get(vpath)
        with nispack.NisPack(path) as pk:
            live = {e.name.lower(): (e.offset, e.size) for e in pk.entries}
            entries = [(e.name, e.offset, e.size) for e in pk.entries]
        hp, hlen, limit = None, 0, os.path.getsize(path)
        if rec and rec.get("modified"):
            if rec.get("mode") != "append":
                raise SystemExit(f"{vpath}: installer mode {rec.get('mode')!r} keeps no original members here")
            hp = os.path.join(state_dir, "backups", vpath.replace("/", "__") + ".hdr")
            with open(hp, "rb") as f:
                head = crypt.decode(f.read())
            hlen, limit = len(head), rec["vanilla_size"]
            count = struct.unpack_from("<I", head, 12)[0]
            if 16 + count * nispack.ENTRY_SIZE > hlen:
                raise SystemExit(f"{vpath}: backup prefix {hlen} B is shorter than its own directory")
            entries = []
            for i in range(count):
                name, off, size, _ = struct.unpack_from("<32sIII", head, 16 + i * nispack.ENTRY_SIZE)
                entries.append((name.split(b"\0")[0].decode("ascii", "replace"), off, size))
        for name, off, size in entries:
            if off + size > limit:
                raise SystemExit(f"{vpath}/{name}: original member lies past the original file end")
            how = ("untouched archive" if hp is None else
                   "unchanged member" if live.get(name.lower()) == (off, size) else
                   "original bytes of a replaced member")
            out.append((vpath, name, how, path, off, size, hp, hlen))
    return out


def read_member(path, off, size, hp, hlen):
    raw = b""
    if hp and off < hlen:
        with open(hp, "rb") as f:
            f.seek(off)
            raw = f.read(min(size, hlen - off))
    if len(raw) < size:
        with open(path, "rb") as f:
            f.seek(off + len(raw))
            raw += f.read(size - len(raw))
    # crypt.decode is position independent (byte-wise), so a member can be decoded in pieces
    return crypt.decode(raw)


def prefix_consistency(members, game_dir):
    """Bytes of the backup prefix that the live archive still holds unchanged must be equal (proves the prefix
    is this archive's original bytes, not a copy of a patched file).  Returns {vpath: (compared, equal)}."""
    res = {}
    for vpath, _, _, path, _, _, hp, hlen in members:
        if not hp or vpath in res:
            continue
        with nispack.NisPack(path) as pk:
            live_dir_end = 16 + len(pk.entries) * nispack.ENTRY_SIZE
        with open(hp, "rb") as f:
            pre = f.read()
        with open(path, "rb") as f:
            f.seek(live_dir_end)
            cur = f.read(hlen - live_dir_end)
        res[vpath] = {"prefix_bytes": hlen, "live_directory_end": live_dir_end,
                      "compared": len(cur), "equal": cur == pre[live_dir_end:]}
    return res


# ---------------------------------------------------------------------------------------- regions
def regions(f, data):
    """[(start, end, label, kind)] for the original bytes, from the parsed file and its raw headers.
    kind: header | reserved (must be zero) | table | image | pad (alignment, should be zero) | trailing."""
    R = [(0, 0x14, "file header", "header"), (0x14, 0x20, "file header +0x14", "reserved")]
    pos = anm.FILE_HEADER_SIZE
    for bi, b in enumerate(f.blocks):
        offs, size = b.layout()
        R.append((pos, pos + 0x1A, f"block {bi} header", "header"))
        R.append((pos + 0x1A, pos + 0x1C, f"block {bi} header count slot 10", "reserved"))
        R.append((pos + 0x1C, pos + 0x44, f"block {bi} header offsets", "header"))
        for t, (o, rows, sz) in enumerate(zip(offs, b.tables(), anm.TABLE_SIZES)):
            if rows:
                R.append((pos + o, pos + o + len(rows) * sz, f"block {bi} table {t} {TABLE_NAMES[t]}", "table"))
        end = offs[9] + len(b.params) * 4
        if end < size:
            R.append((pos + end, pos + size, f"block {bi} tail padding", "pad"))
        pos += size
    imgs = f.textures + f.palettes
    base = struct.unpack_from("<I", data, 0)[0] + 0x10
    for i in range(len(imgs)):
        h = pos + i * anm.IMG_HEADER_SIZE
        R.append((h, h + 4, f"image {i} header fmt", "header"))
        R.append((h + 4, h + 16, f"image {i} header", "header"))
    for i, im in enumerate(imgs):
        off = base + struct.unpack_from("<I", data, pos + i * anm.IMG_HEADER_SIZE + 12)[0]
        kind = "texture" if i < len(f.textures) else "palette"
        R.append((off, off + len(im.data), f"image {i} ({kind}) data", "image"))
        if im.pad:
            R.append((off + len(im.data), off + len(im.data) + len(im.pad), f"image {i} alignment padding", "pad"))
    if f.trailing:
        R.append((len(data) - len(f.trailing), len(data), "after image data", "trailing"))
    R.sort()
    return R


def coverage(R, data):
    """bytes per group + every unexplained range.  A gap no region claims, a region overlapping another,
    non-zero padding / reserved bytes and trailing bytes are unexplained."""
    groups = {"content": 0, "known header": 0, "alignment padding": 0, "unexplained": 0}
    unexplained = []
    pos = 0
    for s, e, label, kind in R:
        if s > pos:
            unexplained.append((pos, s, "claimed by nothing"))
        elif s < pos:
            unexplained.append((s, min(e, pos), "claimed twice (%s)" % label))
        pos = max(pos, e)
        n = e - s
        zero = not any(data[s:e])
        if kind in ("table", "image"):
            groups["content"] += n
        elif kind == "header" or (kind == "reserved" and zero):
            groups["known header"] += n
        elif kind == "pad" and zero:
            groups["alignment padding"] += n
        else:
            unexplained.append((s, e, label + (" (non-zero)" if kind != "trailing" else "")))
    if pos < len(data):
        unexplained.append((pos, len(data), "claimed by nothing"))
    groups["unexplained"] = sum(e - s for s, e, _ in unexplained)
    return groups, [{"offset": s, "length": e - s, "where": w, "bytes": data[s:min(e, s + 16)].hex()}
                    for s, e, w in unexplained]


def region_of(R, off):
    for s, e, label, _ in R:
        if s <= off < e:
            return label
    return "unclaimed"


# ---------------------------------------------------------------------------------------- one bank
def check(job):
    vpath, name, how, path, off, size, hp, hlen = job
    r = {"bank": f"{vpath}/{name}", "source": how}
    try:
        packed = read_member(path, off, size, hp, hlen)
        ext, usize, csize, _ = struct.unpack_from("<4sIII", packed, 0)
        data = lzs.decompress(packed)
        if len(data) != usize or csize > size:
            raise ValueError(f"LZS header says {usize} B / {csize} B, got {len(data)} B / entry {size} B")
    except Exception as exc:  # a bad original member is reported, not fatal
        r.update(status="unreadable", reason=str(exc))
        return r
    r.update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    try:
        f = anm.AnmFile.parse(data)
    except Exception as exc:
        r.update(status="parse error", reason=str(exc))
        return r
    r["blocks"] = len(f.blocks)
    R = regions(f, data)
    r["coverage"], r["unexplained"] = coverage(R, data)
    out = f.to_bytes()
    if out == data:
        r["status"] = "identical"
        return r
    n = min(len(out), len(data))
    first = next((i for i in range(n) if out[i] != data[i]), n)
    r.update(status="differs", first_diff=first, region=region_of(R, first),
             out_size=len(out), original=data[first:first + 8].hex(), written=out[first:first + 8].hex(),
             same_without_virtual_offset_fix=anm.AnmFile.parse(data).to_bytes(False) == data)
    return r


# ---------------------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game", default=util.GAME, help="game folder (read only)")
    ap.add_argument("--kit", default=KIT, help="kit folder whose state/ holds the Installer backups of --game")
    ap.add_argument("--out", help="folder for results.json (per bank) and summary.json")
    ap.add_argument("--baseline", default=os.path.join(KIT, "cache", "anm_roundtrip_baseline.json"))
    ap.add_argument("--update-baseline", action="store_true", help="write the identical banks to --baseline")
    ap.add_argument("--only", help="check only banks whose 'archive/member' contains this text")
    ap.add_argument("--jobs", type=int, default=max(1, min(6, (os.cpu_count() or 2) - 2)))
    a = ap.parse_args(argv)

    t0 = time.time()
    state = modsys.game_state_dir(a.game, a.kit)
    members = original_members(a.game, state)
    prefix = prefix_consistency(members, a.game)
    if a.only:
        members = [m for m in members if a.only.lower() in f"{m[0]}/{m[1]}".lower()]
    members.sort(key=lambda m: -m[5])           # biggest first: anm_resident would otherwise finish last
    with ProcessPoolExecutor(a.jobs) as ex:
        results = sorted(ex.map(check, members), key=lambda r: r["bank"])

    by = {}
    for r in results:
        by.setdefault(r["status"], []).append(r)
    unexpl = [r for r in results if r.get("unexplained")]
    summary = {
        "game": a.game, "state": state, "backup_prefix_check": prefix,
        "total": len(results), "unique_contents": len({r.get("sha256") for r in results if "sha256" in r}),
        "by_status": {k: len(v) for k, v in by.items()},
        "by_source": {s: sum(1 for r in results if r["source"] == s) for s in sorted({r["source"] for r in results})},
        "coverage_bytes": {g: sum(r.get("coverage", {}).get(g, 0) for r in results)
                           for g in ("content", "known header", "alignment padding", "unexplained")},
        "banks_with_unexplained": len(unexpl),
        "seconds": round(time.time() - t0, 1),
    }

    print(f"{summary['total']} banks ({summary['unique_contents']} distinct), {summary['seconds']} s")
    for k, v in summary["by_status"].items():
        print(f"  {k}: {v}")
    for k, v in summary["by_source"].items():
        print(f"  source {k}: {v}")
    for vp, p in prefix.items():
        print(f"  backup prefix {vp}: {p['compared']} B still unchanged in the live file, equal={p['equal']}")
    for r in by.get("differs", []):
        print(f"  DIFF {r['bank']} at {r['first_diff']:#x} in {r['region']}")
    for r in by.get("parse error", []) + by.get("unreadable", []):
        print(f"  {r['status'].upper()} {r['bank']}: {r['reason']}")
    print("  coverage bytes:", summary["coverage_bytes"])
    for r in unexpl:
        u = r["unexplained"]
        print(f"  unexplained {r['bank']}: {len(u)} ranges, {r['coverage']['unexplained']} B, first at "
              f"{u[0]['offset']:#x} {u[0]['where']}")

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "results.json"), "w") as f:
            json.dump(results, f, indent=1)
        with open(os.path.join(a.out, "summary.json"), "w") as f:
            json.dump(summary, f, indent=1)

    # baseline: {bank: sha256 of the decompressed original}; a regression is the same bytes no longer identical
    base = {}
    if os.path.exists(a.baseline):
        with open(a.baseline) as f:
            base = json.load(f)
    now = {r["bank"]: r for r in results}
    bad = [k for k, sha in base.items() if k in now and now[k].get("sha256") == sha and now[k]["status"] != "identical"]
    changed = [k for k, sha in base.items() if k in now and now[k].get("sha256") != sha]
    for k in bad:
        print(f"REGRESSION {k}: in the baseline, now {now[k]['status']}")
    if changed:
        print(f"note: {len(changed)} baseline banks have different original bytes now (not compared)")
    if a.update_baseline:
        os.makedirs(os.path.dirname(os.path.abspath(a.baseline)), exist_ok=True)
        keep = {k: v for k, v in base.items() if k not in now}       # --only runs keep the rest
        keep.update({r["bank"]: r["sha256"] for r in results if r["status"] == "identical"})
        with open(a.baseline, "w") as f:
            json.dump(dict(sorted(keep.items())), f, indent=0)
        print(f"baseline: {len(keep)} identical banks -> {a.baseline}")
    if bad:
        return 1
    if by.get("unreadable"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
