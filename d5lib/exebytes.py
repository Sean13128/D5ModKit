"""Checked exe byte patches carried by a mod as data (patches/exe/*.json): no kit code needed.

{"build": "<sha1 prefix, optional>", "patches": [{"va": "0x1401AF645", "orig": "0F84DE010000", "new": "660F1F440000",
  "what": "...", "values": [{"offset": 2, "size": 4, "setting": "cost", "default": 100}]}]}

`va` (a hex string or an int) is an address of the build named by `build` (absent: the build being patched,
exemap.Native).  `values` writes mod.json settings[setting] (or default) little-endian into `new` at `offset`.  The
site owner is `mod <folder id>` (the display name is not unique).  An entry inside a kit-added (.d5*) section, or not
wholly inside one original section of the image, is rejected: patches/exe targets the game's own code, not the
kit's.  A mod is applied whole or not at all;
a mod that doesn't fit is left out with a note and the others still go in.  Hex strings and ints only: nothing a mod
carries is ever run.
"""
import glob
import os

from . import exemap
from .exepatch import KIT_SECTION_PREFIX, pefile
from .gamefs import EXE_FILE
from .modsys import Mod, register_finalizer

IMAGE_BASE = 0x140000000


def _hex(s):
    return bytes.fromhex("".join(str(s).split()))


def _fail(what, field, why):
    raise ValueError(f"{what}: {field} {why}")


def _int(what, field, v):
    if type(v) is not int:
        _fail(what, field, f"must be a whole number (JSON integer), not {v!r}")
    return v


def _hexbytes(what, field, v):
    if not isinstance(v, str):
        _fail(what, field, f"must be a hex string, not {v!r}")
    try:
        if "_" in v:
            raise ValueError(v)         # bytes.fromhex accepts nothing of the kind, but int() does: no separators
        b = _hex(v)
    except ValueError:
        _fail(what, field, f"is not valid even-length hex: {v!r}")
    if not b:
        _fail(what, field, "must not be empty")
    return b


def _va(what, v):
    if type(v) is int:
        va = v
    elif isinstance(v, str):
        try:
            va = int(v.strip(), 16)
        except ValueError:
            _fail(what, "va", f"must be a hex string or an integer, not {v!r}")
    else:
        _fail(what, "va", f"must be a hex string or an integer, not {v!r}")
    if va < 0:
        _fail(what, "va", f"must not be negative: {v!r}")
    return va


def load(mod):
    """the mod's entries: [{"va", "orig", "new" (settings applied), "what"}]; ValueError (naming file, entry and
    field) when the data is malformed or can't apply to this build.  Nothing else can escape."""
    out = []
    for path in sorted(glob.glob(os.path.join(mod.patches_dir, "exe", "*.json"))):
        fn = os.path.basename(path)
        try:
            doc = mod.load_patch("exe", fn)
        except (OSError, ValueError, RecursionError) as e:      # JSONDecodeError and UnicodeDecodeError are ValueErrors
            raise ValueError(f"{fn}: unreadable ({type(e).__name__}: {e})") from None
        if not isinstance(doc, dict) or not isinstance(doc.get("patches", []), list):
            raise ValueError(f"{fn}: expected an object with a list of patches")
        build = doc.get("build")
        if build is not None and build != "":
            if not isinstance(build, str) or not build.strip() or any(c not in "0123456789abcdefABCDEF" for c in build.strip()):
                raise ValueError(f"{fn}: build must be a hex string, not {build!r}")
            if not exemap.ACTIVE.sha1.startswith(build.strip().lower()):
                raise ValueError(f"{fn} is for game build {build}, this one is {exemap.ACTIVE.sha1[:12]}")
        settings = mod.meta.get("settings", {})
        settings = settings if isinstance(settings, dict) else {}
        for i, p in enumerate(doc.get("patches", [])):
            what = f"{fn} #{i}"
            if not isinstance(p, dict):
                raise ValueError(f"{what}: expected an object")
            for k in ("va", "orig", "new"):
                if k not in p:
                    _fail(what, k, "is missing")
            if isinstance(p.get("what"), str) and p["what"]:
                what = f"{fn} #{i} ({p['what']})"
            else:
                what = f"{fn} #{i} ({p['va']})"
            va, orig, new = _va(what, p["va"]), _hexbytes(what, "orig", p["orig"]), bytearray(_hexbytes(what, "new", p["new"]))
            values = p.get("values", [])
            if not isinstance(values, list):
                _fail(what, "values", "must be a list")
            specs = []
            for j, v in enumerate(values):
                vw = f"{what} value #{j}"
                if not isinstance(v, dict):
                    raise ValueError(f"{vw}: expected an object")
                for k in ("setting", "offset", "size"):
                    if k not in v:
                        _fail(vw, k, "is missing")
                if not isinstance(v["setting"], str) or not v["setting"]:
                    _fail(vw, "setting", f"must be a non-empty string, not {v['setting']!r}")
                default = v.get("default")
                if "default" in v and default is not None:
                    _int(vw, "default", default)
                specs.append((vw, v["setting"], _int(vw, "offset", v["offset"]), _int(vw, "size", v["size"]), default))
            if len(orig) != len(new):
                raise ValueError(f"{what}: orig is {len(orig)} bytes, new is {len(new)}")
            for vw, setting, off, size, default in specs:
                val = settings.get(setting, default)
                if setting in settings:
                    _int(vw, f"setting {setting}", val)
                if off < 0 or size < 1 or off + size > len(new):
                    raise ValueError(f"{vw}: {setting} lies outside the {len(new)} bytes")
                try:
                    new[off:off + size] = int(val).to_bytes(size, "little", signed=int(val) < 0)
                except (OverflowError, TypeError, ValueError):
                    raise ValueError(f"{vw}: setting {setting} = {val!r} doesn't fit {size} bytes") from None
            out.append({"va": va, "orig": orig, "new": bytes(new), "what": what})
    return out


