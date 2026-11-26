"""Checked exe byte patches carried by a mod as data (patches/exe/*.json): no kit code needed.

{"build": "<sha1 prefix, optional>", "patches": [{"va": "0x1401AF645", "orig": "0F84DE010000", "new": "660F1F440000",
  "what": "...", "values": [{"offset": 2, "size": 4, "setting": "cost", "default": 100}]}]}

`va` (a hex string or an int) is an address of the build named by `build` (absent: the build being patched,
exemap.Native).  `values` writes mod.json settings[setting] (or default) little-endian into `new` at `offset`.  The
site owner is `mod <folder id>` (the display name is not unique).  An entry inside a kit-added (.d5*) section, or not
wholly inside one original section of the image, is rejected: patches/exe targets the game's own code, not the
kit's.  Limits: MAX_PATCH_BYTES per patch, MAX_MOD_BYTES per mod (sum of `new`).

These patches are machine code that runs inside the game, so a mod carrying them is OFF until the player approves it:
the installer never evaluates mod-supplied Python, but it does write these bytes into the game program.  The approval
(approve / is_approved) is kept outside the mod, in <kit>/exe_approvals.json, bound to a fingerprint of the patch
files and the mod's settings: changed content needs a new approval.  A mod is applied whole or not at all (modsys.build
builds again without a mod whose patches can't apply or aren't approved, saying why); the others still go in.
"""
import glob
import hashlib
import json
import os

from . import exemap
from .exepatch import KIT_SECTION_PREFIX, pefile
from .gamefs import EXE_FILE
from .modsys import Mod, register_finalizer

IMAGE_BASE = 0x140000000
MAX_PATCH_BYTES = 256
MAX_MOD_BYTES = 4096
APPROVALS = "exe_approvals.json"


def carries(mod):
    """True when the mod has patches/exe files at all (counted by file, never by parsing: malformed still counts)"""
    return bool(glob.glob(os.path.join(mod.patches_dir, "exe", "*.json")))


def snapshot(mod):
    """the exact patches/exe bytes and settings an approval covers and a build applies, read once:
    {"files": {name: bytes}, "settings": {...}, "fingerprint": sha256}.  ValueError naming the file when one can't be
    read (a whole-mod skip with its reason, never a traceback)."""
    files = {}
    for path in sorted(glob.glob(os.path.join(mod.patches_dir, "exe", "*.json"))):
        fn = os.path.basename(path)
        try:
            with open(path, "rb") as f:
                files[fn] = f.read()
        except OSError as e:
            raise ValueError(f"{fn}: unreadable ({type(e).__name__}: {e})") from None
    settings = mod.meta.get("settings")
    settings = settings if isinstance(settings, dict) else {}
    h = hashlib.sha256()
    for fn in sorted(files):
        h.update(fn.encode() + b"\0" + files[fn] + b"\0")
    h.update(json.dumps(settings, sort_keys=True, default=str).encode())
    return {"files": files, "settings": settings, "fingerprint": h.hexdigest()}


def fingerprint(mod):
    """sha256 of what the approval covers: every patches/exe file (name and bytes) and the mod's settings"""
    return snapshot(mod)["fingerprint"]


def _approvals_file(folder):
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(folder))), APPROVALS)


def _approved_map(folder):
    try:
        with open(_approvals_file(folder), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def is_approved(mod, snap=None):
    """True when the approval on file matches these exact patch bytes and settings (a snapshot read once, or read now);
    an unreadable patch file is simply not approved (the build says why, by name)"""
    try:
        snap = snap if snap is not None else snapshot(mod)
    except ValueError:
        return False
    return _approved_map(mod.folder).get(mod.id) == snap["fingerprint"]


def _save(folder, d):
    path = _approvals_file(folder)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, path)


def approve(mod):
    d = _approved_map(mod.folder)
    d[mod.id] = fingerprint(mod)
    _save(mod.folder, d)


def revoke(mod):
    d = _approved_map(mod.folder)
    if d.pop(mod.id, None) is not None:
        _save(mod.folder, d)


NOT_APPROVED = ("carries patches to the game's program (machine code) and is not approved: approve it in the kit "
                "(confirmed on import) to let it in")


