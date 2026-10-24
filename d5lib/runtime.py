"""The D5 Mod Kit runtime: what the game loads besides its own code.

The game gets a tiny exe hook (new section .d5auto): the per-frame update 0x1402211e0 calls the input poll
0x1408a50c0 at 0x14022124f; that call goes to our stub instead, which calls the input poll and then d5_frame() of
d5auto.dll (the loader, d5load.c: loaded from the game folder on the first frame with LoadLibraryA /
GetProcAddress from the game's import table).  The loader runs d5core.dll (d5auto.c and the .inc.c files it
includes; a copy, so it can be swapped while the game runs), which serves every runtime feature:
  * outfit looks' custom colours (d5looks.inc.c; d5lib.outfits sets ctx.needs_runtime),
  * the character-row fixer for old saves (d5rows.inc.c; inserted_char_rows),
  * custom colour slots (d5color.inc.c; d5lib.customcolors),
  * the live skill preview (d5live.inc.c; d5lib.skills sets ctx.live_skills),
  * the D5 Mod Kit's link to the game (d5ctl.inc.c; kit setting "game_link"),
  * the Item World auto-battle (d5pilot / d5di / d5menu.inc.c + d5lib.autobattle) -- only where its sources are:
    without them d5auto.c builds with d5noauto.inc.c's stand-ins (the shareable kit leaves it out).
d5auto.ini (next to the exe) switches each one on or off.  Built with Zig (pip install ziglang), cached in cache/ by
the hash of the sources.  Installed files are removed on restore.
"""
import hashlib
import os
import struct
import subprocess
import sys

import pefile

from .gamefs import EXE_FILE
from .modsys import register_finalizer

IMAGE_BASE = 0x140000000
SECTION_NAME = b".d5auto"
FRAME_VA = 0x14022124F                       # call 0x1408a50c0 (input poll) inside the per-frame update
FRAME_ORIG = bytes.fromhex("e86c3e6800")
INPUT_POLL = 0x1408A50C0
IAT_LOADLIBRARYA = 0x1408D5068
IAT_GETPROCADDRESS = 0x1408D5070
DLL_NAME = "d5auto.dll"
INI_NAME = "d5auto.ini"
GAME_PREFIX = "GAME/"                        # loose files next to the exe (see modsys.Installer)

HERE = os.path.dirname(os.path.abspath(__file__))
NATIVE = os.path.join(HERE, "native")
SOURCE = os.path.join(NATIVE, "d5auto.c")
CACHE = os.path.join(HERE, "..", "cache")
LOADER_SOURCE = os.path.join(NATIVE, "d5load.c")
CORE_NAME = "d5core.dll"
LIBS = ["-ld3d11", "-ldxgi", "-luuid", "-ladvapi32", "-lgdi32"]
AUTO_SOURCES = ("d5pilot.inc.c", "d5di.inc.c", "d5menu.inc.c")     # the Item World auto-battle (left out when shared)


def has_autobattle(native=NATIVE):
    """this kit carries the Item World auto-battle (its native sources)"""
    return all(os.path.exists(os.path.join(native, n)) for n in AUTO_SOURCES)


# ------------------------------------------------------------------------------------------ exe
def is_hooked(exe: bytes) -> bool:
    return SECTION_NAME in exe[:0x400]


def _asm(src, addr):
    from keystone import Ks, KS_ARCH_X86, KS_MODE_64
    from . import exemap
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_64).asm(exemap.ACTIVE.text(src), addr)
    return bytes(enc)


