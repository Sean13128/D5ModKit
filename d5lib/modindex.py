"""Browse Mods: the community mod list (a public GitHub repository) and safe downloads from it.

The list is one file, index.json, in the repository INDEX_REPO (anyone can read it without an account; entries are
added by pull request and reviewed before they are listed):

    {"format": 1,
     "mods": [{"uid": "<the mod's uid (mod.json)>", "name": "...", "author": "...", "version": "1.2",
               "category": "Character", "summary": "one line", "description": "a few lines",
               "tags": ["..."], "requires": ["<uid>", ...], "kit": "1.5.7",
               "preview": "previews/<uid>.png", "page": "https://...",
               "download": "https://github.com/<owner>/<repo>/releases/download/<tag>/<file>.zip",
               "size": 1234567, "sha256": "<hex>", "updated": "2026-10-21"}]}

Safety (a mod is data; the kit makes every piece of code itself):
  * the list and the previews come from raw.githubusercontent.com over HTTPS; a download only from github.com /
    its release storage or raw.githubusercontent.com (the final address after redirects is checked too);
  * a download must have the listed size (at most MAX_DOWNLOAD) and SHA-256, else it is thrown away;
  * the zip is checked before anything is unpacked (check_zip): one mod folder, plain relative paths, only the
    file types mods use (game data, pictures, sound, text), no program files for the game folder, size limits
    against zip bombs;
  * then it goes through the normal import (modshare.import_package: updates by uid, moved ids, backups).
"""
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

INDEX_REPO = "eraser4521/D5ModKit-Mods"
BRANCH = "main"
RAW = f"https://raw.githubusercontent.com/{INDEX_REPO}/{BRANCH}/"
INDEX_URL = RAW + "index.json"
SUBMIT_URL = f"https://github.com/{INDEX_REPO}#submit-a-mod"
FORMAT = 1
CATEGORIES = ["Character", "Outfit", "Class", "Monster", "Stage", "Skill", "Music", "Text", "Gameplay", "Other"]

ALLOWED_HOSTS = {"github.com", "raw.githubusercontent.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com"}
MAX_INDEX = 8 << 20                # the list itself
MAX_PREVIEW = 4 << 20
MAX_DOWNLOAD = 2 << 30             # a mod zip
MAX_FILE = 512 << 20               # one file inside it, unpacked
MAX_TOTAL = 4 << 30                # everything inside it, unpacked
MAX_RATIO = 400                    # unpacked / packed, per file (zip bombs)
MAX_FILES = 50000
ALLOWED_EXT = {
    ".json", ".txt", ".md",                                         # patches, notes
    ".lzs", ".anm", ".obf", ".txf", ".dat", ".chr", ".hex", ".gop", ".pac", ".bin", ".ogg", ".vag",  # game data
    ".png", ".jpg", ".jpeg", ".webp", ".bmp",                       # pictures (faces, portraits, sheets)
    ".wav", ".flac", ".mp3",                                        # sound sources
}
UA = {"User-Agent": "D5ModKit-browse"}


class UnsafeMod(ValueError):
    """a download or a zip that failed a safety check"""


# ------------------------------------------------------------------------------------------------ fetching
def _check_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme == "file" and os.environ.get("D5_MODINDEX_LOCAL"):        # tests: a local copy of the repository
        return
    if u.scheme != "https" or (u.hostname or "").lower() not in ALLOWED_HOSTS:
        raise UnsafeMod(f"not an address the mod list may use: {url}")


def _open(url, timeout):
    _check_url(url)
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)
    _check_url(r.geturl())                                                 # where the redirects ended up
    return r