def assess(mod):
    """(snapshot, "") when the mod may be built (no patches/exe, or exactly the bytes and settings a build would apply
    are the approved ones), else (the snapshot or None, why not).  This is the one read: a build keeps the snapshot
    it approved here and applies those same bytes, so an edit between the check and the apply can't slip through.
    An unreadable patch file is a whole-mod skip with its name in the reason, not an exception."""
    if not carries(mod):
        return None, ""
    try:
        snap = snapshot(mod)
    except ValueError as e:
        return None, f"its patches to the game's program can't be read: {e}"
    return snap, ("" if is_approved(mod, snap) else NOT_APPROVED)


def consent_problem(mod):
    """"" when the mod may be built, else why not (it carries game-program patches nobody approved)"""
    return assess(mod)[1]


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


def load(mod, snap=None):
    """the mod's entries: [{"va", "orig", "new" (settings applied), "what"}]; ValueError (naming file, entry and
    field) when the data is malformed or can't apply to this build.  Nothing else can escape.  `snap` is the
    approved snapshot the build keeps (its exact bytes and settings); absent, the mod's files are read now."""
    snap = snap if snap is not None else snapshot(mod)
    settings = snap["settings"]
    out = []
    for fn, data in sorted(snap["files"].items()):
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError) as e:   # JSONDecodeError and UnicodeDecodeError are ValueErrors
            raise ValueError(f"{fn}: unreadable ({type(e).__name__}: {e})") from None
        if not isinstance(doc, dict) or not isinstance(doc.get("patches", []), list):
            raise ValueError(f"{fn}: expected an object with a list of patches")
        build = doc.get("build")
        if build is not None and build != "":
            if not isinstance(build, str) or not build.strip() or any(c not in "0123456789abcdefABCDEF" for c in build.strip()):
                raise ValueError(f"{fn}: build must be a hex string, not {build!r}")
            if not exemap.ACTIVE.sha1.startswith(build.strip().lower()):
                raise ValueError(f"{fn} is for game build {build}, this one is {exemap.ACTIVE.sha1[:12]}")
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
            if len(new) > MAX_PATCH_BYTES:
                raise ValueError(f"{what}: {len(new)} bytes is over the {MAX_PATCH_BYTES}-byte limit of one patch")
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
    total = sum(len(e["new"]) for e in out)
    if total > MAX_MOD_BYTES:
        raise ValueError(f"the mod's patches/exe total {total} bytes, over the {MAX_MOD_BYTES}-byte limit of one mod")
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


LABEL = "Changes the game's program"


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
    snaps = getattr(ctx, "exe_snapshots", None)      # set by modsys.build: the exact inputs that passed consent
    snaps = snaps if isinstance(snaps, dict) else None
    for f in getattr(ctx, "mod_folders", []) or []:
        mod = Mod(f)
        owner = f"mod {mod.id}"        # the folder id is unique (display names are not); never a kit feature's name
        shown = f"{mod.name} ({mod.id})" if mod.name != mod.id else mod.id
        try:
            if snaps is None:                    # a direct call (tests): read now, as before
                snap = snapshot(mod)
            else:
                snap = snaps.get(mod.id)
                if snap is None:                 # not carrying patches when the build checked it: a new file is not approved
                    snap, why = assess(mod)
                    if why:
                        raise ValueError(why)
                    if snap is None:                 # still carries nothing: nothing to apply, and no unchecked second read
                        continue
            entries = load(mod, snap)
            if not entries:
                continue
            base = base or ctx.get(EXE_FILE)
            cur = apply(cur or base, entries, owner, base)
        except ValueError as e:
            exemap.release(owner)
            ctx.skipped_features = getattr(ctx, "skipped_features", []) + [(f"mod {shown}", str(e))]
            ctx.log(f"  warning: exe patches of {shown} can't apply: {e}")
            if not hasattr(ctx, "drop_mods"):
                ctx.drop_mods = {}
            ctx.drop_mods[mod.id] = (f"mod {shown}", str(e))      # modsys.build builds again without the whole mod
            continue
        if snaps is not None:                # what the build actually applied, for the log and the tests
            ctx.exe_applied = getattr(ctx, "exe_applied", {})
            ctx.exe_applied[mod.id] = snap["fingerprint"]
        size = sum(len(e["orig"]) for e in entries)       # from the applied entries: no second read of the files
        ctx.log(f"  {mod.name}: patches the game's code at {len(entries)} sites ({size} bytes)")
    if cur:
        ctx.put(EXE_FILE, cur)


register_finalizer(_finalize)
