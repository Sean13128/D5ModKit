"""Static hook-site arbitration between the Kit runtime and Overlord (offline).

Two runtimes that both rewrite game code need a table that says, per byte range, who owns it and
what happens where they meet. This builds that table mechanically:

  * Overlord's sites come from **his own source** (`overlord/01_declarations.c`: every
    `<NAME>_RVA 0x...` paired with `<NAME>_STOLEN_LEN n`), so his numbers are never re-typed here;
  * Kit and OLEFFECTS-lane sites come from `kit_sites.json`, whose entries cite the evidence file
    and line they were transcribed from;
  * every site is then read back from the **pinned vanilla executable**, so an address or length
    that does not land on the documented instruction shows up in the output;
  * `--release` also scans the released Overlord DLLs for 4-byte references to each of his RVAs,
    which is the only offline way to tell "the v3.5 WIP source hooks here" from "the v3 release
    binary does too" (weak evidence: candidates, not confirmed dispatches).

Verdicts are fail-closed: `exact-overlap` and `partial-overlap` mean the two runtimes write the
same bytes and no load order can arbitrate them; `same-function` means both patch inside one
function without touching the same bytes (ordering still matters); `disjoint` is the only clean
verdict. `duplicate-effect` is an overlap where both sides implement the *same* effect, which is
not a conflict to arbitrate but a decision to take: content moves to one runtime.

Read-only throughout.
"""
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pefile   # noqa: E402

IMAGE_BASE = 0x140000000
PINNED_SHA256_PREFIX = "49a7530b"
HERE = os.path.dirname(os.path.abspath(__file__))
SITES_FILE = os.path.join(HERE, "kit_sites.json")

# Overlord site name -> the Kit/OLEFFECTS effect it implements (for duplicate-effect verdicts).
EQUIVALENT = {
    "STEAL_ON_KILL_HOOK": "steal_on_kill_percent",
    "SP_DRAIN_HOOK": "sp_drain_per_turn",
    "PERMANENT_REVENGE_TURN_HOOK_1": "permanent_revenge",
    "PERMANENT_REVENGE_TURN_HOOK_2": "permanent_revenge",
    "OVERLOAD_ID_RESOLVER": "block_overload",
    "POWER_HOOK": "power",
    "DEFENSE_POWER_HOOK": "defense_power",
    "MAGIC_RANGE_HOOK": "range",
    "AILMENT_CHANCE_HOOK": "status_chance",
    "HP_REGEN_HOOK": "regen",
    "PREVENT_ALLY_DAMAGE_HOOK": None,
}

_DEFINE = re.compile(r"#define\s+([A-Z0-9_]+)_RVA\s+(0x[0-9A-Fa-f]+)", re.M)
_STOLEN = re.compile(r"#define\s+([A-Z0-9_]+)_STOLEN_LEN\s+(\d+)", re.M)
_INSTALL = re.compile(r"d5_hook_install\(\s*[A-Za-z_0-9]+\s*,\s*(0x[0-9A-Fa-f]+)u?\s*,\s*[A-Za-z_0-9]+\s*,\s*(\d+)u?")

def _length_for(name, lengths):
    """Stolen length for a site name.

    A few declarations share one length define (`PERMANENT_REVENGE_TURN_HOOK_1_RVA` /
    `..._2_RVA` with `..._TURN_HOOK_STOLEN_LEN`), so a missing exact match is retried against the
    name with its trailing index removed. Nothing is guessed: no match means the entry is a
    read-only address and is skipped.
    """
    if name in lengths:
        return lengths[name]
    stem = name.rsplit("_", 1)[0]
    return lengths.get(stem)


EXTRA_FILE = os.path.join(HERE, "overlord_extra_sites.json")


