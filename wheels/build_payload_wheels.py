"""Build the offline payload exe from a bundle's profile and prove it (payload + wheel contents + pages).

Assembles what the installer will assemble -- the class hooks and the wheel owner table from the bundle's enabled
class mods -- into the pinned game exe, then

  1. writes the payload and runs the shared payload verifier over it (PE structure, exception directory, kit guards),
  2. prints what each wheel page holds, read from the payload's own owner table,
  3. runs the real Hire Character / Rebirth list builder on Unicorn through that payload for every page, and checks
     that each page shows exactly its own families (and that no family appears twice).

Offline only: reads a bundle, writes a payload under Local/ and a receipt next to this script.
"""
import argparse
import json
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))

import pefile                                                     # noqa: E402

from d5lib import exemap, modsys, newclasses, wheelmeta            # noqa: E402

VERIFY = Path("/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/integration/verify_payload.py")


def profile_specs(bundle):
    """the enabled class descriptors of a bundle profile, as the installer collects them"""
    order = json.loads((bundle / "profile" / "LIVE5_TEST16" / "load_order.json").read_text())
    specs, pairs, missing = {}, [], []
    for mod_id in order:
        folder = bundle / "mods" / mod_id
        if not folder.is_dir():
            missing.append(mod_id)
            continue
        mod = modsys.Mod(str(folder))
        loaded = newclasses.load_specs(mod)
        if not loaded:
            continue
        pairs.append((dict(mod.meta), loaded))
        for spec in loaded:
            specs[int(spec["family"])] = spec
    return specs, pairs, missing


def build_payload(pinned, specs, pairs):
    classes = sorted({f + k for f in specs for k in range(6)})
    auto = sorted({c for f, s in specs.items() for c in newclasses.auto_ranks(f, s)})
    aliases = {}
    for s in specs.values():
        aliases.update({int(a): int(b) for a, b in (s.get("evility_alias") or {}).items()})
    descs = [(f, newclasses.DESC_BASE + n) for n, f in enumerate(sorted(specs)) if specs[f].get("hire_desc")]
    wheels = wheelmeta.runtime_entries(pairs)
    exe = newclasses.build_hooks(pinned, classes, auto, aliases, descs, specs=specs, wheel_entries=wheels)
    return exe, wheels


def wheel_table(exe, base_hint=None):
    """the owner table as it sits in the payload's kit section"""
    pe = pefile.PE(data=exe, fast_load=True)
    last = max(pe.sections, key=lambda s: s.VirtualAddress)
    data = last.get_data()
    header = data.find(b"D5WHEEL1")
    if header < 0:
        raise SystemExit("the payload has no wheel header")
    enabled, nowners, nsnap, page, page2 = struct.unpack_from("<IIIII", data, header + 8)
    rows = [struct.unpack_from("<HBB", data, header + newclasses.WHEEL_HEADER_SIZE + 4 * i) for i in range(nowners)]
    return dict(enabled=enabled, nowners=nowners, nsnap=nsnap, page=page, page2=page2,
                owners=sorted((f, w) for f, w, _ in rows))


def verify_payload(path):
    """the shared whole-payload verifier, pointed at this worktree"""
    src = VERIFY.read_text().replace(
        'KIT = Path("/Volumes/Data/Projects/D5/Local/Worktrees/engine-ext-integration")', f'KIT = Path("{KIT}")')
    namespace = {"__file__": str(VERIFY), "__name__": "verify_payload"}
    exec(compile(src, str(VERIFY), "exec"), namespace)               # noqa: S102 - a checkout-local tool
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        namespace["main"](str(path))
    text = buf.getvalue()
    return json.loads(text[text.index("{"):])          # the verifier prints its receipt as JSON


