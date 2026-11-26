"""FIXUP1: validate a staged mod folder without writing into it.

`modsys.build` runs finalizers that write back into their input Mods (outfits._declare_icon_cells records the icon
pairs in outfits.json), so building the staged folder itself changed Zed's icons 13363/14180 -> 13173/13990 after
the stage receipt was written.  `build_check` builds disposable clones; `verify_stage` re-hashes the staged tree
against the receipt.  Production builds keep persisting icon claims."""
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tree_hashes(folder):
    folder = Path(folder)
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def build_check(fs, folders, extra=(), log=None, work=None):
    """modsys.build on clones of `extra` (read-only context, e.g. installed Outfit_System) + `folders`; the
    originals are hashed before and after and must not change.  Returns the build's result."""
    from . import modsys
    folders = [Path(f) for f in folders]
    extra = [Path(f) for f in extra]
    before = {f: tree_hashes(f) for f in folders + extra}
    tmp = Path(tempfile.mkdtemp(prefix="stagecheck-", dir=work))
    try:
        mods = []
        for f in extra + folders:
            c = tmp / f.name
            subprocess.run(["cp", "-cR", str(f), str(c)], check=True)
            mods.append(modsys.Mod(str(c)))
        result = modsys.build(fs, mods, log=log or (lambda *a: None))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    changed = []
    for f, h in before.items():
        t = tree_hashes(f)
        changed += [f"{f.name}/{k}" for k in sorted(h.keys() | t.keys()) if h.get(k) != t.get(k)]
    if changed:
        raise RuntimeError(f"validation wrote into its input: {changed[:5]}")
    return result


def verify_stage(out):
    """Every file the receipt hashed (`staged_sha256`, else `identical_sha256`) still has that hash -> mismatches."""
    import json
    out = Path(out)
    receipt = json.loads((out / "STAGE-RECEIPT.json").read_text())
    bad = []
    for p in receipt["packs"]:
        want = p.get("staged_sha256") or p.get("identical_sha256") or {}
        for rel, h in want.items():
            f = out / "mods" / p["folder"] / rel
            if not f.is_file() or sha(f) != h:
                bad.append(f"{p['folder']}/{rel}")
    return bad