def parse_overlord_sites(declarations_path, source_dir=None):
    """Overlord patch sites from his own WIP sources.

    `01_declarations.c` pairs every `<NAME>_RVA` with `<NAME>_STOLEN_LEN`; other files in the same
    tree install hooks through `d5_hook_install(base, 0xRVA, expected, length, ...)`. Both forms are
    read, so no address is re-typed here. Sites documented in `overlord_extra_sites.json` (those the
    source computes at run time) are added with `source: "documented"` so they are distinguishable.
    """
    root = source_dir or os.path.dirname(os.path.dirname(os.path.abspath(declarations_path)))
    out, seen = [], set()
    files = [declarations_path]
    for base, _dirs, names in os.walk(root):
        for n in sorted(names):
            if n.endswith(".c") or n.endswith(".cpp"):
                p = os.path.join(base, n)
                if p != declarations_path:
                    files.append(p)
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        lengths = {m.group(1): int(m.group(2)) for m in _STOLEN.finditer(text)}
        installed = {int(m.group(1), 16): int(m.group(2)) for m in _INSTALL.finditer(text)}
        for m in _DEFINE.finditer(text):
            name, rva = m.group(1), int(m.group(2), 16)
            length = _length_for(name, lengths)
            if length is None:
                continue                 # a read-only address (a function it calls), not a patch site
            if IMAGE_BASE + rva in seen:
                continue
            seen.add(IMAGE_BASE + rva)
            out.append({"owner": "overlord", "name": name, "kind": "entry", "source": "parsed",
                        "va": IMAGE_BASE + rva, "len": length, "file": os.path.relpath(path, root)})
        for rva, length in installed.items():
            if IMAGE_BASE + rva in seen:
                continue
            seen.add(IMAGE_BASE + rva)
            out.append({"owner": "overlord", "name": f"hook_install@{hex(rva)}", "kind": "entry",
                        "source": "parsed", "va": IMAGE_BASE + rva, "len": length,
                        "file": os.path.relpath(path, root)})
    if os.path.exists(EXTRA_FILE):
        with open(EXTRA_FILE, encoding="utf-8") as fh:
            extra = json.load(fh)
        for s in extra.get("sites") or []:
            va = int(s["va"], 16)
            if va in seen:
                continue
            seen.add(va)
            out.append({"owner": "overlord", "name": s["name"], "kind": "entry", "source": "documented",
                        "va": va, "len": int(s["len"]), "evidence": s.get("evidence", "")})
    return sorted(out, key=lambda s: s["va"])


def load_kit_sites(path=SITES_FILE):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for owner, key in (("kit", "kit"), ("kit-oleffects", "oleffects")):
        for s in data.get(key) or []:
            out.append({"owner": owner, "name": s["name"], "kind": s.get("kind", "call-site"),
                        "va": int(s["va"], 16), "len": int(s["len"]),
                        "evidence": s.get("evidence", "")})
    return sorted(out, key=lambda s: s["va"])


