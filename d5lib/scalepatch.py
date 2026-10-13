"""Full-size drawing for the kit's own-animation sprites numbered 10000+ (exe section .d5sc).

The game draws an animation block whose id is 10000-19999 or 30000-39999 at 0.67 size (portraits and cut-ins:
0x1402f1a6f and 0x1402f200f, `mulss` by 0.67 at 0x1409bf634).  A sprite with its own animation set is drawn from its
own block (the outfit layer hook), whose id is the sprite number -- so every outfit / new character sprite numbered
10000+ (DRPG outfits from Laharl's on, Future Usalia, Liezerota, Girl Laharl's newer looks) appeared at two thirds
of its size.  Both sites skip the scale for the kit's own sprites; portraits keep theirs.

A sprite's cut-in / Status screen portrait is block sprite + 10000: for the kit's sprites numbered 10000+ that is
20000-29999, a range the game never scales -- those portraits showed at 1.5 times their size, spilling out of the
Status screen's frame (Liezerota 23040).  Both sites scale them like the game's own portraits.
"""
from . import exepatch

SECTION = b".d5sc"
# cmp eax, 10000 / jb scale / lea eax, [rcx - 30000] / cmp eax, 10000 / jae skip   (ecx = block id)
ORIG = bytes.fromhex("3d10270000720d8d81d08affff3d102700007310")
SITES = {0x1402F1A6F: (0x1402F1A83, 0x1402F1A93),       # site: (scale, skip)
         0x1402F200F: (0x1402F2023, 0x1402F2033)}


def scaled(n):
    n = int(n)
    return 10000 <= n < 20000 or 30000 <= n < 40000


def patch(exe: bytes, own_sprites, log=print) -> bytes:
    big = sorted({int(x) for x in own_sprites if scaled(x)})
    portraits = sorted({int(x) + 10000 for x in own_sprites if 10000 <= int(x) < 20000})
    if not big and not portraits:
        return exe
    # sc_kind: ecx = block id -> eax 0 (own sprite: full size), 1 (kit portrait: scaled), 2 (the game's rule)
    shared = "\n".join(["sc_kind:", "push rdx", "push r8", "xor eax, eax", "lea rdx, [rip + sc_ids]",
                        f"mov r8d, {len(big)}",
                        "sc_loop:", "test r8d, r8d", "je sc_next", "cmp ecx, dword ptr [rdx]", "je sc_done",
                        "add rdx, 4", "dec r8d", "jmp sc_loop",
                        "sc_next:", "inc eax", "lea rdx, [rip + sc_portraits]", f"mov r8d, {len(portraits)}",
                        "sc_loop2:", "test r8d, r8d", "je sc_none", "cmp ecx, dword ptr [rdx]", "je sc_done",
                        "add rdx, 4", "dec r8d", "jmp sc_loop2",
                        "sc_none:", "inc eax",
                        "sc_done:", "pop r8", "pop rdx", "ret",
                        ".align 4", "sc_ids:", ".long " + ", ".join(map(str, big or [0])),
                        "sc_portraits:", ".long " + ", ".join(map(str, portraits or [0]))])
    hooks = []
    for site, (scale, skip) in SITES.items():
        src = "\n".join(["call {shared}", "test eax, eax", f"je {skip:#x}", "cmp eax, 1", f"je {scale:#x}",
                         "lea eax, [rcx - 0x2710]", "cmp eax, 0x2710", f"jb {scale:#x}",
                         "lea eax, [rcx - 0x7530]", "cmp eax, 0x2710", f"jae {skip:#x}", f"jmp {scale:#x}"])
        hooks.append((site, ORIG, src, 0xE9))
    log(f"  sprite scale: {len(big)} own sprite(s) numbered 10000+ drawn at full size, "
        f"{len(portraits)} portrait(s) numbered 20000+ at the game's portrait size")
    return exepatch.add_hook_section(exe, SECTION, hooks, shared)


