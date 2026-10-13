"""Developer tool: map every game address the kit uses from the build it was made on (KNOWN) to another build of
disgaea5.exe, with both exes at hand -> d5lib/data/exe_map_<sha1[:12]>.json (shipped; exemap.translator reads it).

    python tools/exe_port.py OLD_EXE NEW_EXE [--report]

Functions are matched exactly by fingerprint (exemap.Exe.fingerprint) where unique; the functions between two exact
matches are paired in order (same count) or by size and instruction similarity; an address inside a changed function
is carried over by aligning the two instruction sequences (difflib).  Data addresses follow the instructions that
reference them.  Every mapping gets a confidence: exact (identical function), aligned (equal instruction run around
it), or none (left out: the feature using it refuses this build)."""
import bisect
import difflib
import hashlib
import json
import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, KIT)
from d5lib import exemap   # noqa: E402


def tokens(ex, start, end):
    """[(offset, size, normalized mnemonic+operands)] of a function"""
    from capstone.x86 import X86_OP_MEM, X86_REG_RIP
    cs = ex._capstone()
    out = []
    for ins in cs.disasm(ex.read(start, end - start), ex.base + start):
        ops = ins.op_str
        if ins.mnemonic.startswith("j") or ins.mnemonic == "call":
            ops = "REL" if ops.startswith("0x") else ops
        elif "rip" in ops:
            ops = "RIPREL"
        else:
            import re
            ops = re.sub(r"0x14[0-9a-f]{7}", "ADDR", ops)
            # [reg + reg*n + table rva] (a switch table): the rva moves between builds
            ops = re.sub(r"(\*\s*\d+\s*\+\s*)0x[0-9a-f]{4,7}\]", r"\1TABLE]", ops)
        out.append((ins.address - ex.base - start, ins.size, ins.mnemonic + " " + ops))
    return out


def rip_targets(ex, start, end):
    """{insn offset: (rip-relative target rva, switch table rva, or call/jmp target rva)}"""
    from capstone.x86 import X86_OP_MEM, X86_OP_IMM, X86_REG_RIP, X86_REG_INVALID
    cs = ex._capstone()
    out = {}
    image = ex.pe.OPTIONAL_HEADER.SizeOfImage
    for ins in cs.disasm(ex.read(start, end - start), ex.base + start):
        o = ins.address - ex.base - start
        for op in ins.operands:
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP:
                out[o] = ins.address + ins.size + op.mem.disp - ex.base
            elif (op.type == X86_OP_MEM and op.mem.index != X86_REG_INVALID and ins.disp_size == 4
                  and 0x1000 <= op.mem.disp < image):
                out[o] = op.mem.disp
            elif op.type == X86_OP_IMM and (ins.mnemonic.startswith("j") or ins.mnemonic == "call") and ins.imm_size == 4:
                out[o] = (op.imm & 0xFFFFFFFFFFFFFFFF) - ex.base
    return out


