"""Updating the kit in place from its GitHub releases, without downloading everything again.

Every release carries manifest.json (in the kit folder: every file it shipped with its SHA-1, and the version) and,
next to the full zip, a small update zip for the release before it ("D5ModKit-update-<old>-to-<new>.zip", made by
tools/make_release.py --previous): only the files that changed or are new, the files removed, and the new manifest.

    latest()            the newest release on GitHub (version, notes, its assets)
    update_asset(info)  the update zip for this kit's version, or None (another version: the full zip it is)
    apply(zip)          writes the update over the kit: files the player changed are backed up first
                        (state/update_backups/<version>/); files in use (a loaded DLL) are written as .new and swapped
                        in by apply_pending() at the next start (D5ModKit.pyw runs it before anything else)

Only the standard library is used here: the launcher imports this before the rest of the kit.
"""
import hashlib
import json
import os
import shutil
import urllib.request
import zipfile

REPO = "eraser4521/D5ModKit"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases"
MANIFEST = "manifest.json"
PENDING = os.path.join("state", "update_pending.json")
KEEP = ("settings.json", "state/", "profiles/", "mods/load_order.json", "mods/packs.json")   # the player's own


def version_tuple(v):
    out = []
    for p in str(v).lstrip("vV").split("."):
        digits = "".join(c for c in p if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def newer(a, b):
    """is version a newer than b"""
    return version_tuple(a) > version_tuple(b)


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "D5ModKit-updater",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest(timeout=15):
    """the newest release -> dict(version, tag, url, notes, assets {name: (download url, size)})"""
    d = json.loads(_get(API, timeout).decode("utf-8"))
    return {"version": d.get("tag_name", "").lstrip("vV"), "tag": d.get("tag_name", ""),
            "url": d.get("html_url") or RELEASES, "notes": d.get("body") or "",
            "assets": {a["name"]: (a["browser_download_url"], int(a.get("size") or 0)) for a in d.get("assets", [])}}


def update_name(old, new):
    return f"D5ModKit-update-{old}-to-{new}.zip"


def update_asset(info, current):
    """(download url, size) of the update zip from `current` to the release, or None"""
    return info["assets"].get(update_name(current, info["version"]))


def download(url, dest, progress=None, chunk=1 << 20):
    """-> dest; progress(done bytes, total bytes)"""
    req = urllib.request.Request(url, headers={"User-Agent": "D5ModKit-updater"})
    tmp = dest + ".part"
    with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            b = r.read(chunk)
            if not b:
                break
            f.write(b)
            done += len(b)
            if progress:
                progress(done, total)
    os.replace(tmp, dest)
    return dest


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_manifest(kit_dir):
    try:
        with open(os.path.join(kit_dir, MANIFEST), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"version": None, "files": {}}


def _kept(rel):
    rel = rel.replace("\\", "/")
    return any(rel == k or (k.endswith("/") and rel.startswith(k)) for k in KEEP)


def apply(zip_path, kit_dir, log=print):
    """write an update zip over the kit -> dict(version, written, backed_up, pending)"""
    old = load_manifest(kit_dir)
    old_files = old.get("files", {})
    with zipfile.ZipFile(zip_path) as z:
        info = json.loads(z.read("update.json").decode("utf-8"))
        if old.get("version") and info.get("from") and old["version"] != info["from"]:
            raise RuntimeError(f"this update is for version {info['from']}; the kit is {old['version']}")
        to = info["to"]
        backup = os.path.join(kit_dir, "state", "update_backups", to)
        written, backed, pending = [], [], {}

        def keep_copy(rel, path):
            if os.path.exists(path) and old_files.get(rel) and sha1_file(path) != old_files[rel]:
                dst = os.path.join(backup, *rel.split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(path, dst)
                backed.append(rel)
        for rel in info.get("files", []):
            if _kept(rel):
                continue
            path = os.path.join(kit_dir, *rel.split("/"))
            keep_copy(rel, path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = z.read("files/" + rel)
            tmp = path + ".upd"
            with open(tmp, "wb") as f:
                f.write(data)
            try:
                os.replace(tmp, path)
            except PermissionError:                     # in use (a loaded DLL): swapped in at the next start
                os.replace(tmp, path + ".new")
                pending[rel] = rel + ".new"
            written.append(rel)
        for rel in info.get("removed", []):
            if _kept(rel):
                continue
            path = os.path.join(kit_dir, *rel.split("/"))
            if os.path.exists(path):
                keep_copy(rel, path)
                try:
                    os.remove(path)
                except PermissionError:
                    pending[rel] = None
        with open(os.path.join(kit_dir, MANIFEST), "w", encoding="utf-8") as f:
            json.dump(info["manifest"], f, indent=0)
    if pending:
        p = os.path.join(kit_dir, PENDING)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(pending, f)
    if log:
        log(f"Updated to {to}: {len(written)} file(s)" + (f", {len(backed)} of your changes backed up in "
                                                           f"state/update_backups/{to}" if backed else "")
            + (f", {len(pending)} finished at the next start" if pending else ""))
    return {"version": to, "written": written, "backed_up": backed, "pending": pending}


def apply_pending(kit_dir):
    """finish an update: files that were in use are swapped in (run before the kit loads anything)"""
    p = os.path.join(kit_dir, PENDING)
    if not os.path.exists(p):
        return
    try:
        with open(p, encoding="utf-8") as f:
            pending = json.load(f)
    except (OSError, ValueError):
        pending = {}
    left = {}
    for rel, new in pending.items():
        path = os.path.join(kit_dir, *rel.split("/"))
        try:
            if new is None:
                if os.path.exists(path):
                    os.remove(path)
            else:
                os.replace(os.path.join(kit_dir, *new.split("/")), path)
        except OSError:
            left[rel] = new
    if left:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(left, f)
    else:
        os.remove(p)


# ------------------------------------------------------------------------------------------------ making updates
def make_manifest(folder, version):
    """{version, files {relative path: sha1}} of a release folder (the player's own files left out)"""
    files = {}
    for dp, dns, fns in os.walk(folder):
        dns.sort()
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, folder).replace(os.sep, "/")
            if rel == MANIFEST or _kept(rel):
                continue
            files[rel] = sha1_file(p)
    return {"version": version, "files": files}


def make_update(folder, new_manifest, old_manifest, out_path):
    """the update zip from old_manifest's release to the release in `folder` -> (files, removed)"""
    old_f, new_f = old_manifest.get("files", {}), new_manifest["files"]
    changed = [r for r, h in new_f.items() if old_f.get(r) != h]
    removed = [r for r in old_f if r not in new_f]
    info = {"from": old_manifest.get("version"), "to": new_manifest["version"], "files": changed,
            "removed": removed, "manifest": new_manifest}
    tmp = out_path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        z.writestr("update.json", json.dumps(info))
        for r in changed:
            z.write(os.path.join(folder, *r.split("/")), "files/" + r)
    os.replace(tmp, out_path)
    return changed, removed