def build_exe_hook(exe: bytes) -> bytes:
    """Add the per-frame DLL hook to an exe (vanilla or already carrying other .d5 patches)."""
    if is_hooked(exe):
        return exe
    from . import exemap
    pe = pefile.PE(data=exe, fast_load=True)   # headers and sections only: a full parse takes ~1 s
    frame_va = exemap.site(pe, FRAME_VA, FRAME_ORIG, "the runtime's hook site")
    sec_align = pe.OPTIONAL_HEADER.SectionAlignment
    file_align = pe.OPTIONAL_HEADER.FileAlignment
    last = max(pe.sections, key=lambda s: s.VirtualAddress)
    new_rva = (last.VirtualAddress + max(last.Misc_VirtualSize, last.SizeOfRawData) + sec_align - 1) \
        // sec_align * sec_align
    new_raw = (len(exe) + file_align - 1) // file_align * file_align
    base = IMAGE_BASE + new_rva
    nl = chr(10)
    # stub: call the input poll, then (lazily loaded) d5_frame().  Data lives in the same RWX section.
    src = nl.join([
        "frame_hook:",
        "    push rbx",                      # entry rsp = 8 mod 16 -> aligned, with 0x20 shadow space
        "    sub rsp, 0x20",
        f"    call {INPUT_POLL:#x}",
        "    mov rax, qword ptr [rip + fn_frame]",
        "    test rax, rax",
        "    jnz have",
        "    cmp byte ptr [rip + tried], 0",
        "    jne done",
        "    mov byte ptr [rip + tried], 1",
        "    lea rcx, [rip + dll_name]",
        "    call qword ptr [rip + IAT_LOADLIBRARYA]",
        "    test rax, rax",
        "    jz done",
        "    mov rcx, rax",
        "    lea rdx, [rip + proc_name]",
        "    call qword ptr [rip + IAT_GETPROCADDRESS]",
        "    mov qword ptr [rip + fn_frame], rax",
        "    test rax, rax",
        "    jz done",
        "have:",
        "    call rax",
        "done:",
        "    add rsp, 0x20",
        "    pop rbx",
        "    ret",
        "    .align 16",
        "fn_frame:",
        "    .quad 0",
        "tried:",
        "    .byte 0",
        "    .align 8",
        "dll_name:",
        "    .byte " + ", ".join(str(b) for b in DLL_NAME.encode() + b"\0"),
        "proc_name:",
        "    .byte " + ", ".join(str(b) for b in b"d5_frame\0"),
        f"    IAT_LOADLIBRARYA = {IAT_LOADLIBRARYA:#x}",
        f"    IAT_GETPROCADDRESS = {IAT_GETPROCADDRESS:#x}",
    ])
    code = _asm(src, base)
    section = code + b"\xCC" * (-len(code) % file_align)
    out = bytearray(exe) + b"\0" * (new_raw - len(exe))
    nsec = pe.FILE_HEADER.NumberOfSections
    sh_off = pe.DOS_HEADER.e_lfanew + 4 + 20 + pe.FILE_HEADER.SizeOfOptionalHeader + 40 * nsec
    if sh_off + 40 > pe.OPTIONAL_HEADER.SizeOfHeaders:
        raise ValueError("no room for another section header")
    hdr = struct.pack("<8sIIIIIIHHI", SECTION_NAME.ljust(8, b"\0"), len(code), new_rva, len(section), new_raw,
                      0, 0, 0, 0, 0xE0000020)  # code | execute | read | write
    out[sh_off:sh_off + 40] = hdr
    fh = pe.DOS_HEADER.e_lfanew + 4
    struct.pack_into("<H", out, fh + 2, nsec + 1)
    size_of_image = (new_rva + len(code) + sec_align - 1) // sec_align * sec_align
    struct.pack_into("<I", out, fh + 20 + 56, size_of_image)
    out += section
    # the hooked call: same length (5 bytes), now calls our stub
    off = pe.get_offset_from_rva(frame_va - IMAGE_BASE)
    out[off:off + 5] = b"\xE8" + struct.pack("<i", base - (frame_va + 5))
    return bytes(out)


# ------------------------------------------------------------------------------------------ dll
def _source_text(path):
    """a native source as compiled for the game build being patched (exemap.ACTIVE: its game addresses)"""
    from . import exemap
    with open(path, "rb") as f:
        raw = f.read()
    if exemap.ACTIVE.identity:
        return raw
    src = exemap.translate_c(exemap.ACTIVE, raw.decode("utf-8", "replace"))
    if os.path.basename(path) == "d5auto.c":
        # the build, for code that differs in more than its addresses (#if defined(D5_BUILD_9460A6411699) ...)
        src = f"#define D5_BUILD_{exemap.ACTIVE.sha1[:12].upper()} 1\n#line 1\n" + src
    return src.encode("utf-8")