def main():
    old_p, new_p = sys.argv[1], sys.argv[2]
    od, nd = open(old_p, "rb").read(), open(new_p, "rb").read()
    old, new = exemap.Exe(od), exemap.Exe(nd)
    of, nf = old.functions(), new.functions()
    print(f"functions: old {len(of)}, new {len(nf)}")
    ofp = [old.fingerprint(s, e)[0] for s, e in of]
    nfp = [new.fingerprint(s, e)[0] for s, e in nf]
    oc, nc = {}, {}
    for h in ofp:
        oc[h] = oc.get(h, 0) + 1
    for h in nfp:
        nc[h] = nc.get(h, 0) + 1
    nidx = {}
    for i, h in enumerate(nfp):
        nidx.setdefault(h, []).append(i)
    pair = {}                                            # old function index -> (new index, "exact" / "fuzzy")
    for i, h in enumerate(ofp):
        if oc[h] == 1 and nc.get(h) == 1:
            pair[i] = (nidx[h][0], "exact")
    # keep only anchors in increasing order on both sides (longest increasing run)
    anchors = sorted((i, j) for i, (j, _) in pair.items())
    tails, prev, idxs = [], [None] * len(anchors), []
    for k, (i, j) in enumerate(anchors):
        p = bisect.bisect_left([anchors[t][1] for t in tails], j)
        if p == len(tails):
            tails.append(k)
        else:
            tails[p] = k
        prev[k] = tails[p - 1] if p else None
    k = tails[-1] if tails else None
    keep = []
    while k is not None:
        keep.append(anchors[k])
        k = prev[k]
    keep.reverse()
    pair = {i: (j, "exact") for i, j in keep}
    print(f"exact unique anchors in order: {len(pair)}")
    # identical but not unique functions between anchors: pair in order when they agree
    bounds = [(-1, -1)] + keep + [(len(of), len(nf))]
    fuzzy = 0
    for (a0, b0), (a1, b1) in zip(bounds, bounds[1:]):
        oi = list(range(a0 + 1, a1))
        ni = list(range(b0 + 1, b1))
        if not oi or not ni:
            continue
        # equal fingerprints in order
        sm = difflib.SequenceMatcher(None, [ofp[i] for i in oi], [nfp[j] for j in ni], autojunk=False)
        for blk in sm.get_matching_blocks():
            for t in range(blk.size):
                pair[oi[blk.a + t]] = (ni[blk.b + t], "exact")
        rest_o = [i for i in oi if i not in pair]
        used_n = {pair[i][0] for i in oi if i in pair}
        rest_n = [j for j in ni if j not in used_n]
        if not rest_o or not rest_n:
            continue
        # changed functions: in order, by size similarity
        sm = difflib.SequenceMatcher(None, [round((of[i][1] - of[i][0]) / 16) for i in rest_o],
                                     [round((nf[j][1] - nf[j][0]) / 16) for j in rest_n], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ("equal", "replace") and i2 - i1 == j2 - j1:
                for t in range(i2 - i1):
                    pair[rest_o[i1 + t]] = (rest_n[j1 + t], "fuzzy")
                    fuzzy += 1
    print(f"paired: {len(pair)} of {len(of)} old functions ({fuzzy} changed)")
    # unpaired functions found through their callers: a paired caller's call / jmp, aligned, names the callee's new
    # place (several rounds: newly found functions call others)
    ostart = {s_: i for i, (s_, e_) in enumerate(of)}
    nstart = {s_: j for j, (s_, e_) in enumerate(nf)}
    tok_cache0 = {}

    def tk(ex, f, key):
        if key not in tok_cache0:
            tok_cache0[key] = tokens(ex, *f)
        return tok_cache0[key]
    for rnd in range(4):
        votes = {}
        for i, (j, kind) in list(pair.items()):
            to = rip_targets(old, *of[i])
            calls = {o: t for o, t in to.items() if t in ostart and ostart[t] not in pair}
            if not calls:
                continue
            tn = rip_targets(new, *nf[j])
            if kind == "exact":
                m = {o: o for o in calls}
            else:
                ot, nt = tk(old, of[i], ("o", i)), tk(new, nf[j], ("n", j))
                sm = difflib.SequenceMatcher(None, [t[2] for t in ot], [t[2] for t in nt], autojunk=False)
                m = {}
                for blk in sm.get_matching_blocks():
                    for t in range(blk.size):
                        m[ot[blk.a + t][0]] = nt[blk.b + t][0]
            for o, t in calls.items():
                nt_ = tn.get(m.get(o))
                if nt_ is not None and nt_ in nstart:
                    v = votes.setdefault(ostart[t], {})
                    v[nstart[nt_]] = v.get(nstart[nt_], 0) + 1
        added = 0
        used = {j for j, _ in pair.values()}
        for i, v in votes.items():
            j, n = max(v.items(), key=lambda kv: kv[1])
            if j in used or n * 2 <= sum(v.values()):
                continue
            pair[i] = (j, "exact" if ofp[i] == nfp[j] else "fuzzy")
            used.add(j)
            added += 1
        print(f"  call propagation round {rnd + 1}: {added} more functions")
        if not added:
            break

    ref = exemap.load_reference()
    out, how, missing = {}, {}, []
    tok_cache = {}

    def toks(ex, f, key):
        if key not in tok_cache:
            tok_cache[key] = tokens(ex, *f)
        return tok_cache[key]

    def map_code(rva):
        i = exemap._containing(of, rva)
        if i is None or i not in pair:
            return None, None
        j, kind = pair[i]
        off = rva - of[i][0]
        if kind == "exact":
            return nf[j][0] + off, "exact"
        to = toks(old, of[i], ("o", i))
        tn = toks(new, nf[j], ("n", j))
        sm = difflib.SequenceMatcher(None, [t[2] for t in to], [t[2] for t in tn], autojunk=False)
        offs = [t[0] for t in to]
        k = bisect.bisect_right(offs, off) - 1
        if k < 0:
            return None, None
        within = off - to[k][0]
        for blk in sm.get_matching_blocks():
            if blk.a <= k < blk.a + blk.size:
                # an equal run of at least 3 instructions around the site
                if blk.size >= 3:
                    return nf[j][0] + tn[blk.b + k - blk.a][0] + within, "aligned"
        return None, None
    nimp = {v: k for k, v in new.imports().items()}
    for key, s in ref["sites"].items():
        va = int(key, 16)
        rva = va - exemap.IMAGE_BASE
        if s["kind"] == "import":
            if s["name"] in nimp:
                out[va] = exemap.IMAGE_BASE + nimp[s["name"]]
                how[va] = "import"
            else:
                missing.append(va)
            continue
        if s["kind"] == "code":
            n, kind = map_code(rva)
        else:
            n, kind = None, None
            votes = {}
            for r in s["refs"]:
                h, size, o, delta = r[:4]
                # the referencing function in the old exe (by its fingerprint), then its pair
                for i in range(len(of)):
                    pass
                break
            # data: every old function referencing it (scan pairs' rip targets)
        if n is not None:
            out[va] = exemap.IMAGE_BASE + n
            how[va] = kind
        elif s["kind"] == "code":
            missing.append(va)
    # fallback for code sites still missing: the instruction pattern at the site (masked like the fingerprints),
    # searched in the paired new function, else among new functions of a similar size (function starts)
    def pattern_search(rva):
        i = exemap._containing(of, rva)
        if i is None:
            return None, None
        to = toks(old, of[i], ("o", i))
        offs = [t[0] for t in to]
        off = rva - of[i][0]
        k = bisect.bisect_right(offs, off) - 1
        if k < 0 or to[k][0] != off:
            return None, None
        if k == 0:                                           # a function start: its first instructions
            want = [t[2] for t in to[:12]]
            size = of[i][1] - of[i][0]
            hits = [j for j, (a_, b_) in enumerate(nf) if 0.6 * size <= b_ - a_ <= 1.6 * size + 64
                    and [t[2] for t in toks(new, nf[j], ("n", j))[:len(want)]] == want]
            if len(hits) == 1:
                return nf[hits[0]][0], "pattern"
            return None, None
        lo, hi = max(0, k - 4), min(len(to), k + 6)
        want = [t[2] for t in to[lo:hi]]
        cands = [pair[i][0]] if i in pair else []
        found = []
        for j in cands:
            tn = toks(new, nf[j], ("n", j))
            for q in range(len(tn) - len(want) + 1):
                if [t[2] for t in tn[q:q + len(want)]] == want:
                    found.append(nf[j][0] + tn[q + (k - lo)][0])
        if len(found) == 1:
            return found[0], "pattern"
        return None, None
    still = []
    for va in missing:
        n, kind = pattern_search(va - exemap.IMAGE_BASE)
        if n is not None:
            out[va] = exemap.IMAGE_BASE + n
            how[va] = kind
        else:
            still.append(va)
    missing = still

    # data addresses: rip-relative targets of paired functions, instruction by instruction
    data_sites = {int(k, 16) - exemap.IMAGE_BASE: int(k, 16) for k, s in ref["sites"].items() if s["kind"] == "data"}
    keys = sorted(data_sites)
    # votes: instructions naming the address itself decide; without one, those naming the closest place below it
    # (a field of the same object / table) -- {new va: [count, distance]}
    votes = {va: {} for va in data_sites.values()}
    for i, (j, kind) in pair.items():
        to = rip_targets(old, *of[i])
        if not to:
            continue
        lo = min(to.values())
        hi = max(to.values())
        a = bisect.bisect_left(keys, lo)
        if a >= len(keys) or keys[a] > hi + 0x400:
            continue
        tn = rip_targets(new, *nf[j])
        if kind == "exact":
            pairs_o_n = [(t, tn.get(o)) for o, t in to.items()]
        else:
            ot, nt = toks(old, of[i], ("o", i)), toks(new, nf[j], ("n", j))
            sm = difflib.SequenceMatcher(None, [t[2] for t in ot], [t[2] for t in nt], autojunk=False)
            m = {}
            for blk in sm.get_matching_blocks():
                for t in range(blk.size):
                    m[ot[blk.a + t][0]] = nt[blk.b + t][0]
            pairs_o_n = [(t, tn.get(m.get(o))) for o, t in to.items()]
        for t_old, t_new in pairs_o_n:
            if t_new is None:
                continue
            k = bisect.bisect_right(keys, t_old + 0x400) - 1
            while k >= 0 and keys[k] >= t_old:
                va = data_sites[keys[k]]
                nv = exemap.IMAGE_BASE + t_new + (keys[k] - t_old)
                c = votes[va].setdefault(nv, [0, 1 << 30])
                c[0] += 1
                c[1] = min(c[1], keys[k] - t_old)
                k -= 1
    for va, v in votes.items():
        if v:
            d = min(c[1] for c in v.values())
            near = {nv: c[0] for nv, c in v.items() if c[1] == d}
            nv, n = max(near.items(), key=lambda kv: kv[1])
            out[va] = nv
            how[va] = "data %d/%d" % (n, sum(near.values())) + (f" +{d:#x}" if d else "")
        else:
            missing.append(va)
    sha = hashlib.sha1(nd).hexdigest()
    dest = os.path.join(KIT, "d5lib", "data", f"exe_map_{sha[:12]}.json")
    keep = {}
    if os.path.exists(dest):                         # hand-checked entries survive a new run
        with open(dest) as f:
            old_d = json.load(f)
        keep = {k: old_d[k] for k in ("manual", "manual_notes") if k in old_d}
        missing = [a for a in missing if hex(a) not in keep.get("manual", {})]
    with open(dest, "w") as f:
        json.dump({**keep, "from": exemap.KNOWN_SHA1, "to": sha,
                   "image_end": hex(new.base + new.pe.OPTIONAL_HEADER.SizeOfImage),
                   "map": {hex(a): hex(b) for a, b in sorted(out.items())},
                   "how": {hex(a): h for a, h in sorted(how.items())}, "missing": [hex(a) for a in sorted(missing)]},
                  f, indent=0)
    kinds = {}
    for h in how.values():
        kinds[h.split()[0]] = kinds.get(h.split()[0], 0) + 1
    print(f"mapped {len(out)} of {len(ref['sites'])}: {kinds}; missing {len(missing)} -> {dest}")
    weak = [hex(a) for a, h in how.items() if h.startswith("data") and int(h.split()[1].split("/")[0]) * 2 <= int(h.split()[1].split("/")[1])]
    print("data placed by a neighbour only:", len([a for a, h in how.items() if h.startswith("data") and "+" in h]))
    print("data with split votes:", weak)
    print("missing:", " ".join(hex(a) for a in sorted(missing)))


if __name__ == "__main__":
    main()
