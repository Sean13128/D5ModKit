"""LONGTAIL2 offline proof: Xenolith (DD2 80 "The Artifact", row 26306 = max_hp_reflect 20 + alias to D5's Malicious Reflect 143)
through the pinned game's REAL code: the rider block of FUN_1401ADA40 from the defender's evility-list search (0x1401AE254) to the
call that applies the reflected damage to the attacker (0x1401AE604), with the kit's wrap_maxrefl at the game's own call of
damage_skill_dat (0x1401AE531).  The game's own clamp (below the attacker's current HP, never lethal) and its own float arithmetic run.

<unicorn python> evility/offline_proof_longtail2_xenolith.py [--abi] [--control NAME]
Controls (a deliberately broken build; the proof must then FAIL): mr-rdi, mr-row, mr-holder, mr-always, mr-id, mr-align (needs --abi)

Not covered: the rest of FUN_1401ADA40, that the alias hook puts 143 in the holder's active list (proved by the DRPGSIG2 / DD2EVIL2 alias
proofs, the same hook), a live battle.
"""
import argparse
import hashlib
import struct
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(KIT), str(KIT / "tools"), str(KIT / "evility")]
from d5lib import evility as ev                                  # noqa: E402
import stat_oracle as so                                         # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA        # noqa: E402

SCRATCH = Path("/Volumes/Data/ai-tmp/claude/longtail2")
START, SITE, APPLY = 0x1401AE254, 0x1401AE531, 0x1401AE604
STOPS = {0x1401AE2BB: "none", 0x1401AE612: "none", APPLY: "apply"}
REFLECT, XEN = 143, 26306
ROWS = {
    XEN: {"family": "max_hp_reflect", "effects": [{"value": 20}]},                                        # Xenolith
    24081: {"family": "max_hp_reflect", "effects": [{"value": 20}]},                                      # a second holder row
    24082: {"family": "max_hp_reflect", "effects": [{"value": 50}], "conditions": [{"kind": "attack_skill"}]},
}


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def game_amount(pct, damage):
    """what the game computes for a row percent: trunc(float(pct) / 100.0f * float(damage)), all in float32"""
    return int(f32(f32(f32(pct) / 100.0) * f32(damage)))


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    edits = {
        "mr-rdi": ("    mov qword ptr [rsp + 0x38], rax     // the amount goes into rdi's saved slot: the canonical epilogue's pop hands it to the game\n", ""),
        "mr-row": ("    mov dword ptr [rcx + 0x38], 100     // 100 / 100.0f x amount = amount", "    mov dword ptr [rcx + 0x38], 50"),
        "mr-holder": ("    mov rax, qword ptr [rbx + 0x240]    // the attacker's unit record\n    test rax, rax\n    jz .mr_done\n    mov rax, qword ptr [rax + 0x2cd8]",
                      "    mov rax, qword ptr [r13 + 0x240]    // the attacker's unit record\n    test rax, rax\n    jz .mr_done\n    mov rax, qword ptr [rax + 0x2cd8]"),
        "mr-always": ("    call evil_dmg_sum                   // eax = P percent, 0 for a defender without the row\n    test eax, eax\n    jle .mr_done\n    cdqe",
                      "    call evil_dmg_sum                   // eax = P percent, 0 for a defender without the row\n    cdqe"),
        "mr-id": ("    mov rdi, 0x20000000000              // max_hp_reflect: second-word bit 9", "    mov rdi, 0x10000000000"),
    }
    if control == "mr-align":      # a 0x30 frame: every call inside the wrapper is made with rsp 8 off a 16-byte boundary
        a = text.index("wrap_maxrefl:")
        b = text.index("// D4SIG3: wrap_support", a)
        w = text[a:b].replace("sub rsp, 0x38", "sub rsp, 0x30").replace("add rsp, 0x38", "add rsp, 0x30").replace("[rsp + 0x38]", "[rsp + 0x30]")
        SCRATCH.mkdir(parents=True, exist_ok=True)
        out = SCRATCH / f"d5evil-longtail2-{control}.inc.asm"
        out.write_text(text[:a] + w + text[b:])
        return out
    old, new = edits[control]
    assert text.count(old) == 1, (control, text.count(old))
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f"d5evil-longtail2-{control}.inc.asm"
    out.write_text(text.replace(old, new))
    return out


def emu(exe):
    return so.Emu(exe_path=exe)