# --------------------------------------------------------------------------------------------------- humanoid or not
# The game takes a character whose sprite number is above 2000 for a monster (vanilla: humanoids < 2000, monsters
# 2010+): its battle actor draws the light / companion file (sprite + 1, 0x140159f37) and 0x14014e0a0 (mode 3) says
# "monster".  The kit's humanoid sprites are numbered 9500+: in battle they showed sprite + 1 while a skill's copy of
# the caster (cmd_6410) asked for the full sprite -- the copy stayed invisible (Seraphina's Dazzling Eyes in an outfit).
# Both checks treat the kit's humanoid own sprites as humanoids.
HUM_SECTION = b".d5hm"
HUM_SITES = [
    # battle unit actor: cmp word [row + 0xd4], 2000 / setg sil / jmp
    (0x140159F37, "6642398419d4000000400f9fc6e904ffffff",
     ["push rdx", "movsx edx, word ptr [rcx + r11 + 0xd4]", "call {shared}", "jne hm_a", "xor edx, edx",
      "hm_a:", "cmp dx, ax", "pop rdx", "setg sil", "jmp 0x140159e4d"]),
    # 0x14014e0a0 mode 3 (monster?): cmp word [row + 0xd4], dx(2000) / jle no
    (0x14014E0F1, "66399401d40000007eb4",
     ["movsx edx, word ptr [rcx + rax + 0xd4]", "call {shared}", "je 0x14014e0af", "cmp edx, 0x7d0",
      "jle 0x14014e0af", "jmp 0x14014e0fb"]),
]


def humanoid_patch(exe: bytes, humanoid_sprites, log=print) -> bytes:
    ids = sorted({int(x) for x in humanoid_sprites if int(x) > 2000})
    if not ids:
        return exe
    shared = "\n".join(["hm_check:", "push rcx", "push r8", "lea rcx, [rip + hm_ids]", f"mov r8d, {len(ids)}",
                        "hm_loop:", "test r8d, r8d", "je hm_no", "cmp edx, dword ptr [rcx]", "je hm_yes",
                        "add rcx, 4", "dec r8d", "jmp hm_loop",
                        "hm_yes:", "pop r8", "pop rcx", "cmp eax, eax", "ret",        # ZF = 1: a kit humanoid
                        "hm_no:", "pop r8", "pop rcx", "test esp, esp", "ret",        # ZF = 0
                        ".align 4", "hm_ids:", ".long " + ", ".join(map(str, ids))])
    hooks = [(va, bytes.fromhex(orig), "\n".join(src), 0xE9) for va, orig, src in HUM_SITES]
    log(f"  humanoid sprites: {len(ids)} own sprite(s) above 2000 count as humanoids (not monsters)")
    return exepatch.add_hook_section(exe, HUM_SECTION, hooks, shared)


# ----------------------------------------------------------------------------------------- what the scripts see
# Skill scripts tell characters apart by the sprite number of a unit's class ($62100-$62199: 0x14015b130 returns
# char.dat sprite_id, read only by the two script-value getters): `if ($62199 == 40) cmd_6402 1001, 7002` spawns
# Seraphina's event-pose actor for Dazzling Eyes, other branches move, time or voice a skill per character.  A unit
# in an outfit with its own sprite (9740) matched none of them -- the event pose never appeared and Seraphina
# vanished for most of the skill.  The scripts now see a kit sprite as the vanilla sprite it stands in for.
SS_SECTION = b".d5ss"
SS_SITE, SS_ORIG = 0x14015B1B0, "0fbf80d4000000"      # movsx eax, word ptr [rax + 0xd4] (then add rsp / pop / ret)


def script_sprite_patch(exe: bytes, mapping, log=print) -> bytes:
    """mapping: {kit sprite: vanilla sprite the skill scripts should see}"""
    rows = sorted((int(a), int(b)) for a, b in mapping.items() if int(a) != int(b))
    if not rows:
        return exe
    shared = "\n".join(["ss_map:", "push rcx", "push rdx", "lea rdx, [rip + ss_table]", f"mov ecx, {len(rows)}",
                        "ss_loop:", "test ecx, ecx", "je ss_done", "cmp eax, dword ptr [rdx]", "je ss_hit",
                        "add rdx, 8", "dec ecx", "jmp ss_loop",
                        "ss_hit:", "mov eax, dword ptr [rdx + 4]",
                        "ss_done:", "pop rdx", "pop rcx", "ret", ".align 4", "ss_table:"]
                       + [f".long {a}, {b}" for a, b in rows])
    src = "\n".join(["movsx eax, word ptr [rax + 0xd4]", "call {shared}", f"jmp {SS_SITE + 7:#x}"])
    log(f"  script sprites: skill scripts see {len(rows)} own sprite(s) as their character's / template's")
    return exepatch.add_hook_section(exe, SS_SECTION, [(SS_SITE, bytes.fromhex(SS_ORIG), src, 0xE9)], shared)
