"""Posting mods to the community list, and reviewing posts, from inside the kit (no git, no GitHub pages).

Sign-in: GitHub's device flow for an OAuth app (CLIENT_ID is public, there is no secret): the kit shows a short code,
the player opens github.com/login/device, types it and allows "D5 Mod Kit".  The token (scope public_repo) stays on
this PC, encrypted for this Windows user (DPAPI; elsewhere a file only this user can read).

Posting a mod (post()):
  1. the player's copy of the list repository (a fork; the list's owners use the repository itself), brought up to
     date with the list;
  2. a release in that copy holding the mod's zip (its download address is github.com/...: allowed by the list);
  3. a branch with the entry put into index.json (the mod's earlier entry replaced: an update) and the picture in
     previews/<uid>.png;
  4. a pull request to the list ("Post: <name> v<version>").  The list's check downloads it and runs the rules; a
     maintainer looks at it in the kit's Review tab and publishes (merges) or declines it.
An entry records the GitHub account that posted it ("github"); an update posted by another account is flagged in
review (the list's check refuses it too).
"""
import base64
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import modindex

CLIENT_ID = "Ov23liTJJaqgnbUFBhz6"                       # the "D5 Mod Kit" OAuth app (Device Flow on): set by the maintainer
SCOPE = "public_repo"
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
UA = "D5ModKit-post"
PREVIEW_SIZE = (640, 360)


class PostError(RuntimeError):
    pass


def client_id(settings=None):
    return (settings or {}).get("github_client_id") or os.environ.get("D5_GITHUB_CLIENT_ID") or CLIENT_ID


def upstream():
    owner, name = modindex.INDEX_REPO.split("/")
    return owner, name


# ------------------------------------------------------------------------------------------------ the token
def _token_path(kit_dir):
    return os.path.join(kit_dir, "state", "github_token.bin")