def run(e, defender_ids, attacker_ids=(), damage=1000, max_hp=1000, hp=10**6, skill=0, abi=False, section=None):
    """-> (outcome, amount applied to the attacker, rdi seen by the game's cvtsi2ss)"""
    X, mu = e.X, e.mu
    e.brk = e.heap_mark

    def unit(ids, hp_, max_):
        u = bytearray(0x4800)
        ids = sorted(ids)
        struct.pack_into("<i", u, 0x3030, len(ids))
        for i, v in enumerate(ids):
            struct.pack_into("<i", u, 0x2F30 + 4 * i, v)
        struct.pack_into("<I", u, 0x4348, 0x28A)           # no stat record: nothing here reads one
        struct.pack_into("<q", u, 0x2CC8, hp_)             # current HP
        struct.pack_into("<q", u, 0x2CD8, max_)            # max HP
        return e.alloc(u)

    def rec(u):
        r = bytearray(4704)
        struct.pack_into("<Q", r, 0x240, u)
        return e.alloc(r)

    atk, dfn = rec(unit(attacker_ids, hp, max_hp)), rec(unit(defender_ids, 777, 999999))
    ctx = e.alloc(bytes(0x28000))
    mu.mem_write(ctx + 0x1328, struct.pack("<q", damage))     # target entry 0: the damage the defender took
    mu.mem_write(ctx + 0x27670, struct.pack("<i", skill))
    rsp = so.STACK + 0x100000 - 0x200                          # the body of FUN_1401ADA40 runs with rsp 16-aligned
    mu.reg_write(X.UC_X86_REG_RSP, rsp)
    regs = {X.UC_X86_REG_RBX: atk, X.UC_X86_REG_R13: dfn, X.UC_X86_REG_R15: ctx, X.UC_X86_REG_R14: 0, X.UC_X86_REG_R12: 0,
            X.UC_X86_REG_RDI: 0x1234567, X.UC_X86_REG_RBP: 0x1111, X.UC_X86_REG_RSI: 0x2222}
    for r, v in regs.items():
        mu.reg_write(r, v)
    mu.reg_write(X.UC_X86_REG_XMM6, struct.unpack("<I", struct.pack("<f", 100.0))[0])
    # the frame the game keeps: [rsp+0x34] = the round's hit counter read at 0x1401AE2BB, [rsp+0x1A0] = xmm6's save slot
    mu.mem_write(rsp + 0x34, struct.pack("<I", 0))
    out, bad, hooks, seen = {}, [], [], {}
    import capstone
    from unicorn import UC_HOOK_CODE
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    nonvol = (X.UC_X86_REG_RBX, X.UC_X86_REG_RBP, X.UC_X86_REG_RSI, X.UC_X86_REG_RDI, X.UC_X86_REG_R12, X.UC_X86_REG_R13,
              X.UC_X86_REG_R14, X.UC_X86_REG_R15, X.UC_X86_REG_RSP)
    xmms = [getattr(X, f"UC_X86_REG_XMM{i}") for i in range(6, 16)]
    saved = {}

    def code(uc, addr, size, _):
        if addr in STOPS:
            out["end"] = STOPS[addr]
            if addr == APPLY:
                out["applied"] = uc.reg_read(X.UC_X86_REG_RSI)
            uc.emu_stop()
            return
        if addr == SITE:
            saved.update({r: uc.reg_read(r) for r in nonvol + tuple(xmms)})
            seen["site"] = True
        elif addr == SITE + 5 and saved:
            seen["rdi_after"] = uc.reg_read(X.UC_X86_REG_RDI)
            for r, v in saved.items():
                if r != X.UC_X86_REG_RDI and uc.reg_read(r) != v:
                    bad.append(f"register {r} changed across the redirected call")
        if abi and section and section[0] <= addr < section[1]:
            ins = next(md.disasm(bytes(uc.mem_read(addr, size)), addr))
            if ins.mnemonic == "call" and uc.reg_read(X.UC_X86_REG_RSP) % 16:
                bad.append(f"misaligned call at {addr:#x}")

    hooks.append(mu.hook_add(UC_HOOK_CODE, code))
    try:
        mu.emu_start(START, 0x1401AE700, count=3_000_000)
    finally:
        for h in hooks:
            mu.hook_del(h)
    assert not bad, bad
    assert "end" in out, "the window did not end at a known address"
    return out["end"], out.get("applied", 0), seen.get("rdi_after")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--abi", action="store_true")
    ap.add_argument("--control")
    args = ap.parse_args()
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    if args.control:
        ev.ASM_FILE = str(mutated_asm(args.control))
    patched = ev.build_patch(original, ROWS)
    info = ev.section_info(patched)
    tmp = Path(tempfile.mkdtemp(prefix="lt2-xen-", dir=str(SCRATCH)))
    (tmp / "kit.exe").write_bytes(patched)
    kit, game = emu(tmp / "kit.exe"), emu(ORIGINAL)
    section = (info["code"], info["base"] + len(info["data"]))
    D = 1000
    # (label, emulator, kwargs, expected (outcome, applied))
    cases = [
        ("pinned exe: Malicious Reflect alone = 10% of the damage taken (game control)", game, dict(defender_ids=(REFLECT,)), ("apply", game_amount(10, D))),
        ("pinned exe: defender without 143, no rider", game, dict(defender_ids=(27691,)), ("none", 0)),
        ("kit: the real 143 alone behaves exactly as the game (10% of 1000 = 100)", kit, dict(defender_ids=(REFLECT,)), ("apply", 100)),
        ("kit: real 143 with another damage, 10% of 777 = 77", kit, dict(defender_ids=(REFLECT,), damage=777), ("apply", 77)),
        ("kit: real 143 with 40 other ids around it", kit, dict(defender_ids=tuple(range(1, 41)) + (REFLECT,)), ("apply", 100)),
        ("kit: Xenolith = 20% of the ATTACKER's max HP (1000 -> 200), not of the damage", kit, dict(defender_ids=(REFLECT, XEN)), ("apply", 200)),
        ("kit: Xenolith, the damage taken does not matter (50 taken, still 200)", kit, dict(defender_ids=(REFLECT, XEN), damage=50), ("apply", 200)),
        ("kit: Xenolith, max HP 777 -> trunc(155.4) = 155", kit, dict(defender_ids=(REFLECT, XEN), max_hp=777), ("apply", 155)),
        ("kit: Xenolith, max HP 99999 -> 19999", kit, dict(defender_ids=(REFLECT, XEN), max_hp=99999), ("apply", game_amount(100, 19999))),
        ("kit: Xenolith, max HP 4,000,000,000 -> 800,000,000", kit, dict(defender_ids=(REFLECT, XEN), max_hp=4_000_000_000, hp=9_000_000_000), ("apply", game_amount(100, 800_000_000))),
        ("kit: Xenolith, the game's clamp: attacker at 150 HP loses 149, never dies", kit, dict(defender_ids=(REFLECT, XEN), hp=150), ("apply", 149)),
        ("kit: Xenolith, attacker at exactly 200 HP (= the amount) loses 199", kit, dict(defender_ids=(REFLECT, XEN), hp=200), ("apply", 199)),
        ("kit: Xenolith, attacker at 201 HP loses 200", kit, dict(defender_ids=(REFLECT, XEN), hp=201), ("apply", 200)),
        ("kit: Xenolith, attacker at 1 HP: nothing applied (the game's own zero test)", kit, dict(defender_ids=(REFLECT, XEN), hp=1), ("none", 0)),
        ("kit: Xenolith, attacker max HP 0: nothing", kit, dict(defender_ids=(REFLECT, XEN), max_hp=0), ("none", 0)),
        ("kit: Xenolith, zero damage taken: the game skips the rider", kit, dict(defender_ids=(REFLECT, XEN), damage=0), ("none", 0)),
        ("kit: the row without the alias to 143 does nothing (no rider)", kit, dict(defender_ids=(XEN,)), ("none", 0)),
        ("kit: the row on the ATTACKER, defender holds only 143: the game's 10% (100)", kit, dict(defender_ids=(REFLECT,), attacker_ids=(XEN,)), ("apply", 100)),
        ("kit: two rows add up, 20 + 20 = 40% (400)", kit, dict(defender_ids=(REFLECT, XEN, 24081)), ("apply", 400)),
        ("kit: skill-condition row, normal attack: the game's 10% (100)", kit, dict(defender_ids=(REFLECT, 24082)), ("apply", 100)),
        ("kit: skill-condition row, a skill hit: 50% of max HP (500)", kit, dict(defender_ids=(REFLECT, 24082), skill=101), ("apply", 500)),
        ("kit: Xenolith, 40 other ids around the row", kit, dict(defender_ids=tuple(range(1, 41)) + (REFLECT, XEN)), ("apply", 200)),
    ]
    bad = 0
    for label, e, kw, want in cases:
        try:
            got = run(e, abi=args.abi and e is kit, section=section, **kw)
            res = (got[0], got[1])
        except AssertionError as ex:
            res = ("ABI", str(ex))
        ok = res == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label:92} {res} (expected {want})")
    # the rdi the game reads is the amount for a holder, and untouched for everything else (the one deliberate register change)
    for label, kw, want in (("holder: rdi after the call = the amount (200)", dict(defender_ids=(REFLECT, XEN)), 200),
                            ("real 143 alone: rdi after the call = the damage taken, untouched", dict(defender_ids=(REFLECT,)), D)):
        got = run(kit, section=section, abi=args.abi, **kw)[2]
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label:92} {got} (expected {want})")
    n = len(cases) + 2
    print(f"{n - bad}/{n} {'abi' if args.abi else 'behavior'}; kit build sha256 {hashlib.sha256(patched).hexdigest()[:16]}, pinned exe {game.exe_sha[:16]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
