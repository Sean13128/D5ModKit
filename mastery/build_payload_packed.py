"""Offline section-coexistence payload for the D5ModKit engine extensions.

Builds one exe from the pinned vanilla exe by running every section-adding
module's own builder in modsys finalizer order, then reports the section table,
the PE exception directory, and whether each module can still recognise its own
section.  Nothing here reads or writes the game folder, the installed kit, or
any mods directory: the only input is the pinned exe backup.

    python build_payload.py <out-dir>

Writes <out-dir>/payload.exe and <out-dir>/payload-report.json.
"""
import hashlib
import os
import json
import struct
import sys
from pathlib import Path

KIT = Path(os.environ.get("D5_KIT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))

PINNED = Path("/Volumes/Data/Projects/D5/D5Modkit/state/games/"
              "Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")

import pefile  # noqa: E402

from d5lib import (customcolors, enemyitems, evility, eventpose, exepatch, exemap,  # noqa: E402
                   identitypatch, masteryext, packedmasteryhook, modsys, newclasses, questpatch,
                   runtime, scalepatch, spellgrowth, unlockpatch, weaponlevels, fxpool)


def sections(exe):
    pe = pefile.PE(data=exe, fast_load=True)
    out = []
    for s in pe.sections:
        out.append(dict(name=s.Name.rstrip(b"\0").decode("ascii", "replace"),
                        va=s.VirtualAddress, vsize=s.Misc_VirtualSize,
                        raw=s.PointerToRawData, rawsize=s.SizeOfRawData,
                        chars=hex(s.Characteristics)))
    return out, pe


def report(exe):
    secs, pe = sections(exe)
    d = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    entries = []
    if d.Size:
        try:
            raw = pe.get_data(d.VirtualAddress, d.Size)
            entries = [tuple(v) for v in struct.iter_unpack("<III", raw)]
        except Exception as exc:                                  # noqa: BLE001
            entries = [("ERROR", str(exc), 0)]
    last = max(secs, key=lambda s: s["va"])
    header_room = pe.OPTIONAL_HEADER.SizeOfHeaders - (pe.DOS_HEADER.e_lfanew + 4 + 20
                                                     + pe.FILE_HEADER.SizeOfOptionalHeader
                                                     + 40 * pe.FILE_HEADER.NumberOfSections)
    return dict(sections=secs, n_sections=pe.FILE_HEADER.NumberOfSections,
                size_of_image=pe.OPTIONAL_HEADER.SizeOfImage,
                size_of_headers=pe.OPTIONAL_HEADER.SizeOfHeaders,
                section_header_bytes_left=header_room,
                last_section=last["name"],
                last_section_end_rva=last["va"] + max(last["vsize"], last["rawsize"]),
                exception_directory=dict(rva=d.VirtualAddress, size=d.Size, entries=len(entries)),
                exception_entries_ok=_exc_ok(entries, secs),
                exception_unwind_section=_section_of([e[2] for e in entries], secs))


def _section_of(rvas, secs):
    where = {}
    for rva in rvas:
        hit = [s["name"] for s in secs if s["va"] <= rva < s["va"] + max(s["vsize"], s["rawsize"])]
        where[hit[0] if hit else "NONE"] = where.get(hit[0] if hit else "NONE", 0) + 1
    return where


def _exc_ok(entries, secs):
    """every runtime function mapped, sorted, non-overlapping, aligned; a function in a kit section must unwind there"""
    if not entries:
        return None
    def sec_of(rva):
        for s in secs:
            if s["va"] <= rva < s["va"] + max(s["vsize"], s["rawsize"]):
                return s["name"]
        return None
    prev = 0
    for start, end, unwind in entries:
        if start < prev or start >= end or not unwind or unwind % 4:
            return False
        if sec_of(start) is None or sec_of(end - 1) is None or sec_of(unwind) is None:
            return False
        if sec_of(start).startswith(".d5") and sec_of(unwind) != sec_of(start):
            return False
        prev = end
    return True


def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    exe = PINNED.read_bytes()
    tr = exemap.translator_for(exe, log=lambda *a: None)
    exemap.use(tr)
    src_sha = hashlib.sha256(exe).hexdigest()
    modsys.load_handlers(log=lambda *a: None)
    order = [fn.__module__ + "." + fn.__name__ for fn in modsys.ordered_finalizers()]

    baseline = report(exe)
    # a full-section count of the exe after the vanilla-exe-only .d5ly branch (the layer hook that
    # build_outfit_patch would otherwise install inside .d5mod)
    ly = report(exepatch.build_layer_patch(exe, [1270, 1271]))

    steps = []

    def run(label, fn):
        nonlocal exe
        before = report(exe)
        try:
            new = fn(exe)
        except Exception as exc:                                   # noqa: BLE001
            steps.append(dict(step=label, status="error", error=f"{type(exc).__name__}: {exc}"))
            return
        if new is exe or new == exe:
            steps.append(dict(step=label, status="no-change"))
            return
        exe = new
        after = report(exe)
        steps.append(dict(step=label, status="applied",
                          sections_before=before["n_sections"], sections_after=after["n_sections"],
                          grew_last=after["n_sections"] == before["n_sections"],
                          last_section=after["last_section"],
                          exception_directory=after["exception_directory"],
                          exception_entries_ok=after["exception_entries_ok"],
                          header_bytes_left=after["section_header_bytes_left"],
                          bytes=len(exe)))

    # 1. outfits (.d5mod) -- the outfit menu, needs only the vanilla exe
    run("outfits(.d5mod) exepatch.build_outfit_patch",
        lambda e: exepatch.build_outfit_patch(e, [(1, 1270, 0)], 900000, 900001,
                                              own_sprites=[1270, 1271]))
    # 2. event poses (.d5ev) -- the outfit versions of skill event poses
    run("outfits/eventpose(.d5ev)",
        lambda e: eventpose.patch(e, [(1270, 7002, 7002), (1271, 7003, 7003)], log=lambda *a: None))
    # 3. sprite layer (.d5ly) is the same hook build_outfit_patch installs inside .d5mod, for
    #    outfits-less installs; measured separately (below) instead of in the chain.
    # 4. class hooks (.d5cl, writable: the 512-row carousel/entry buffers)
    run("newclasses(.d5cl) build_hooks",
        lambda e: newclasses.build_hooks(e, [1270, 1271, 1275], [1270, 1271], {}))
    # 5a. class mastery (.d5cm, the second unwind section) -- after the class lane's widening.
    #     The packed mapper (.d5pm) redirects the same 16 calls, so the two are alternatives:
    #     build .d5pm here and prove separately that the other order is refused, not half-applied.
    run("packedmasteryhook(.d5pm) build_patch",
        lambda e: packedmasteryhook.build_patch(e, [1350, 1360]))
    # 6. recruit / colour-screen hooks (.d5qr)
    run("questpatch(.d5qr) build_recruit_hook",
        lambda e: questpatch.build_recruit_hook(e, [1270, 1271]))
    # 6. evility writer (.d5el) -- the one section that also carries unwind data
    run("evility(.d5el) build_patch",
        lambda e: evility.build_patch(e, {
            7002: {"family": "potency", "effects": [{"stat": "atk", "value": 30}]},
            7003: {"family": "dealt", "effects": [{"value": 20, "per": "adjacent_ally"}]},
            7004: {"family": "conversion", "effects": [{"stat": "atk", "from": "sp_current", "value": 10}]},
        }))
    # 7. unlocks (.d5ul)
    run("unlockpatch(.d5ul) build_unlock_patch",
        lambda e: unlockpatch.build_unlock_patch(e, [1270, 1271, 1275]))
    # 8. weapon levels (.d5wl)
    run("weaponlevels(.d5wl) build",
        lambda e: weaponlevels.build(e, {1270: [5, 5, 5, 5, 5, 5, 5, 5]}))
    # 9. spell growth (.d5sg)
    run("spellgrowth(.d5sg) build",
        lambda e: spellgrowth.build(e, [1, 4, 9, 16, 25, 40, 60, 80]))
    # 10. enemy item rarity (.d5ei)
    run("enemyitems(.d5ei) build", lambda e: enemyitems.build(e))
    # 11. custom colours (.d5c4)
    run("customcolors(.d5c4) add_hook_section",
        lambda e: exepatch.add_hook_section(
            e, customcolors.SECTION_NAME,
            [(customcolors.EC4_VA, customcolors._ec4_form()[0], customcolors._ec4_src([2001]), 0xE9)]))
    # 12. lazy effect preload (.d5fx)
    run("fxpool(.d5fx) preload_patch", lambda e: fxpool.preload_patch(e, [1, 2, 3]))
    # 13. identity stubs (.d5id)
    run("identitypatch(.d5id) patch", lambda e: identitypatch.patch(e, {9001: 1270}, log=lambda *a: None))
    # 14. sprite scale (.d5sc), humanoid check (.d5hm), script sprite map (.d5ss)
    run("scalepatch(.d5sc) patch", lambda e: scalepatch.patch(e, [10001, 10002], log=lambda *a: None))
    run("scalepatch(.d5hm) humanoid_patch",
        lambda e: scalepatch.humanoid_patch(e, [10001, 10002], log=lambda *a: None))
    run("scalepatch(.d5ss) script_sprite_patch",
        lambda e: scalepatch.script_sprite_patch(e, {1270: 101}, log=lambda *a: None))
    # 15. runtime per-frame DLL hook (.d5auto) -- last: it is what the DLL is loaded from
    run("runtime(.d5auto) build_exe_hook", lambda e: runtime.build_exe_hook(e))

    final = report(exe)
    (out / "payload.exe").write_bytes(exe)

    # which .d5 names does each module's own "already installed" check still see?
    wanted = {".d5mod": exepatch.SECTION_NAME, ".d5ev": eventpose.SECTION, ".d5ly": exepatch.LAYER_SECTION,
              ".d5cm": masteryext.SECTION_NAME, ".d5pm": packedmasteryhook.SECTION_NAME,
              ".d5cl": newclasses.SECTION, ".d5qr": questpatch.SECTION_NAME, ".d5el": evility.SECTION_NAME,
              ".d5ul": unlockpatch.SECTION_NAME, ".d5wl": weaponlevels.SECTION, ".d5sg": spellgrowth.SECTION,
              ".d5ei": enemyitems.SECTION, ".d5c4": customcolors.SECTION_NAME, ".d5fx": fxpool.SECTION,
              ".d5id": identitypatch.SECTION, ".d5sc": scalepatch.SECTION, ".d5auto": runtime.SECTION_NAME}
    visible = {label: exepatch.has_feature(exe, name) for label, name in wanted.items()}
    in_table = {label: any(s["name"] == name.decode() for s in final["sections"])
                for label, name in wanted.items()}
    # every patched site must jump/call into the kit's own section space
    d5 = [(s["va"], s["va"] + max(s["vsize"], s["rawsize"])) for s in final["sections"] if s["name"].startswith(".d5")]
    # the 16 packed-mapper sites are verified by mastery/verify_packed_payload.py, which needs no
    # exemap translation (this script's own site checks go through it)
    sites = [("outfit menu", exepatch.OPEN_VA), ("event pose", eventpose.SITES[0][0]),
             ("carousel", newclasses.CAROUSEL_VA), ("recruit", questpatch.HOOK_VA),
             ("evility wrapr", evility.WRAPPERS[0][2][0]), ("unlock", unlockpatch.SLOTS_VA),
             ("weapon lvl", weaponlevels.SITE_VA), ("spell range", spellgrowth.RANGE_SITE),
             ("enemy item", enemyitems.ID_SITE), ("custom col", customcolors.EC4_VA),
             ("fx preload", fxpool.PRELOAD_CALL_VA), ("runtime", runtime.FRAME_VA),
             ("scale", scalepatch.SITES and 0x1402F1A6F), ("script spr", scalepatch.SS_SITE)]
    checks = []
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    pe2 = pefile.PE(data=exe, fast_load=True)
    for label, va in sites:
        if not va:
            continue
        nva = va
        try:
            if va != evility.WRAPPERS[0][2][0]:      # evility uses the pinned build's own addresses
                nva = exemap.ACTIVE(va)
        except Exception:                                          # noqa: BLE001
            checks.append(dict(site=label, va=hex(va), status="unmapped"))
            continue
        off = pe2.get_offset_from_rva(nva - exepatch.IMAGE_BASE)
        ins = next(md.disasm(exe[off:off + 6], nva, count=1), None)
        if ins is None:
            checks.append(dict(site=label, va=hex(nva), status="undecodable"))
            continue
        target = None
        if ins.mnemonic in ("jmp", "call") and ins.op_str.startswith("0x"):
            target = int(ins.op_str, 16)
        inside = target is not None and any(a <= target - exepatch.IMAGE_BASE < b for a, b in d5)
        checks.append(dict(site=label, va=hex(nva), instruction=f"{ins.mnemonic} {ins.op_str}",
                           target=(hex(target) if target else None), into_kit_section=inside))
    overlap = []
    order = sorted(final["sections"], key=lambda s: s["va"])
    for a, b in zip(order, order[1:]):
        if a["va"] + max(a["vsize"], a["rawsize"]) > b["va"]:
            overlap.append((a["name"], b["name"]))

    ev = evility.section_info(exe)

    # the two mastery hooks redirect the same 16 calls: the other order must be refused, not half-applied
    try:
        packedmasteryhook.build_patch(masteryext.build_patch(PINNED.read_bytes(), [1350, 1360]),
                                      [1350, 1360])
        collision = dict(refused=False)
    except ValueError as exc:
        collision = dict(refused=True, error=str(exc))

    report_doc = dict(source_exe=str(PINNED), collision=collision, source_sha256=src_sha, payload_sha256=hashlib.sha256(exe).hexdigest(),
                      payload_bytes=len(exe), finalizer_order=order, baseline=baseline, steps=steps,
                      final=final, section_names_in_header=visible, section_names_in_table=in_table,
                      evility_section_info={k: v for k, v in (ev or {}).items() if k != "data"},
                      d5ly_alone=ly, site_checks=checks, section_overlap=overlap,
                      size_of_image_covers_last=(final["size_of_image"] >= final["last_section_end_rva"]),
                      exemap=dict(sha1=tr.sha1, source=tr.source, identity=tr.identity))
    (out / "payload-report.json").write_text(json.dumps(report_doc, indent=1, default=str))

    print("source  ", src_sha)
    print("payload ", report_doc["payload_sha256"], len(exe), "bytes")
    print("\nsection table of the final payload:")
    print(f"{'name':10} {'rva':>10} {'vsize':>9} {'rawsize':>9} {'chars':>12}")
    for s in final["sections"]:
        print(f"{s['name']:10} {s['va']:>10x} {s['vsize']:>9} {s['rawsize']:>9} {s['chars']:>12}")
    print("\nsteps:")
    for st in steps:
        print(" ", st["step"], "->", st["status"], st.get("error", ""),
              "" if st["status"] != "applied" else f"(sections {st['sections_before']}->{st['sections_after']}, "
              f"header bytes left {st['header_bytes_left']})")
    print("\nexception directory:", final["exception_directory"])
    print("exception entries ok:", final["exception_entries_ok"],
          " unwind rvas in:", final["exception_unwind_section"])
    print("section names visible to is_patched checks:", visible)
    print("collision with .d5cm refused:", report_doc["collision"])
    print("section names present in the table:", in_table)
    print("evility section_info:", {k: (hex(v) if k in ("base", "code") else v)
                                    for k, v in (ev or {}).items() if k != "data"} if ev else None)
    print("headers:", final["n_sections"], "size_of_headers", final["size_of_headers"],
          "bytes left", final["section_header_bytes_left"],
          "(one more 40-byte header:", "fits" if final["section_header_bytes_left"] >= 40 else "does NOT fit", ")")
    print(".d5ly on the vanilla exe:", [(s["name"], hex(s["va"]), s["vsize"]) for s in ly["sections"] if s["name"].startswith(".d5")])
    print("section overlap:", overlap or "none", " size_of_image covers last:",
          report_doc["size_of_image_covers_last"])
    print("patched sites:")
    for c in checks:
        print("  ", c)


if __name__ == "__main__":
    main()