def describe(mod):
    """one line for the player: how much game code a mod's patches/exe changes, or "" when it carries none
    (counted from the raw files; nothing is checked against a build here)"""
    n = size = 0
    for path in sorted(glob.glob(os.path.join(mod.patches_dir, "exe", "*.json"))):
        try:
            for p in mod.load_patch("exe", os.path.basename(path)).get("patches", []):
                n, size = n + 1, size + len(_hex(p["orig"]))
        except (AttributeError, KeyError, TypeError, ValueError):
            pass            # malformed: the install leaves it out with its own note
    return f"{mod.name}: patches the game's code at {n} sites ({size} bytes)" if n else ""


def describe_package(path):
    """the same notice for a shared mod's .zip, read straight from the archive before anything is imported: how much
    game code its patches/exe change ("" when it has none).  Unreadable patch data still counts as a notice."""
    import json
    import re
    import zipfile
    n = size = 0
    unreadable = False
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not re.fullmatch(r"[^/]+/patches/exe/[^/]+\.json", name.replace("\\", "/"), re.I):
                continue
            try:
                for p in json.loads(z.read(name)).get("patches", []):
                    n, size = n + 1, size + len(_hex(p["orig"]))
            except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
                unreadable = True
    if unreadable:
        return "patches the game's code (some of the patch data is unreadable: it will be left out at install)"
    return f"patches the game's code at {n} sites ({size} bytes)" if n else ""


def warning_text(name, note):
    """what the player is asked before a shared mod with patches/exe is imported"""
    return (f"'{name}' changes the game's program, not only its data: it {note}.\n\n"
            "Each patch is checked byte by byte against the original program and is left out if it does not match, "
            "and Restore vanilla puts the original program back. But what a patch writes runs when you play, so "
            "import it only if you trust who made it.\n\nImport it?")


def _check_range(pe, e):
    """a range must lie wholly inside one of the game's own sections, never in a section the kit added"""
    rva, n = e["va"] - IMAGE_BASE, len(e["orig"])
    for s in pe.sections:
        if s.Name.startswith(KIT_SECTION_PREFIX) and rva < s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData) \
                and s.VirtualAddress < rva + n:
            raise ValueError(f"{e['what']}: address {e['va']:#x} is in the kit's generated section "
                             f"{s.Name.rstrip(chr(0).encode()).decode(errors='replace')}: patches/exe targets the game's own code, not the kit's")
    if not any(not s.Name.startswith(KIT_SECTION_PREFIX) and s.VirtualAddress <= rva
               and rva + n <= s.VirtualAddress + min(s.Misc_VirtualSize, s.SizeOfRawData) for s in pe.sections):
        raise ValueError(f"{e['what']}: address {e['va']:#x} is outside the game's image")


def apply(exe, entries, owner, base=None):
    """exe with every entry written, each checked (and claimed under `owner`) first; `base` is the exe the checks read
    (default exe itself: a later mod's site is then judged against the earlier mods' bytes)"""
    pe = pefile.PE(data=base or exe, fast_load=True)
    for e in entries:
        _check_range(pe, e)
    with exemap.owner(owner):
        for e in entries:       # the clash first: a range a kit feature changed already reads differently, and the owner's name is the useful message
            exemap.claim(e["va"], len(e["orig"]), e["what"])
        sites = [(exemap.site(pe, exemap.Native(e["va"]), e["orig"], e["what"]), e) for e in entries]
    out = bytearray(exe)
    for va, e in sites:
        off = pe.get_offset_from_rva(va - IMAGE_BASE)
        out[off:off + len(e["new"])] = e["new"]
    return bytes(out)


def _finalize(ctx):
    base = cur = None
    for f in getattr(ctx, "mod_folders", []) or []:
        mod = Mod(f)
        owner = f"mod {mod.id}"        # the folder id is unique (display names are not); never a kit feature's name
        shown = f"{mod.name} ({mod.id})" if mod.name != mod.id else mod.id
        try:
            entries = load(mod)
            if not entries:
                continue
            base = base or ctx.get(EXE_FILE)
            cur = apply(cur or base, entries, owner, base)
        except ValueError as e:
            exemap.release(owner)
            ctx.skipped_features = getattr(ctx, "skipped_features", []) + [(f"mod {shown}", str(e))]
            ctx.log(f"  warning: exe patches of {shown} left out: {e}")
            continue
        ctx.log(f"  {describe(mod)}")
    if cur:
        ctx.put(EXE_FILE, cur)


register_finalizer(_finalize)
