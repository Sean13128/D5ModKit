# The community mod list (Browse Mods): setup, testing, reviewing

Players see the list on **🛍 Browse Mods**, post with **📤 Post my mod…** and follow their posts in **📬 My posts**.
The list's maintainers review posts in **🛡 Review posts**. All of it happens in the kit; GitHub only stores the
list (https://github.com/eraser4521/D5ModKit-Mods) and the mods' zips (releases), for free.

Code: `d5lib/modindex.py` (the list, downloads, the package checks), `d5lib/modpost.py` (sign-in, posting,
review), `d5gui/pages/browse.py` (the page and its windows). The list's own check: `tools/check_index.py` and
`.github/workflows/check-index.yml` in the list's repository.

## How it works

* **Browsing / installing** needs no account. The kit reads `index.json` at the list's newest commit (one small
  GitHub API call, then the file at that commit: never a stale copy), shows the pictures, and installs a mod by
  downloading its zip, checking its size and SHA-256 against the entry, checking the package (only mod data: game
  files, pictures, sound, text; no programs, nothing for the game folder, size limits), then importing it like
  Home › Import (an update keeps the mod's ids on this PC, the old version goes to `state/mod_backups`).
* **Posting** needs a free GitHub account. The first time, the kit signs the player in with GitHub's *device flow*:
  it shows a short code, the player pastes it on github.com/login/device and presses Authorize. The kit keeps the
  sign-in on that PC, encrypted for that Windows user (`state/github_token.bin`). Then **Post** does, for the player:
  their copy (fork) of the list, a release in it holding the zip, a branch with the entry in `index.json` and the
  picture in `previews/`, and a pull request to the list. The entry records the GitHub account (`github`).
* **The automatic check** runs on every pull request: the copy of `tools/check_index.py` on `main` (a post can't
  change it) checks every entry and downloads every new or changed mod (size, SHA-256, uid, version, package
  rules). It refuses an update or a removal by another account than the one that posted the mod (the list's owner
  can do both).
* **Review**: the kit's Review window lists the open posts with the check's result and warnings, installs one to
  try (same download checks), and publishes (merges) or declines (closes, with the reason as a comment the poster
  sees in My posts). Published = on everyone's Browse Mods.

## One-time setup (the maintainer)

1. **The GitHub app for signing in** (needed once, free):
   1. github.com → your picture (top right) → **Settings** → **Developer settings** (bottom left) → **OAuth Apps**
      → **New OAuth App**.
   2. Application name `D5 Mod Kit`; Homepage URL `https://github.com/eraser4521/D5ModKit`; Authorization callback
      URL `https://github.com/eraser4521/D5ModKit` (not used by the device flow, but required).
   3. **Register application**, then tick **Enable Device Flow** and press **Update application**.
   4. Copy the **Client ID** (it is public: no secret is ever needed; don't make a client secret).
   5. Put it in `d5lib/modpost.py` as `CLIENT_ID = "..."` and release the kit. (To try it before a release, put
      `"github_client_id": "..."` into `D5ModKit/settings.json`.)
2. **Protect the list's main branch** (recommended): the list's repository → **Settings** → **Branches** → **Add
   branch ruleset** (or protection rule) for `main`: require a pull request before merging and the status check
   **check**. Leave yourself as a bypass actor, so the kit's Publish (a merge) and Take off the list keep working.
3. *(Optional)* to update the list's workflow file later, give the `gh` command line the workflow permission:
   `gh auth refresh -s workflow`.

## Testing it (do this once after setup, and after changing the code)

Use a second GitHub account for the "player" part if you can (the owner's posts skip the fork step).

| step | do | expect |
|---|---|---|
| 1 | Browse Mods on a kit with no sign-in | the list loads (or "No mods to show yet"); the account line says *Not signed in* |
| 2 | **Post my mod…** | the sign-in window with a code; **Open GitHub** opens github.com/login/device with the code copied |
| 3 | paste the code, **Authorize** | the window closes by itself; the account line shows the account |
| 4 | pick a small mod, version, name, kind, summary, a picture, tick the box, **Post** | "Packing… Uploading… Adding it to the list… Sending it for review…", then *posted and waits for review* |
| 5 | **My posts** | the post, *waiting for review* (GitHub's search can take a minute to show it) |
| 6 | as the maintainer: **Review posts** | the post with *Automatic check: passed* after a minute or two (*still running* before) |
| 7 | **Install to try** | downloaded, checked, imported; Install & Play to see it in game |
| 8 | **Publish** | *Published*; on Browse Mods (⟳ Refresh list) it shows within a minute |
| 9 | on another PC / kit: Browse Mods › the mod › **Install** | imported, switched on, the list row shows *installed* |
| 10 | post the same mod again with a higher version | Review shows *Update: …*; once published, the other kit shows **⬆ Update to v…** |
| 11 | from the second account, try to post an update of the first account's mod | the check fails, Review warns *was posted by …* |
| 12 | **Decline…** a post with a reason | My posts shows *declined*; double-click shows the reason |
| 13 | maintainer: select a listed mod › **Take off the list…** | it's gone from Browse Mods (players who have it keep it) |

The kit's own tests: `scratchpad`-style scripts used during development were `browse_smoke.py` (a local copy of the
list: `D5_MODINDEX_LOCAL=<folder>`), `post_e2e.py` (posting / review / install against the real list with
`D5_GITHUB_TOKEN`), `post_gui_e2e.py` (the same through the windows). Bad packages (a DLL, files for the game
folder, an exe, `..` paths, two mod folders, a zip bomb, no mod.json) are refused by `modindex.check_zip`.

## Day to day (the maintainer)

* Open **Browse Mods › 🛡 Review posts** now and then (GitHub also emails you about new pull requests).
* For each post: read what it is, look at the warnings, **Install to try** and look at it in the game, then
  **Publish** — or **Decline…** with a short reason (say what to fix; the poster can post again).
* A listed mod that turns out bad: select it on Browse Mods › **Take off the list…** (players who have it keep it;
  the zip stays in the poster's release).
* What to accept: the poster's own work or work they may share, credited; works in the game; nothing illegal,
  hateful or sexual involving minors. The kit already makes sure a mod can only be data.

## Costs and limits

Free: public GitHub repositories, releases (2 GB per file) and Actions minutes for public repositories. Browsing
makes one GitHub API call per refresh (the limit without an account is 60 an hour per PC) and reads files from
raw.githubusercontent.com (no limit that matters). Posting uses the player's own account.