def cached_name(sources, out_name):
    """the cache file name of a DLL built from these sources (sha1 of their names and contents, as translated for
    the game build)"""
    src = b""
    for path in sources:
        src += os.path.basename(path).encode() + b"|" + _source_text(path)
    h = hashlib.sha1(src + b"v3").hexdigest()[:12]
    return f"{os.path.splitext(out_name)[0]}-{h}.dll"


def _compile(sources, out_name, main, libs, log, cache=CACHE):
    """compile one DLL with Zig (cached by the hash of its sources)"""
    os.makedirs(cache, exist_ok=True)
    out = os.path.join(cache, cached_name(sources, out_name))
    if not os.path.exists(out):
        log(f"  compiling {out_name} (Zig) ...")
        from . import exemap
        if not exemap.ACTIVE.identity:          # this game build's addresses: a translated copy of the sources
            import tempfile
            tdir = tempfile.mkdtemp(prefix="d5native_")
            for path in sources:
                with open(os.path.join(tdir, os.path.basename(path)), "wb") as f:
                    f.write(_source_text(path))
            main = os.path.join(tdir, os.path.basename(main))
        cmd = [sys.executable, "-m", "ziglang", "cc", "-target", "x86_64-windows-gnu", "-shared", "-O2",
               "-o", out, main] + libs
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0 or not os.path.exists(out):
            msg = (r.stderr or r.stdout or "").strip()
            if "No module named ziglang" in msg:
                msg = "the Zig compiler is missing: run  pip install ziglang"
            raise RuntimeError(f"could not build {out_name}: " + msg[-2000:])
    with open(out, "rb") as f:
        return f.read()


def core_sources(native=NATIVE):
    """d5auto.c and the files it includes (everything in native/ except the loader)"""
    return [os.path.join(native, n) for n in sorted(os.listdir(native))
            if n.endswith((".c", ".h")) and n != os.path.basename(LOADER_SOURCE)]


def loader_sources(native=NATIVE):
    return [os.path.join(native, os.path.basename(LOADER_SOURCE))]


def build_core(log=print, native=NATIVE, cache=CACHE) -> bytes:
    """d5core.dll: every runtime feature (hot-reloadable, see d5load.c)"""
    return _compile(core_sources(native), CORE_NAME, os.path.join(native, "d5auto.c"), LIBS, log, cache)


def build_loader(log=print, native=NATIVE, cache=CACHE) -> bytes:
    """d5auto.dll: the small loader the exe patch loads"""
    src = loader_sources(native)
    return _compile(src, DLL_NAME, src[0], [], log, cache)


def build_dll(log=print) -> bytes:
    """compatibility name: the loader"""
    return build_loader(log)