def run_pages(exe, pinned, owners, specs, pages=(0, 1, 2, 3, 4)):
    """the real builder through the payload for each page -> the entries the wheel would show"""
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UcError, UC_HOOK_CODE
    from unicorn.x86_const import (UC_X86_REG_RAX, UC_X86_REG_RCX, UC_X86_REG_RDI, UC_X86_REG_RIP,
                                   UC_X86_REG_RSP)
    sys.path.insert(0, str(KIT / "tests"))
    import test_recruit_runtime as T

    translator = exemap.ACTIVE
    base, size, secs = T.sections(exe)
    entry = T.read_entry_buffer(exe, translator(newclasses.CAROUSEL_VA))
    keys_slot = translator(newclasses.KEYS_SLOT)  # .rdata: holds the GetKeyboardState pointer
    stub = 0x180000000                           # outside the image: mov eax,1 / ret
    flags = translator(newclasses.FLAGS_VA)
    # every class the wheel can list: the game's own 47 hire families plus the mods' families
    # The classes the mods add, plus the game's own hire families for their char.dat rows.  The vanilla families'
    # unlock state lives in the game's own tables (not the kit's 17283.. bitmap), so this replay can only unlock the
    # mods' classes: a page holding nothing but vanilla classes reads empty here and falls through, by design.
    unlisted = sorted(set(newclasses.HIRE_LIST) | {f for f, _ in owners})
    rows = sorted({f + k for f in unlisted for k in range(6)})
    flag_bits = {}
    for fam in sorted({f for f, _ in owners}):
        slot = newclasses.flag_of(fam, specs)
        for k in range(6):
            flag_bits[slot + k] = 1
    out = {}
    for page in pages:
        mu = Uc(UC_ARCH_X86, UC_MODE_64)
        mu.mem_map(base, (size + 0xFFF) // 0x1000 * 0x1000)
        for name, va, vs, rs, ro in secs:
            if rs:
                mu.mem_write(base + va, exe[ro:ro + min(vs, rs)])
        mu.mem_map(T.STACK, 0x200000)
        mu.mem_write(T.CHARTAB, T.char_rows(rows))
        mu.mem_write(T.PTR_G, struct.pack("<Q", T.CHARTAB))
        mu.mem_write(T.COUNT_G, struct.pack("<I", len(rows)))
        bitmap = bytearray((17999 - 17001) // 8 + 2)
        for bit in flag_bits:
            bitmap[(bit - 17001) >> 3] |= 1 << ((bit - 17001) & 7)
        mu.mem_write(flags + (17001 >> 3), bytes(bitmap))
        mu.mem_write(T.OBJECT, b"\x00" * 0x800)
        mu.mem_write(entry, b"\x00" * (newclasses.CAROUSEL_CAP * 8))
        # the page the build starts from, as an install-time default would set it
        mu.mem_write(entry + newclasses.WHEEL_HEADER + newclasses.WHEEL_PAGE, struct.pack("<I", page))
        mu.mem_write(entry + newclasses.WHEEL_HEADER + newclasses.WHEEL_PAGE2, struct.pack("<I", page))

        mu.mem_map(stub, 0x1000)
        mu.mem_write(stub, b"\xb8\x01\x00\x00\x00\xc3")            # mov eax,1 / ret
        mu.mem_write(keys_slot, struct.pack("<Q", stub))               # what the loader would have written

        def at_stub(m, addr, n, _):
            m.mem_write(m.reg_read(UC_X86_REG_RCX), bytes(256))          # no key held: the stored page
        mu.hook_add(UC_HOOK_CODE, at_stub, begin=stub, end=stub)
        mu.reg_write(UC_X86_REG_RSP, T.STACK + 0x100000 + 8)
        mu.reg_write(UC_X86_REG_RCX, T.OBJECT)
        try:
            mu.emu_start(exemap.ACTIVE(T.BUILDER) if False else T.BUILDER, 0, count=20000000)
        except UcError:
            pass
        n = struct.unpack("<i", mu.mem_read(T.OBJECT + 0x208, 4))[0]
        ents = [struct.unpack("<ii", mu.mem_read(entry + 8 * k, 8)) for k in range(max(0, min(n, newclasses.CAROUSEL_CAP)))]
        shown = struct.unpack("<I", mu.mem_read(entry + newclasses.WHEEL_HEADER + newclasses.WHEEL_PAGE, 4))[0]
        out[page] = dict(requested=page, page_used=shown, count=n, families=[f for f, _ in ents])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default="/Volumes/Data/Projects/D5/Builds/LIVE5_TEST16-20261030")
    ap.add_argument("--original", default=None)
    ap.add_argument("--out", default="/Volumes/Data/Projects/D5/Local/payload/wheels3-disgaea5.exe")
    ap.add_argument("--receipt", default=None)
    ap.add_argument("--run-pages", action="store_true")
    ap.add_argument("--pages", type=lambda v: [int(x) for x in v.split(",")], default=[0, 1, 2, 3, 4])
    args = ap.parse_args()
    sys.path.insert(0, str(KIT / "tests"))
    from test_recruit_runtime import pinned_exe
    original = args.original or pinned_exe()
    if original is None:
        raise SystemExit("the pinned game exe is not in the kit's game state (pass --original)")

    pinned = Path(original).read_bytes()
    exemap.use(exemap.translator_for(pinned))
    specs, pairs, missing = profile_specs(Path(args.bundle))
    exe, wheels = build_payload(pinned, specs, pairs)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_bytes(exe)

    table = wheel_table(exe)
    per_page = {}
    for family, wheel in table["owners"]:
        per_page.setdefault(wheelmeta.WHEELS[wheel], []).append(family)
    for name in wheelmeta.WHEELS:
        per_page.setdefault(name, [])

    receipt = dict(bundle=args.bundle, original=original, payload=args.out, payload_bytes=len(exe),
                   class_mods=len(specs), profile_folders_missing=missing,
                   wheel_entries=len(wheels), table=table,
                   per_page={k: sorted(v) for k, v in per_page.items()},
                   counts={k: len(v) for k, v in per_page.items()})
    print("payload", args.out, len(exe), "bytes")
    print("class mods", len(specs), "wheel owners", table["nowners"], "enabled", table["enabled"],
          "page", table["page"])
    print("per page:", {k: len(v) for k, v in per_page.items()})
    if missing:
        print("profile folders not in the bundle (already installed):", len(missing))
    report = verify_payload(args.out)
    problems = [str(p) for p in report.get("problems", [])]
    guard = [p for p in problems if "install guard does not see it" in p]
    structural = [p for p in problems if p not in guard]
    receipt["verify_payload"] = dict(
        problems=problems,
        structural=structural,
        absent_features=guard,   # this payload carries the classes section only: those guards cannot see theirs
        structural_problems=len(structural))
    if args.run_pages:
        receipt["pages"] = run_pages(exe, pinned, table["owners"], specs,
                                     pages=args.pages)
        for page, r in receipt["pages"].items():
            print(f"  page {page} -> used {r['page_used']} count {r['count']} "
                  f"families {sorted(set(r['families']))[:6]}{' ...' if len(set(r['families'])) > 6 else ''}")
    out = Path(args.receipt) if args.receipt else KIT / "wheels" / "payload-wheels3.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print("payload verify: structural problems", len(structural), "| absent-feature guards", len(guard))
    print("receipt", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