def _read(url, limit, timeout=20):
    with _open(url, timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise UnsafeMod(f"{url}: bigger than {limit >> 20} MB")
    return data


_head = {"sha": None, "at": 0.0}


def _latest_sha(timeout=10):
    """the list's newest commit (GitHub's API, a few hundred bytes; at most once a minute): raw files of 'main' are
    cached up to 5 minutes, the files of a commit never change"""
    if time.time() - _head["at"] < 60 and _head["sha"]:
        return _head["sha"]
    req = urllib.request.Request(f"https://api.github.com/repos/{INDEX_REPO}/commits/{BRANCH}",
                                 headers=dict(UA, Accept="application/vnd.github.sha"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        sha = r.read(100).decode().strip()
    if not re.match(r"^[0-9a-f]{40}$", sha):
        raise ValueError("no commit id")
    _head.update(sha=sha, at=time.time())
    return sha


def base_url():
    """the repository's raw address at its newest commit (D5_MODINDEX_LOCAL=folder: a local copy, for tests)"""
    local = os.environ.get("D5_MODINDEX_LOCAL")
    if local:
        return "file:" + urllib.request.pathname2url(os.path.abspath(local)) + "/"
    try:
        return f"https://raw.githubusercontent.com/{INDEX_REPO}/{_latest_sha()}/"
    except Exception:
        return RAW


def fetch_index(cache_dir=None, timeout=20):
    """the mod list -> {"mods": [entry, ...], "fetched": time, "offline": bool}.  The last good copy is kept in
    cache_dir and returned (offline=True) when the list can't be reached."""
    path = os.path.join(cache_dir, "index.json") if cache_dir else None
    try:
        data = _read(base_url() + "index.json", MAX_INDEX, timeout)
        idx = parse_index(data)
        if path:
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        idx["offline"] = False
        return idx
    except Exception as e:
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                idx = parse_index(f.read())
            idx["offline"] = True
            idx["error"] = str(e)
            return idx
        raise


def parse_index(data):
    d = json.loads(data.decode("utf-8"))
    if int(d.get("format", 0)) > FORMAT:
        raise ValueError("the mod list is newer than this kit: update the kit")
    mods = []
    for e in d.get("mods") or []:
        problems = entry_problems(e)
        if not problems:
            mods.append(e)
    return {"mods": mods, "fetched": time.time()}


HEX64 = re.compile(r"^[0-9a-f]{64}$")


def entry_problems(e):
    """what is wrong with an index entry ([] = fine); the repository's check runs the same rules"""
    out = []
    for k in ("uid", "name", "author", "version", "download", "sha256", "size"):
        if not e.get(k):
            out.append(f"missing '{k}'")
    if e.get("sha256") and not HEX64.match(str(e["sha256"]).lower()):
        out.append("sha256 is not 64 hex digits")
    try:
        if not 0 < int(e.get("size", 0)) <= MAX_DOWNLOAD:
            out.append("size out of range")
    except (TypeError, ValueError):
        out.append("size is not a number")
    for k in ("download", "page"):
        if e.get(k):
            try:
                _check_url(e[k]) if k == "download" else None
            except UnsafeMod as ex:
                out.append(str(ex))
    if e.get("category") and e["category"] not in CATEGORIES:
        out.append(f"unknown category {e['category']!r}")
    return out


def preview(entry, cache_dir, timeout=15):
    """the entry's preview picture (bytes, cached) or None"""
    p = entry.get("preview")
    if not p:
        return None
    url = p if p.startswith("https://") else base_url() + p.lstrip("/")
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + os.path.splitext(p)[1][:5]
    path = os.path.join(cache_dir, "previews", name)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    try:
        data = _read(url, MAX_PREVIEW, timeout)
    except Exception:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return data


def download(entry, folder, progress=None, timeout=60):
    """the entry's zip into `folder` -> path; its size and SHA-256 must be the listed ones, and the zip must pass
    check_zip.  progress(done, total) is called while it downloads."""
    size, want = int(entry["size"]), str(entry["sha256"]).lower()
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".zip", dir=folder)
    h = hashlib.sha256()
    done = 0
    try:
        with os.fdopen(fd, "wb") as out, _open(entry["download"], timeout) as r:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                done += len(chunk)
                if done > size:
                    raise UnsafeMod("the download is bigger than the mod list says")
                h.update(chunk)
                out.write(chunk)
                if progress:
                    progress(done, size)
        if done != size:
            raise UnsafeMod(f"the download is {done} bytes, the mod list says {size}")
        if h.hexdigest() != want:
            raise UnsafeMod("the download's checksum doesn't match the mod list: it was changed or damaged")
        check_zip(tmp)
        return tmp
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------------------------------------ the zip
def check_zip(path):
    """every check a mod package must pass before anything of it is unpacked -> (top folder, mod.json dict)"""
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise UnsafeMod(f"not a zip file: {e}")
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if not infos:
            raise UnsafeMod("the zip is empty")
        if len(infos) > MAX_FILES:
            raise UnsafeMod("too many files")
        tops = set()
        total = 0
        for i in infos:
            n = i.filename
            parts = n.split("/")
            if n.startswith("/") or "\\" in n or ":" in n or ".." in parts or any(p in ("", ".") for p in parts):
                raise UnsafeMod(f"unsafe path in the zip: {n}")
            if i.flag_bits & 0x1:
                raise UnsafeMod(f"encrypted file in the zip: {n}")
            tops.add(parts[0])
            rel = "/".join(parts[1:])
            ext = os.path.splitext(n)[1].lower()
            if rel != "mod.json" and ext not in ALLOWED_EXT:
                raise UnsafeMod(f"a file type mods don't use: {n}")
            if len(parts) > 2 and parts[1] == "files" and parts[2].upper() in ("EXE", "GAME"):
                raise UnsafeMod(f"a program file for the game folder: {n}")
            if i.file_size > MAX_FILE:
                raise UnsafeMod(f"a file over {MAX_FILE >> 20} MB: {n}")
            if i.compress_size and i.file_size / i.compress_size > MAX_RATIO and i.file_size > (1 << 20):
                raise UnsafeMod(f"a file that unpacks far too big (zip bomb?): {n}")
            total += i.file_size
            if total > MAX_TOTAL:
                raise UnsafeMod(f"more than {MAX_TOTAL >> 30} GB unpacked")
        if len(tops) != 1:
            raise UnsafeMod("the zip must hold exactly one mod folder")
        top = tops.pop()
        try:
            meta = json.loads(z.read(f"{top}/mod.json").decode("utf-8"))
        except KeyError:
            raise UnsafeMod("the zip has no mod.json")
        except ValueError as e:
            raise UnsafeMod(f"mod.json can't be read: {e}")
    return top, meta


# ------------------------------------------------------------------------------------------------ listing
def installed_state(entry, mods):
    """('new' | 'installed' | 'update' | 'newer', the installed Mod or None) of an entry, by uid and version"""
    m = next((x for x in mods if x.meta.get("uid") == entry.get("uid")), None)
    if m is None:
        return "new", None
    have, want = _ver(m.meta.get("version", "")), _ver(entry.get("version", ""))
    if want > have:
        return "update", m
    if want < have:
        return "newer", m
    return "installed", m


def _ver(v):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", str(v or "0")))


def kit_too_old(entry, kit_version):
    """does the entry need a newer kit than this one?"""
    need = entry.get("kit")
    return bool(need) and _ver(need) > _ver(kit_version)


def entry_for(mod, download_url, zip_path, category="Other", summary="", description="", preview_path=""):
    """an index entry for a mod exported to zip_path (what an author pastes into their pull request)"""
    from .version import VERSION
    with open(zip_path, "rb") as f:
        data = f.read()
    _, meta = check_zip(zip_path)
    e = {"uid": meta.get("uid"), "name": meta.get("name") or mod.name, "author": meta.get("author", ""),
         "version": meta.get("version", "1.0"), "category": category, "summary": summary,
         "description": description, "tags": [], "requires": [], "kit": VERSION,
         "download": download_url, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
         "updated": time.strftime("%Y-%m-%d")}
    if preview_path:
        e["preview"] = preview_path
    return e