def _functions(pe):
    """[(begin_va, end_va)] from the exception directory (.pdata)."""
    out = []
    try:
        d = pe.OPTIONAL_HEADER.DATA_DIRECTORY[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXCEPTION"]]
    except (AttributeError, IndexError):
        return out
    if not d.VirtualAddress or not d.Size:
        return out
    raw = pe.get_data(d.VirtualAddress, d.Size)
    for i in range(0, len(raw) - 11, 12):
        begin, end, _unwind = struct.unpack_from("<III", raw, i)
        if begin and end > begin:
            out.append((IMAGE_BASE + begin, IMAGE_BASE + end))
    return out


def read_site(pe, va, length):
    """Bytes at a VA, as hex, or None when the range is not inside a section."""
    try:
        off = pe.get_offset_from_rva(va - IMAGE_BASE)
    except pefile.PEFormatError:
        return None
    data = pe.__data__[off:off + length]
    return data.hex() if len(data) == length else None


def _containing(functions, va):
    for begin, end in functions:
        if begin <= va < end:
            return (begin, end)
    return None


def compare(sites):
    """Pairwise overlap verdicts. Pure: works on any list of {owner,name,va,len[,function]}.

    Fail-closed: an intersecting range is `needs-arbitration` unless both sides implement the same
    effect (`duplicate-effect`); ranges that do not intersect but share a `.pdata` function are
    `ordered-interaction` (both patch the function, in different bytes).
    """
    overlaps = []
    for i, a in enumerate(sites):
        for b in sites[i + 1:]:
            if a["owner"] == b["owner"]:
                continue
            a0, a1 = a["va"], a["va"] + a["len"]
            b0, b1 = b["va"], b["va"] + b["len"]
            if a1 <= b0 or b1 <= a0:
                if a.get("function") and a.get("function") == b.get("function"):
                    kind = "same-function"
                else:
                    continue
            elif (a0, a1) == (b0, b1):
                kind = "exact-overlap"
            else:
                kind = "partial-overlap"
            dup = None
            for x, y in ((a, b), (b, a)):
                if x["owner"] == "overlord":
                    mine = EQUIVALENT.get(x["name"])
                    if mine and mine == y["name"]:
                        dup = mine
            overlaps.append({
                "kind": kind, "duplicate_effect": dup,
                "a": {"owner": a["owner"], "name": a["name"], "va": hex(a["va"]), "len": a["len"]},
                "b": {"owner": b["owner"], "name": b["name"], "va": hex(b["va"]), "len": b["len"]},
                "verdict": ("duplicate-effect" if dup else
                            "needs-arbitration" if kind in ("exact-overlap", "partial-overlap")
                            else "ordered-interaction")})
    return overlaps


def ownership(config):
    """who owns each contested site, from the Kit's own policy module (d5lib.overlord_compat).

    Keeping this in one place means the report and the installer can never disagree: `add_hook_section`
    drops exactly the hooks this table gives away, which is why the table is generated, not typed.
    """
    from d5lib import overlord_compat
    sites = overlord_compat.resolve(config)
    return {"config": dict(config), "sites": {hex(va): v for va, v in sites.items()},
            "kit_yields": sorted(hex(va) for va in overlord_compat.yielded_sites(config)),
            "double_apply_rows_off": overlord_compat.double_apply(config),
            "rule": "more capability wins (Sean, 2026-10-30 08:15)",
            "supersedes": overlord_compat.WAS_RULE,
            "changed_by_this_rule": {hex(va): list(v) for va, v in overlord_compat.changed_sites(config).items()},
            "capability": overlord_compat.capability_table(config)}


def arbitrate(exe_path, declarations_path, kit_sites_path=SITES_FILE, release=None):
    pe = pefile.PE(exe_path, fast_load=True)
    functions = _functions(pe)
    sites = load_kit_sites(kit_sites_path) + parse_overlord_sites(declarations_path)
    for s in sites:
        s["bytes"] = read_site(pe, s["va"], s["len"])
        f = _containing(functions, s["va"])
        s["function"] = f
    report = {"exe": os.path.abspath(exe_path), "sites": len(sites), "overlaps": [],
              "verdict_counts": {}, "unreadable_sites": []}
    import hashlib
    with open(exe_path, "rb") as fh:
        report["exe_sha256"] = hashlib.sha256(fh.read()).hexdigest()
    if not report["exe_sha256"].startswith(PINNED_SHA256_PREFIX):
        report["warning"] = (f"executable is not the pinned build (expected sha256 {PINNED_SHA256_PREFIX}…): "
                             f"every site below is only valid for that build")
    for s in sites:
        if s["bytes"] is None:
            report["unreadable_sites"].append({"owner": s["owner"], "name": s["name"], "va": hex(s["va"])})
    report["overlaps"] = compare(sites)
    report["overlap_sites"] = [
        {"owner": s["owner"], "name": s["name"], "va": hex(s["va"]), "len": s["len"],
         "source": s.get("source", "transcribed"), "bytes": s["bytes"],
         "evidence": s.get("evidence") or s.get("file") or ""}
        for s in sites]
    for o in report["overlaps"]:
        report["verdict_counts"][o["verdict"]] = report["verdict_counts"].get(o["verdict"], 0) + 1
    pe.close()
    report["ownership"] = {
        "content-only": ownership({"runtime": False}),
        "overlord-runtime": ownership({"runtime": True}),
        "overlord-runtime+plugins": ownership({"runtime": True, "plugins": True}),
    }
    if release:
        report["release_scan"] = scan_release(release, [s for s in sites if s["owner"] == "overlord"])
    return report


def scan_release(release_dir, overlord_sites):
    """Do the released DLLs reference his WIP hook addresses at all? Candidates, not proof."""
    dlls = []
    for root, _dirs, files in os.walk(release_dir):
        for f in files:
            if f.lower().endswith(".dll"):
                dlls.append(os.path.join(root, f))
    out = {"dlls": [], "sites": {}}
    for path in sorted(dlls):
        with open(path, "rb") as fh:
            data = fh.read()
        out["dlls"].append({"path": os.path.relpath(path, release_dir), "size": len(data)})
    for site in overlord_sites:
        rva = site["va"] - IMAGE_BASE
        needle = struct.pack("<I", rva)
        hits = []
        for d in out["dlls"]:
            with open(os.path.join(release_dir, d["path"]), "rb") as fh:
                blob = fh.read()
            at = blob.find(needle)
            while at >= 0 and len(hits) < 8:
                hits.append({"dll": d["path"], "offset": hex(at)})
                at = blob.find(needle, at + 1)
        out["sites"][site["name"]] = {"rva": hex(rva), "candidates": hits}
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", required=True)
    ap.add_argument("--declarations", required=True)
    ap.add_argument("--release", help="extracted Overlord release root (optional DLL scan)")
    ap.add_argument("--json", help="write the report here")
    a = ap.parse_args(argv)
    report = arbitrate(a.exe, a.declarations, release=a.release)
    print(json.dumps({k: report[k] for k in ("sites", "verdict_counts", "exe_sha256")}, indent=1))
    for o in report["overlaps"]:
        if o["verdict"] != "ordered-interaction":
            print(f"  {o['verdict']:18s} {o['a']['owner']}:{o['a']['name']} "
                  f"vs {o['b']['owner']}:{o['b']['name']}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