def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    inp, out = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("Windows could not (un)protect the GitHub sign-in")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def save_token(kit_dir, token):
    p = _token_path(kit_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = token.encode()
    if os.name == "nt":
        data = b"DPAPI" + _dpapi(data, True)
    with open(p, "wb") as f:
        f.write(data)
    if os.name != "nt":
        os.chmod(p, 0o600)


def load_token(kit_dir):
    if os.environ.get("D5_GITHUB_TOKEN"):                    # tests
        return os.environ["D5_GITHUB_TOKEN"]
    p = _token_path(kit_dir)
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        data = f.read()
    try:
        if data.startswith(b"DPAPI"):
            data = _dpapi(data[5:], False)
        return data.decode() or None
    except Exception:
        return None


def sign_out(kit_dir):
    try:
        os.remove(_token_path(kit_dir))
    except OSError:
        pass


# ------------------------------------------------------------------------------------------------ device flow
def _form(url, fields, timeout=20):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def device_start(cid):
    """-> {"user_code", "verification_uri", "device_code", "interval", "expires_in"}"""
    if not cid:
        raise PostError("posting isn't set up in this copy of the kit yet (no GitHub app id)")
    d = _form("https://github.com/login/device/code", {"client_id": cid, "scope": SCOPE})
    if "user_code" not in d:
        raise PostError(d.get("error_description") or "GitHub refused the sign-in")
    return d


def device_wait(cid, start, cancelled=lambda: False):
    """poll until the player allowed the kit -> token (None when cancelled / expired)"""
    interval = int(start.get("interval", 5))
    end = time.time() + int(start.get("expires_in", 900))
    while time.time() < end and not cancelled():
        time.sleep(interval)
        d = _form("https://github.com/login/oauth/access_token",
                  {"client_id": cid, "device_code": start["device_code"],
                   "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if d.get("access_token"):
            return d["access_token"]
        err = d.get("error")
        if err == "slow_down":
            interval += 5
        elif err not in ("authorization_pending",):
            raise PostError(d.get("error_description") or err or "sign-in failed")
    return None


# ------------------------------------------------------------------------------------------------ REST
class GitHub:
    def __init__(self, token):
        self.token = token
        self._login = None

    def call(self, method, path, body=None, raw=None, ctype=None, base=API, ok=(200, 201, 202, 204), timeout=60):
        url = path if path.startswith("https://") else base + path
        h = {"Accept": "application/vnd.github+json", "User-Agent": UA, "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        elif raw is not None:
            data = raw
            h["Content-Type"] = ctype or "application/octet-stream"
            h["Content-Length"] = str(len(raw))
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                txt = r.read().decode() if r.status != 204 else ""
                return json.loads(txt) if txt else {}
        except urllib.error.HTTPError as e:
            if e.code in ok:
                return {}
            msg = e.read().decode("utf-8", "replace")
            try:
                msg = json.loads(msg).get("message", msg)
            except ValueError:
                pass
            if e.code == 401:
                raise PostError("the GitHub sign-in isn't valid any more: sign in again")
            err = PostError(f"GitHub: {msg} ({method} {path.split('?')[0]}, {e.code})")
            err.code = e.code
            raise err

    def login(self):
        if self._login is None:
            self._login = self.call("GET", "/user")["login"]
        return self._login

    def can_maintain(self):
        o, n = upstream()
        try:
            return bool(self.call("GET", f"/repos/{o}/{n}").get("permissions", {}).get("push"))
        except PostError:
            return False


def _b64(data):
    return base64.b64encode(data).decode()


# ------------------------------------------------------------------------------------------------ posting
def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:40] or "mod"


def make_preview(image_path):
    """a 640 x 360 PNG (cover-fit) under 1 MB from any picture"""
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    W, H = PREVIEW_SIZE
    s = max(W / img.width, H / img.height)
    img = img.resize((max(W, round(img.width * s)), max(H, round(img.height * s))), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((x, y, x + W, y + H))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    if buf.tell() > 900_000:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _repo_for(gh):
    """(owner, name) of the repository the post goes to: the list itself for its maintainers, else a fork"""
    o, n = upstream()
    me = gh.login()
    if me.lower() == o.lower() or gh.can_maintain():
        return o, n
    try:
        gh.call("GET", f"/repos/{me}/{n}")
    except PostError as e:
        if getattr(e, "code", 0) != 404:
            raise
        gh.call("POST", f"/repos/{o}/{n}/forks", {"default_branch_only": True})
        for _ in range(30):
            time.sleep(2)
            try:
                gh.call("GET", f"/repos/{me}/{n}/git/ref/heads/main")
                break
            except PostError:
                continue
        else:
            raise PostError("GitHub is still making your copy of the mod list: try again in a minute")
    try:
        gh.call("POST", f"/repos/{me}/{n}/merge-upstream", {"branch": "main"}, ok=(200, 409))
    except PostError:
        pass
    return me, n


def post(gh, zip_path, entry, preview_png=None, progress=lambda text: None):
    """put a mod on the list (see the module doc) -> the pull request's address.
    entry: from modindex.entry_for (its download address is filled in here)."""
    o, n = upstream()
    me = gh.login()
    progress("Getting your copy of the mod list ready…")
    ro, rn = _repo_for(gh)
    tag = f"{slug(entry['name'])}-v{slug(entry['version'])}-{entry['uid'][:8]}-{int(time.time())}"
    progress("Uploading the mod…")
    rel = gh.call("POST", f"/repos/{ro}/{rn}/releases",
                  {"tag_name": tag, "name": f"{entry['name']} v{entry['version']}",
                   "body": f"{entry.get('summary', '')}\n\nPosted with D5 Mod Kit by {me}.", "prerelease": False})
    with open(zip_path, "rb") as f:
        data = f.read()
    if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != int(entry["size"]):
        raise PostError("the package changed after its entry was made")
    asset_name = f"{slug(entry['name'])}_v{slug(entry['version'])}.zip"
    asset = gh.call("POST", f"{UPLOADS}/repos/{ro}/{rn}/releases/{rel['id']}/assets?name={asset_name}",
                    raw=data, ctype="application/zip", timeout=900)
    entry = dict(entry, download=asset["browser_download_url"], github=me,
                 updated=time.strftime("%Y-%m-%d"))
    if preview_png:
        entry["preview"] = f"previews/{entry['uid']}.png"
    problems = modindex.entry_problems(entry)
    if problems:
        raise PostError("the entry isn't valid: " + "; ".join(problems))
    progress("Adding it to the list…")
    base_sha = gh.call("GET", f"/repos/{ro}/{rn}/git/ref/heads/main")["object"]["sha"]
    branch = f"post/{slug(entry['name'])}-{entry['uid'][:8]}-{int(time.time())}"
    gh.call("POST", f"/repos/{ro}/{rn}/git/refs", {"ref": f"refs/heads/{branch}", "sha": base_sha})
    cur = gh.call("GET", f"/repos/{ro}/{rn}/contents/index.json?ref={urllib.parse.quote(branch)}")
    idx = json.loads(base64.b64decode(cur["content"]).decode("utf-8"))
    mods = [m for m in idx.get("mods", []) if m.get("uid") != entry["uid"]]
    old = next((m for m in idx.get("mods", []) if m.get("uid") == entry["uid"]), None)
    mods.append(entry)
    mods.sort(key=lambda m: (m.get("name") or "").lower())
    idx["mods"] = mods
    text = json.dumps(idx, indent=1, ensure_ascii=False) + "\n"
    what = f"{'Update' if old else 'Post'}: {entry['name']} v{entry['version']}"
    gh.call("PUT", f"/repos/{ro}/{rn}/contents/index.json",
            {"message": what, "content": _b64(text.encode("utf-8")), "sha": cur["sha"], "branch": branch})
    if preview_png:
        path = f"previews/{entry['uid']}.png"
        body = {"message": f"{what} (picture)", "content": _b64(preview_png), "branch": branch}
        try:
            body["sha"] = gh.call("GET", f"/repos/{ro}/{rn}/contents/{path}?ref={urllib.parse.quote(branch)}")["sha"]
        except PostError:
            pass
        gh.call("PUT", f"/repos/{ro}/{rn}/contents/{path}", body)
    progress("Sending it for review…")
    pr = gh.call("POST", f"/repos/{o}/{n}/pulls",
                 {"title": what, "head": branch if ro == o else f"{me}:{branch}", "base": "main",
                  "body": (f"**{entry['name']}** v{entry['version']} by {entry['author']} ({entry.get('category', '')})"
                           f"\n\n{entry.get('summary', '')}\n\n{entry.get('description', '')}\n\n"
                           f"Posted with D5 Mod Kit {entry.get('kit', '')} by @{me}.")})
    return pr["html_url"]


# ------------------------------------------------------------------------------------------------ status, review
def my_posts(gh):
    """[{title, url, state: 'waiting' | 'published' | 'declined', comment}] of the signed-in player's posts"""
    o, n = upstream()
    q = urllib.parse.quote(f"repo:{o}/{n} is:pr author:{gh.login()}")
    out = []
    for it in gh.call("GET", f"/search/issues?q={q}&sort=created&order=desc&per_page=30").get("items", []):
        st = "waiting" if it["state"] == "open" else (
            "published" if (it.get("pull_request") or {}).get("merged_at") else "declined")
        out.append({"title": it["title"], "url": it["html_url"], "state": st, "number": it["number"]})
    return out


def submissions(gh):
    """the open posts, each with its changed entries and the list check's result:
    [{number, title, url, author, entries: [entry], removed: [uid], check: 'passed'|'failed'|'running'|'none',
      flags: [text]}]"""
    o, n = upstream()
    main = json.loads(urllib.request.urlopen(urllib.request.Request(
        modindex.base_url() + "index.json", headers={"User-Agent": UA}), timeout=20).read().decode())
    base = {m.get("uid"): m for m in main.get("mods", [])}
    out = []
    for pr in gh.call("GET", f"/repos/{o}/{n}/pulls?state=open&per_page=50"):
        head = pr["head"]
        item = {"number": pr["number"], "title": pr["title"], "url": pr["html_url"],
                "author": pr["user"]["login"], "entries": [], "removed": [], "flags": [], "check": "none"}
        try:
            raw = urllib.request.urlopen(urllib.request.Request(
                f"https://raw.githubusercontent.com/{head['repo']['full_name']}/{head['sha']}/index.json",
                headers={"User-Agent": UA}), timeout=20).read().decode()
            idx = json.loads(raw)
        except Exception as e:
            item["flags"].append(f"its index.json can't be read: {e}")
            idx = {"mods": []}
        now = {m.get("uid"): m for m in idx.get("mods", [])}
        for uid, m in now.items():
            if base.get(uid) != m:
                item["entries"].append(m)
                was = base.get(uid)
                if was and was.get("github") and was["github"].lower() != item["author"].lower():
                    item["flags"].append(f"'{m.get('name')}' was posted by {was['github']}: this update comes "
                                         f"from {item['author']}")
                probs = modindex.entry_problems(m)
                if probs:
                    item["flags"].append(f"'{m.get('name')}': " + "; ".join(probs))
        item["removed"] = [u for u in base if u not in now]
        try:
            runs = gh.call("GET", f"/repos/{o}/{n}/commits/{head['sha']}/check-runs").get("check_runs", [])
            if runs:
                if any(r["status"] != "completed" for r in runs):
                    item["check"] = "running"
                else:
                    item["check"] = "passed" if all(r["conclusion"] in ("success", "skipped", "neutral")
                                                    for r in runs) else "failed"
        except PostError:
            pass
        out.append(item)
    return out


def publish(gh, number):
    o, n = upstream()
    gh.call("PUT", f"/repos/{o}/{n}/pulls/{number}/merge", {"merge_method": "squash"})


def decline(gh, number, reason):
    o, n = upstream()
    if reason:
        gh.call("POST", f"/repos/{o}/{n}/issues/{number}/comments", {"body": reason})
    gh.call("PATCH", f"/repos/{o}/{n}/pulls/{number}", {"state": "closed"})


def remove_listing(gh, uid, reason=""):
    """take a mod off the list (maintainers): a commit to main without its entry"""
    o, n = upstream()
    cur = gh.call("GET", f"/repos/{o}/{n}/contents/index.json")
    idx = json.loads(base64.b64decode(cur["content"]).decode("utf-8"))
    gone = [m for m in idx.get("mods", []) if m.get("uid") == uid]
    if not gone:
        return False
    idx["mods"] = [m for m in idx["mods"] if m.get("uid") != uid]
    gh.call("PUT", f"/repos/{o}/{n}/contents/index.json",
            {"message": f"Remove: {gone[0].get('name')}" + (f" ({reason})" if reason else ""),
             "content": _b64((json.dumps(idx, indent=1, ensure_ascii=False) + "\n").encode()), "sha": cur["sha"]})
    try:                                                   # and its picture
        pic = gh.call("GET", f"/repos/{o}/{n}/contents/previews/{uid}.png")
        gh.call("DELETE", f"/repos/{o}/{n}/contents/previews/{uid}.png",
                {"message": f"Remove: {gone[0].get('name')} (picture)", "sha": pic["sha"]})
    except PostError:
        pass
    return True