# -------------------------------------------------------------------------------------- settings
def ini_text(s, auto=None) -> str:
    """d5auto.ini.  s: the runtime's own switches (_colors, _live_skills, remote, research, test_anywhere,
    battle_speed); auto: the auto-battle's settings (d5lib.autobattle) or None (its sections are left out and the
    feature is off)."""
    cc = s.get("_colors") or {}
    lines = [
        "; D5 Mod Kit runtime settings (written by D5 Mod Kit)",
        "[features]",
        f"autobattle={1 if auto else 0}",
        "[colors]",
        "; custom colour slots: the key saving the precise colour editor's colours into Custom Color 1-3",
        f"enabled={1 if cc else 0}",
        f"key={cc.get('key', 'U')}",
        f"pad={cc.get('pad', 'R3')}",
    ]
    if auto:
        lines += [
            "[keys]",
            f"toggle_key={auto['toggle_key']}",
            f"pad_combo={auto['pad_combo']}",
            f"editor_key={auto.get('editor_key', 'F6')}",
            "[auto]",
            f"deploy={1 if auto.get('deploy', True) else 0}",
            f"deploy_max={int(auto.get('deploy_max', 10))}",
            "; stall_limit: switch off after this many turns in which no enemy lost HP and no unit got closer (0 = never)",
            f"stall_limit={int(auto.get('stall_limit', 8))}",
            "[tactics]",
            "; sp_saving: a unit whose normal attack kills every enemy within `reach` panels uses normal attacks only that turn",
            f"sp_saving={1 if auto.get('sp_saving', True) else 0}",
            "; kill_margin: estimated normal-attack damage must be at least this % of the enemy's HP",
            f"kill_margin={int(auto.get('kill_margin', 150))}",
            f"reach={int(auto.get('reach', 10))}",
            "; heal_below: casters (INT > ATK) keep their SP while an ally is below this HP %",
            f"heal_below={int(auto.get('heal_below', 50))}",
            "[display]",
            f"corner={int(auto['corner'])}",
        ]
    lines += [
        "[debug]",
        f"test_anywhere={1 if s.get('test_anywhere') else 0}",
        f"research={1 if s.get('research') else 0}",
        "; remote: the D5 Mod Kit's link to the game: skill recordings (editor's Game view), test tools (tools/d5ctl.py)",
        f"remote={1 if s.get('remote') else 0}",
        "[skills]",
        "; live_reload: the D5 Mod Kit's skill preview (d5live_script.dat) is loaded into the running game",
        f"live_reload={1 if s.get('_live_skills') else 0}",
        "[battle]",
        "; speed: actions in battle (skit fast-forward): 0 = the game's Options, 1 = normal (holding the fast-forward",
        ";        button still speeds up), 2-4 = always fast-forward at xN.  Memory only: the save's Options stay as they are",
        f"speed={int(s.get('battle_speed') or 0)}",
        "",
    ]
    return "\r\n".join(lines)


# -------------------------------------------------------------------------------------- finalizer
def inserted_char_rows(ctx):
    """class ids mods added to char.dat BETWEEN existing ones (the game sorts the table by id, so every later
    row moves; the runtime DLL (d5rows.inc.c) then re-points old saves' units)"""
    from . import database
    from .dbpatch import DB_ARCHIVE
    vp = f"{DB_ARCHIVE}/char.dat"
    if vp.lower() not in ctx.outputs:
        return []
    van = {r["id"] for r in database.load_table("char.dat", ctx.fs.read(vp)).rows}
    top = max(van)
    return sorted(r["id"] for r in database.load_table("char.dat", ctx.get(vp)).rows
                  if r["id"] not in van and r["id"] < top)


def _finalize(ctx):
    """Install the runtime when any feature needs it: outfit looks with more looks than colour sets, inserted
    character rows, custom colour slots, the live skill preview, the auto-battle (ctx.autobattle, set by
    d5lib.autobattle's patch handler when its mod is enabled)."""
    auto = getattr(ctx, "autobattle", None)
    if auto and not has_autobattle():
        ctx.log("  auto-battle settings found, but this kit has no auto-battle: left out")
        auto = None
    cc = getattr(ctx, "custom_colors", None)
    rows = inserted_char_rows(ctx)
    if rows:
        ctx.log(f"  character rows inserted ({', '.join(map(str, rows))}): the runtime keeps old saves' units on "
                "their own rows")
    if not auto and not cc and not rows and not getattr(ctx, "needs_runtime", False):
        return
    s = {k: auto.get(k) for k in ("test_anywhere", "research", "remote", "battle_speed")} if auto else {}
    s["_colors"] = cc
    s["_live_skills"] = getattr(ctx, "live_skills", False)
    # the skill editor's Game view records skills through the harness pipe (kit setting "game_link")
    from .paths import kit_setting
    s["remote"] = bool(s.get("remote")) or bool(kit_setting("game_link", False))
    ctx.put(EXE_FILE, build_exe_hook(ctx.get(EXE_FILE)))
    ctx.put(GAME_PREFIX + DLL_NAME, build_loader(ctx.log))
    ctx.put(GAME_PREFIX + CORE_NAME, build_core(ctx.log))
    ctx.put(GAME_PREFIX + INI_NAME, ini_text(s, auto).encode())
    if cc:
        ctx.log(f"  custom colour slots: save key {cc.get('key', 'U')} / {cc.get('pad', 'R3')} in the precise colour editor")
    if auto:
        from . import autobattle
        autobattle.add_runtime_files(ctx, auto)


register_finalizer(_finalize)
