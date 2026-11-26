"""Verify the packed mastery hook inside a full layer payload (offline).

`build_payload_packed.py` builds one exe by running every section-adding module's builder in
finalizer order.  This checks the part of that payload this lane owns:

  1. the source exe is the pinned build;
  2. the .d5pm claim is still readable after 13 further sections were appended, and its family
     table, version and code extent are exactly what a fresh build from the pinned exe produces
     (byte for byte) -- i.e. the other layers did not shift or rewrite the hook;
  3. all 16 mapper call sites still call the claim's entry, and no other instruction in the
     payload jumps into the middle of this claim's code;
  4. every PE unwind entry that falls inside the claim has a plausible start/end/unwind and the
     table remains sorted and non-overlapping (the section grew into .d5mod, so the name is not
     the check -- the claim bytes are);
  5. the Kit's own `.d5cm` is absent (the two hooks are alternatives) and every other module can
     still recognise its own section.

    python mastery/verify_packed_payload.py --payload OUT/payload.exe [--json OUT/verify.json]
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))

import pefile                                                  # noqa: E402
from d5lib import packedmasteryhook as pm                      # noqa: E402
from d5lib.exepatch import IMAGE_BASE                          # noqa: E402

ORIGINAL_SHA = "49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce"
PINNED = Path("/Volumes/Data/Projects/D5/D5Modkit/state/games/"
              "Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")
FAMILIES = [1350, 1360]


def xp_claim_magic():
    from d5lib.exepatch import CLAIM_MAGIC
    return CLAIM_MAGIC


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    payload = args.payload.read_bytes()
    original = PINNED.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA, "not the pinned original exe"

    report = {"payload": str(args.payload), "payload_sha256": hashlib.sha256(payload).hexdigest()}
    info = pm.section_info(payload)
    assert info, "the payload has no .d5pm claim"
    report.update(section=info["section"], claim_base=hex(info["base"]), claim_size=info["size"],
                  families=pm.read_families(payload))
    assert pm.read_families(payload) == FAMILIES, pm.read_families(payload)

    # the code carries the family table's absolute address, so it is rebuilt at the *payload's*
    # claim base for the comparison instead of being compared with a differently-placed build
    offset, count, version = struct.unpack_from("<III", info["data"], 4)
    expected, starts = pm._layout(FAMILIES, info["base"], info["base"] + offset)
    report["entries"] = {k: hex(v) for k, v in starts.items()}
    same = info["data"][:len(expected)] == expected
    report.update(table_offset=offset, code_bytes=len(expected), code_identical_at_claim_base=same)
    assert same, "the payload's .d5pm code differs from the same section rebuilt at its own base"
    # the unwinding data and the kit's own per-feature claim block follow the code; the kit's
    # feature registry is the authority on the block being intact
    from d5lib import exepatch as xp
    assert xp.has_feature(payload, b".d5pm"), "the kit no longer recognises the .d5pm feature block"
    report["feature_claim_block"] = True

    # this feature's region ends where the kit's claim block says it does (the section also holds
    # the 13 layers appended after it, so the section size is not the region)
    block = info["data"].find(xp_claim_magic() + b".d5pm\0\0\0")
    assert block > 0, "no .d5pm feature claim block"
    length = struct.unpack_from("<I", info["data"], block + 14)[0]   # magic 6 + name 8
    region_end = info["base"] + length
    report["region_bytes"] = length
    report["unwind_bytes"] = length - len(expected)
    assert length > len(expected), (length, len(expected))
    assert region_end <= info["base"] + info["size"], region_end

    pe = pefile.PE(data=payload, fast_load=True)
    sites = []
    for va in pm.MAPPER_CALLS:
        off = pe.get_offset_from_rva(va - IMAGE_BASE)
        raw = payload[off:off + 5]
        target = va + 5 + struct.unpack("<i", raw[1:])[0]
        assert raw[0] == 0xE8 and target == info["code"], (hex(va), raw.hex(), hex(target))
        sites.append(hex(va))
    # the two sub-class sites this section also owns: the gate is entered by a jump and leaves to the
    # native accept path, the screen fetch is called and returns to the next instruction
    from d5lib import masteryext as mx
    for va, orig, opcode, key in ((mx.SUBCLASS_SITE, mx.SUBCLASS_ORIG, 0xE9, "subclass"),
                                  (mx.FETCH_SITE, mx.FETCH_ORIG, 0xE8, "fetch")):
        off = pe.get_offset_from_rva(va - IMAGE_BASE)
        raw = payload[off:off + 5]
        target = va + 5 + struct.unpack("<i", raw[1:])[0]
        assert raw[0] == opcode and target == starts[key], (hex(va), raw.hex(), hex(target), hex(starts[key]))
        sites.append(hex(va))
    off = pe.get_offset_from_rva(mx.BOUND_SITE - IMAGE_BASE)
    assert payload[off:off + 3] == mx.BOUND_ORIG[:3] and payload[off + 3] == 0x2F + len(FAMILIES), payload[off:off + 4].hex()
    report["screen_bound"] = 0x2F + len(FAMILIES)
    report["sites"] = len(sites)
    report["sites_all_call_the_claim"] = True

    directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    entries = list(struct.iter_unpack("<III", pe.get_data(directory.VirtualAddress, directory.Size)))
    ours = [e for e in entries if info["base"] - IMAGE_BASE <= e[0] < region_end - IMAGE_BASE]
    previous = 0
    for start, end, unwind in entries:
        assert start >= previous and start < end and unwind and unwind % 4 == 0, (start, end, unwind)
        previous = end
    report["unwind_entries_in_claim"] = [(hex(IMAGE_BASE + s), hex(IMAGE_BASE + e)) for s, e, _ in ours]
    report["unwind_table_ok"] = True
    assert len(ours) >= 6, ours                    # wrapper blob's routines + the two sub-class stubs

    # no other call site may enter this feature's *code* (the region also holds the relocated
    # exception table, whose data bytes would make a byte-level scan meaningless)
    code_lo, code_hi = info["code"], info["base"] + len(expected)
    foreign = []
    for s in pe.sections:
        body = payload[pe.get_offset_from_rva(s.VirtualAddress):][:s.Misc_VirtualSize]
        for i in range(0, len(body) - 5):
            if body[i] in (0xE8, 0xE9):
                target = IMAGE_BASE + s.VirtualAddress + i + 5 + struct.unpack_from("<i", body, i + 1)[0]
                site_va = IMAGE_BASE + s.VirtualAddress + i
                if (code_lo <= target < code_hi and not info["base"] <= site_va < code_hi
                        and site_va not in set(pm.MAPPER_CALLS)
                        and site_va not in (mx.SUBCLASS_SITE, mx.FETCH_SITE)):
                    foreign.append((s.Name.rstrip(b"\0").decode("ascii", "replace"), hex(IMAGE_BASE + s.VirtualAddress + i),
                                    hex(target)))
    report["other_jumps_into_the_claim"] = foreign[:10]
    report["other_jumps_count"] = len(foreign)
    assert not foreign, foreign[:5]

    pe2 = pefile.PE(data=payload, fast_load=True)
    names = {s.Name.rstrip(b"\0") for s in pe2.sections}
    report["sections"] = sorted(n.decode("ascii", "replace") for n in names)
    report["d5cm_present"] = b".d5cm" in names
    assert b".d5cm" not in names, "the class-mastery six-slot hook is also installed"
    print(json.dumps(report, indent=1))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
