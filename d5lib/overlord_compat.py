"""Who owns a byte of game code when Overlord and the Kit both want it (offline policy + gate).

Overlord's own DLLs are loaded through the name the Kit also uses for input (`dinput8.dll`), so once
Overlord is installed *his* runtime is always present; a Kit-only install of his converted content is
not.  Two configurations therefore exist, and each contested site is resolved once, for the whole
build, instead of per patch:

  content   his tables converted into Kit mods, his dinput8.dll / d5_runtime_core.dll / plugins NOT
            installed.  Nothing of his is executing, so the Kit owns every site it patches.
  runtime   his proxy and core installed (and optionally his plugin `d5_visual_runtime_c06c.dll`).
            His code runs whether we plan it or not, so a contested site has to be decided.

The rule is Sean's (2026-10-30 08:15): **where hooks clash, the one that allows MORE capability wins** --
more classes, more evilities, more rows, more colours, more conditions.  It replaces OLCOMPAT2's
"his code keeps his sites" default, so every site below carries what each side allows and the number or
limit the comparison rests on (`his_allows` / `kit_allows`).  A site only goes to a side that is present
in the build *and* implements the feature: a Kit that ships no `steal_on_kill_percent` row does not take
that site away from his runtime.

Where the winner is the Kit, his installer sees changed bytes at his own site and refuses that one hook
(`expected[]` in his source, `d5p_previous` in d5_hooks.c): his feature goes off cleanly, nothing is
half-patched.  Where the winner is his runtime, the Kit writes no patch at all at that site -- hooks are
dropped one by one, so a section keeps its other sites (`.d5id` keeps 94 of 95 identity checks when the
charhelp site is his).

Power / defence / range (the OLEFFECTS double-apply list) are ours by Sean's decision of the same
timestamp: his rows for those three effects must be off while both runtimes are loaded
(`double_apply`), or the bonus lands twice.

`d5lib.exepatch.add_hook_section` and `d5lib.evility.build_patch` consult `filter_hooks`, so every
feature's patch goes through one decision point; the installer calls `configure(ctx)` once the enabled
mods are known and `report(ctx)` at the end.  `verify_yield(exe, vanilla)` is the build-time proof that
the decision reached the bytes.  Nothing here reads or writes a game file.
"""
import json
import os

# --------------------------------------------------------------------------------- capability table
# va -> site.  `winner` is the capability verdict *when both sides are present*; `overlord_in` says what
# has to be loaded for his side to exist at all; `kit_implements` names the Kit evility family without
# which the Kit is not a competitor at an effect site (absent = the Kit always is).
SITES = {
    0x1401A0880: {
        "name": "PORTRAIT_RESOLVER", "section": ".d5fi", "kind": "byte-range",
        "overlord_in": "plugin", "kit_feature": "loose portraits (outfits, imported characters)",
        "his_len": 14, "kit_len": 5,
        "his_allows": "any PNG in any of up to 256 mods' Portraits/{48,64,204} folders; 4,096 files and "
                      "4,096 slots, palette count read from the file (d5_portraits.c: D5P_MAX_MODS 256, "
                      "D5P_MAX_NAMES/FILES/SLOTS 4096, D5P_HASH_SIZE 16384)",
        "kit_allows": "the face pictures the Kit installed, one per class and colour, from Kit mod packs",
        "winner": "overlord",
        "why": "his resolver serves any portrait a player drops in, with a palette count per image; ours "
               "serves only the faces the Kit generated, so his allows more portraits and more colours",
        "loser": "the Kit writes no .d5fi hook at this address (the section keeps its other sites)",
    },
    0x1401A3010: {
        "name": "PORTRAIT_SMALL48", "section": ".d5fi", "kind": "byte-range",
        "overlord_in": "plugin", "kit_feature": "small portraits",
        "his_len": 12, "kit_len": 5,
        "his_allows": "the same loader's 48-pixel list entry, any file count up to its 4,096-file cap, "
                      "palette count per image",
        "kit_allows": "the Kit-installed 48-pixel faces",
        "winner": "overlord",
        "why": "same comparison as PORTRAIT_RESOLVER: his file and slot caps are far above the Kit's "
               "install-generated set",
        "loser": "the Kit writes no hook at this address",
    },
    0x1401C62A0: {
        "name": "UnlockClassTier", "section": ".d5cl", "kind": "byte-range",
        "overlord_in": "wip", "kit_feature": "class unlock tiers (.d5cl)",
        "his_len": 13, "kit_len": 10,
        "his_allows": "nothing in the released build: his WIP `d5_hook_install(0x1C62A0)` is absent from "
                      "dinput8.dll and d5_runtime_core.dll (arbitrate.py --release: 15 of 53 WIP-only "
                      "addresses absent, this one in the hook_install family)",
        "kit_allows": "119 class families (dummies 17283-17408, own families to 17996) through the same "
                      "class-unlock block 17001-17999",
        "winner": "kit",
        "why": "his released code never references the address, so the Kit is the only side with anything "
               "here -- and 119 families is the larger set",
        "loser": "nothing: his release does not patch this site; his v3.5 WIP would fail its own "
                 "signature check and skip this one hook",
    },
    0x14029F753: {
        "name": "CHARHELP", "section": ".d5id", "kind": "byte-range",
        "overlord_in": "always", "kit_feature": "character help text (.d5id)",
        "his_len": 6, "kit_len": 6,
        "his_allows": "every class id >= 10000 gets the authored full-profile charhelp line 3 "
                      "(cmp ecx,2460 -> cmp ecx,10000 / jae, unbounded id count; "
                      "overlord/11_charhelp_soundmsg.c:3-80)",
        "kit_allows": "one of the 95 character-identity comparisons (Majorita, class 2460) remapped so a "
                      "unit wearing an outfit still shows its character's help",
        "winner": "overlord",
        "why": "his rule covers every custom class id and is the whole help feature for them; ours keeps "
               "1 of its 95 identity sites, so losing this one costs one help line while his side would "
               "otherwise lose a feature entirely",
        "loser": "the Kit drops this single hook from .d5id; the other 94 identity sites stay patched",
    },
    0x1404552F1: {
        "name": "CHANGE_COLOR_ROW", "section": ".d5c4", "kind": "byte-range",
        "overlord_in": "plugin", "kit_feature": "Extra Colour 4 (.d5c4)",
        "his_len": 20, "kit_len": 13,
        "his_allows": "palettes 4..9 for a unique character (menu cap 10 colours), counted from the "
                      "portrait files (d5_portraits.c row_vanilla 20 B + d5c_palette_count_c: vanilla 4, "
                      "clamp 2..10)",
        "kit_allows": "palette 4 only (Extra Color 4; 5 colours including Normal)",
        "winner": "overlord",
        "why": "same instruction, same meaning: his patch admits up to ten palettes, ours exactly five",
        "loser": "the Kit writes no .d5c4 hook at this address",
    },
    0x1401AF6A2: {
        "name": "STEAL_ON_KILL_HOOK", "section": ".d5el", "kind": "effect-site",
        "overlord_in": "always", "kit_feature": "steal_on_kill_percent (OLEFFECTS)",
        "his_len": 5, "kit_len": 5, "kit_implements": "steal_on_kill_percent",
        "his_allows": "rows from his evilities.ini only: one section per effect, his condition set, the "
                      "site clamp is 0..100",
        "kit_allows": "the same arithmetic over Kit evility rows: any number of mods, several effect rows "
                      "per id (P3b), the full condition vocabulary (unit, element, target status/class, "
                      "adjacency/map/squad scales), signed 16-bit values, same 0..100 site clamp",
        "winner": "kit",
        "why": "identical arithmetic, strictly more authorable rows -- and his rows for this effect "
               "convert byte-identically into Kit rows, so nothing of his is lost by yielding",
        "loser": "his stolen-byte stub sees a changed 5-byte call and refuses that one hook (its own "
                 "message: 'bytes do not match; steal_on_kill_percent skipped safely')",
    },
    0x140552080: {
        "name": "SP_DRAIN_HOOK", "section": ".d5el", "kind": "effect-site",
        "overlord_in": "always", "kit_feature": "sp_drain_per_turn (OLEFFECTS)",
        "his_len": 11, "kit_len": 5, "kit_implements": "sp_drain_per_turn",
        "his_allows": "his evilities.ini rows, value clamped per row to 0..100 (a negative drain, i.e. SP "
                      "gain at the round edge, cannot be authored)",
        "kit_allows": "the same arithmetic plus negative values (a round-edge SP gain), several rows per "
                      "id, and any Kit mod as a source",
        "winner": "kit",
        "why": "same arithmetic in a wider value and row space; the 11 bytes he takes contain our 5-byte "
               "call at +3, so the site can only have one owner",
        "loser": "his stub sees changed bytes and skips only this hook",
    },
    0x14015DBF0: {
        "name": "OVERLOAD_ID_RESOLVER", "section": ".d5el", "kind": "effect-site",
        "overlord_in": "always", "kit_feature": "block_overload (OLEFFECTS)",
        "his_len": 12, "kit_len": 5, "kit_implements": "block_overload",
        "his_allows": "entry patch answering 0 (= no Overload) for his holders",
        "kit_allows": "11 caller redirects answering 0 for Kit rows; the entry itself is untouched",
        "winner": "both",
        "why": "disjoint bytes (his 12 at the function entry, ours at the callers), so both answers "
               "apply: keeping both is the larger capability and there is no byte conflict to resolve",
        "loser": "nobody -- the two patches do not overlap",
    },
    0x14044A730: {
        "name": "WISH_VISIBILITY", "section": ".d5wr", "kind": "native-hook",
        "overlord_in": "wishes", "kit_feature": "recruit wishes (.d5wr): Strategy Assembly bill predicate",
        "his_len": 15, "kit_len": 15,
        "his_allows": "hook_wish_visibility over his unified wish list (alias, subclass and recruit wishes "
                      "from custom_wishes.txt; overlord/03_subclass_wishes.c install_direct_wish_visibility_hook, "
                      "WISH_VISIBILITY_STOLEN_LEN 15)",
        "kit_allows": "recruit bills only (id >= 2000), one table of (bill, class, level, duplicates)",
        "winner": "overlord",
        "why": "his wish runtime covers the Kit's recruit case and adds alias and subclass wishes; the two "
               "recruit-wish hooks are one feature, so the Kit drops both or neither (a bill that is visible "
               "but has no effect hook would be a dead bill)",
        "loser": "the Kit writes no .d5wr section; its recruit wishes are left to his custom_wishes.txt",
    },
    0x14029CA50: {
        "name": "SUBCLASS_CLASS_TAB", "section": ".d5sb", "kind": "native-hook",
        "overlord_in": "always", "kit_feature": "sub-class from the Status Class tab (.d5sb)",
        "his_len": 12, "kit_len": 12,
        "his_allows": "Confirm/K on the Class tab writes unit +0x35AC = family + min(stars, 5) for a row of "
                      "the game's own list at child +0x1E404, count <= 53, family 1000..3000 "
                      "(overlord/03_subclass_wishes.c install_subclass_class_tab_state_hook, "
                      "subclass_class_tab_assign_owner)",
        "kit_allows": "the same switch over the Kit's relocated 512-entry Class tab list (every imported "
                      "class), rank = the Assembly screen's highest unlocked rank, locked families refused",
        "winner": "kit",
        "why": "once the Kit relocates the Class tab, his hook reads a list the game no longer fills and "
               "caps at 53 rows; the Kit's reads the list the tab shows, up to 512 classes",
        "loser": "his installer sees changed bytes at 0x29CA50 and skips this one hook ('Vanilla bytes did "
                 "not match ... Confirm feature skipped safely'); his Change Subclass hint needs that hook's "
                 "owner and stays hidden",
    },
    0x140221793: {
        "name": "WISH_EFFECT", "section": ".d5wr", "kind": "native-hook",
        "overlord_in": "wishes", "kit_feature": "recruit wishes (.d5wr): bill effect after the vote",
        "his_len": 12, "kit_len": 12,
        "his_allows": "generated per-wish stub chain for alias and direct-recruit wishes "
                      "(install_wish_effect_alias_hook, WISH_EFFECT_ALIAS_STOLEN_LEN 12)",
        "kit_allows": "recruit bills only: roster_create_unit(class, 0, level) on an aligned stack",
        "winner": "overlord",
        "why": "same pairing as WISH_VISIBILITY; his chain handles recruits and aliases together",
        "loser": "the Kit writes no .d5wr section (see WISH_VISIBILITY)",
    },
}

# Effects whose *rows* must be off while his runtime is loaded: the arithmetic would otherwise be
# applied twice (OLEFFECTS-REPORT 2.2).  The first two are the shared sites above; the last three are
# ordered interactions -- his patch is inside (power) or at the entry of (defence, range) the function
# our wrapper calls, so both contributions land and the bonus is doubled.  These three are the Kit's
# (Sean, 2026-10-30 08:15); his copy is the one that switches off.
DOUBLE_APPLY = {
    0x1401AF6A2: ("steal_on_kill_percent", "always"),
    0x140552080: ("sp_drain_per_turn", "always"),
    0x1401F6AA8: ("power", "always"),
    0x1401F8700: ("defense_power", "always"),
    0x1401EC5C0: ("range", "always"),
}

def _present(config):
    runtime = bool(config.get("runtime"))
    plugins = bool(config.get("plugins")) and runtime
    return runtime, plugins


def _implemented(config, family):
    """does this build ship a Kit row for `family`?  (no family set recorded = assume yes)"""
    fams = config.get("families")
    if fams is None:
        return True
    return family in fams


# OLCOMPAT2's answer, kept so the change is auditable (report, receipt, tests): that rule was
# "his code keeps his sites", i.e. always -> his when his runtime is loaded, plugin -> his when the
# plugin is on, wip -> never his.  `was_owner_of` reproduces it exactly; WAS_OWNER is the snapshot for
# the runtime+plugins configuration (what the OLCOMPAT2 report printed).
def was_owner_of(va, config):
    site = SITES.get(int(va))
    if not site:
        return None
    runtime, plugins = _present(config)
    if not runtime:
        return "kit"
    where = site["overlord_in"]
    if where in ("always", "wishes"):
        return "overlord"
    if where == "plugin":
        return "overlord" if plugins else "kit"
    return "kit"


WAS_OWNER = {va: was_owner_of(va, {"runtime": True, "plugins": True}) for va in SITES}
WAS_RULE = "his code keeps his sites (OLCOMPAT2, 2026-10-29), superseded 2026-10-30 08:15"


def owner_of(va, config):
    """'kit' | 'overlord' | 'both' | None -- the owner of a contested site in this configuration."""
    site = SITES.get(int(va))
    if not site:
        return None
    runtime, plugins = _present(config)
    if not runtime:
        return "kit"
    where = site["overlord_in"]
    present = (where == "always" or (where == "plugin" and plugins)
               or (where == "wishes" and bool(config.get("wishes", True))))
    if not present:
        return "kit"                       # 'wip' is never present in a released build
    family = site.get("kit_implements")
    if family and not _implemented(config, family):
        return "overlord"                  # the Kit has nothing at this site in this build
    return site["winner"]


def resolve(config):
    """{va: {name, owner, kind, why, his_allows, kit_allows, loser, was}} for every contested site"""
    out = {}
    for va, site in SITES.items():
        out[va] = dict(site, va=hex(va), owner=owner_of(va, config), was=was_owner_of(va, config))
    return out


def yielded_sites(config):
    """the VAs the Kit must not patch, because his code owns them in this configuration"""
    return {va for va in SITES if owner_of(va, config) == "overlord"}


def changed_sites(config):
    """{va: (was, now)} -- every site Sean's rule of 2026-10-30 moved away from OLCOMPAT2"""
    out = {}
    for va in SITES:
        now, was = owner_of(va, config), was_owner_of(va, config)
        if now != was:
            out[va] = (was, now)
    return out


def double_apply(config):
    """the effects whose Kit rows must be switched off while his runtime implements them too"""
    runtime, plugins = _present(config)
    out = []
    for va, (effect, where) in DOUBLE_APPLY.items():
        if not runtime:
            continue
        if where == "always" or (where == "plugin" and plugins):
            out.append(effect)
    return sorted(out)


def capability_table(config=None):
    """the arbitration table as plain rows (report, handoff package, receipts)"""
    config = config if config is not None else {"runtime": True, "plugins": True, "mods": []}
    rows = []
    for va, s in resolve(config).items():
        sec = s["section"].decode() if isinstance(s["section"], bytes) else s["section"]
        rows.append(dict(va=s["va"], name=s["name"], kind=s["kind"], section=sec,
                         his_len=s["his_len"], kit_len=s["kit_len"], present_in=s["overlord_in"],
                         his_allows=s["his_allows"], kit_allows=s["kit_allows"], winner=s["winner"],
                         owner=s["owner"], was=s["was"], why=s["why"], loser=s["loser"]))
    return rows


# ------------------------------------------------------------------------------------- install side
ACTIVE = {"runtime": False, "plugins": False, "wishes": True, "mods": [], "families": set()}


def families_in(folder):
    """the Kit evility families a mod folder really ships (patches/evilities/*.json -> {"family": ...})"""
    out = set()
    d = os.path.join(folder, "patches", "evilities")
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        rows = doc.get("evilities") if isinstance(doc, dict) else None
        if not isinstance(rows, dict):
            continue
        for row in rows.values():
            for r in (row if isinstance(row, list) else [row]):
                if isinstance(r, dict) and r.get("family"):
                    fam = r["family"]
                    if isinstance(fam, (list, tuple)):      # a row may declare several families
                        out.update(f for f in fam if isinstance(f, str) and f)
                    else:
                        out.add(fam)
    return out


def configure(ctx):
    """read the enabled mods once: does an Overlord *runtime* package come with this install, and which
    Kit evility families does the build actually implement?

    A converted-content package declares `overlord_package` in its mod.json and no runtime; a package
    that also installs his DLLs sets `overlord_package.runtime` (and `.plugins`).  Anything else --
    including the converted package we ship -- leaves the Kit owning every site.
    """
    ACTIVE.update({"runtime": False, "plugins": False, "wishes": True, "mods": [], "families": set()})
    for folder in getattr(ctx, "mod_folders", []) or []:
        ACTIVE["families"] |= families_in(folder)
        try:
            with open(os.path.join(folder, "mod.json"), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        pkg = meta.get("overlord_package")
        if not isinstance(pkg, dict):
            continue
        ACTIVE["mods"].append(os.path.basename(folder))
        if pkg.get("runtime"):
            ACTIVE["runtime"] = True
            if pkg.get("plugins"):
                ACTIVE["plugins"] = True
            if pkg.get("wishes") is False:      # his runtime ships no custom_wishes.txt: his wish hooks never install
                ACTIVE["wishes"] = False
    _reserve_sites(ctx)
    return dict(ACTIVE, families=sorted(ACTIVE["families"]))


OWNER = "Overlord runtime"
STEAM_SHA1 = "9460a6411699"       # the build HOOKS.md's RVAs target (data/exe_map_9460a6411699.json)


def _reserve_sites(ctx):
    """his runtime patches the exe itself: hold every site of his except the arbitrated ones the Kit keeps (owner_of != overlord)
    so a Kit feature that lands on one is named at install.  His RVAs are this build's addresses only on the Steam
    build; on any other build nothing is reserved."""
    from . import exemap
    exemap.RESERVED[:] = [e for e in exemap.RESERVED if e["owner"] != OWNER]
    if not ACTIVE["runtime"]:
        return
    if not exemap.ACTIVE.sha1.startswith(STEAM_SHA1):
        getattr(ctx, "log", print)("Overlord sites were not reserved: this game build is not the one his addresses target")
        return
    with open(os.path.join(os.path.dirname(__file__), "data", "overlord_sites.json")) as f:
        rows = json.load(f)
    # the Kit patches these: not his to hold (arbitrated Kit wins, and the effect sites Sean gave the Kit, OLHANDOFF 63b6a4f)
    kit_owned = {va for va in SITES if owner_of(va, ACTIVE) != "overlord"} | set(DOUBLE_APPLY)
    for r in rows:
        va = exemap.IMAGE_BASE + r["rva"]
        if va not in kit_owned:
            exemap.reserve(va, r["len"], OWNER)


def filter_hooks(section, hooks, native=False):
    """drop the hooks another runtime owns; returns (kept, dropped)

    Hook sites are written in the *known build's* addresses and translated to this game build inside
    `add_hook_section`, so a site has to be matched both ways round: raw (a module that already speaks
    this build's addresses) and translated (identitypatch and friends, which name known-build VAs).
    Without the translation the charhelp site slipped through a runtime install -- caught by
    `verify_yield`, which is exactly why the byte-level gate exists.

    native=True: the hooks are `native_hooks` (VAs of the input exe itself, no translation), matched raw only.
    """
    if not ACTIVE["runtime"]:
        return list(hooks), []
    drop = yielded_sites(ACTIVE)

    def owned(va):
        va = int(va)
        if va in drop:
            return True
        if native:
            return False
        try:
            from . import exemap
            return int(exemap.ACTIVE(va)) in drop
        except Exception:                       # noqa: BLE001 - unmapped or no translator yet
            return False

    kept, dropped = [], []
    for hook in hooks:
        (dropped if owned(hook[0]) else kept).append(hook)
    return kept, dropped


def report(ctx):
    """one line for the install log, so a build never silently loses a feature to arbitration"""
    if not ACTIVE["runtime"]:
        return
    drop = resolve(ACTIVE)
    yielded = sorted(v["name"] for v in drop.values() if v["owner"] == "overlord")
    if not yielded:
        return
    log = getattr(ctx, "log", print)
    log("  Overlord runtime present: the Kit yields " + ", ".join(yielded)
        + ("; his rows must be off for " + ", ".join(double_apply(ACTIVE)) if double_apply(ACTIVE) else ""))
    for mod in ACTIVE["mods"]:
        log(f"    (from '{mod}')")


def verify_yield(exe, vanilla, config=None, log=print):
    """Build-time gate: prove the policy reached the bytes.  `exe` and `vanilla` are the built and the
    pinned vanilla image bytes.  For every contested site:
      * owner 'overlord' or 'both' -> the built file still holds the vanilla bytes over HIS whole range,
        i.e. the Kit wrote nothing there and nothing is half-patched (his installer can still match);
      * owner 'kit'    -> anything the build wrote there changes at least one byte inside his own
        `expected[]` signature, so his signature check fails and HIS hook yields -- never the reverse.
        (A call-site redirect keeps the first byte 0xE8, which is why the test is "his signature is
        gone", not "the first byte changed".)
    Returns a list of findings (empty = pass).
    """
    import pefile
    config = dict(ACTIVE if config is None else config)
    findings = []
    van = pefile.PE(data=vanilla, fast_load=True)
    built = pefile.PE(data=exe, fast_load=True)
    base = van.OPTIONAL_HEADER.ImageBase
    for va, site in SITES.items():
        owner = owner_of(va, config)
        off = va - base
        n = max(site["his_len"], site["kit_len"])
        want, have = van.get_data(off, n), built.get_data(off, n)
        if len(want) < n or len(have) < n:
            findings.append(dict(va=hex(va), site=site["name"], reason="site is not fully mapped"))
            continue
        if owner in ("overlord", "both"):
            if have != want:
                findings.append(dict(va=hex(va), site=site["name"], owner=owner,
                                     reason="Kit wrote bytes at a site his runtime owns (vanilla "
                                            f"{want[:8].hex()}, built {have[:8].hex()})"))
        # owner 'kit': his signature is broken by any change inside it, which is exactly the yield we
        # want; the payload builder separately proves the redirect lands inside a .d5 section.
    for f in findings:
        log(f"  YIELD {f['site']} {f['va']}: {f['reason']}")
    return findings


def yield_receipt(exe, vanilla, config=None):
    """the same check, as a JSON-able document for a receipt"""
    import hashlib
    config = dict(ACTIVE if config is None else config)
    findings = verify_yield(exe, vanilla, config, log=lambda *_: None)
    import pefile
    van = pefile.PE(data=vanilla, fast_load=True)
    built = pefile.PE(data=exe, fast_load=True)
    base = van.OPTIONAL_HEADER.ImageBase
    rows = []
    for va, s in resolve(config).items():
        n = max(s["his_len"], s["kit_len"])
        rows.append(dict(va=s["va"], site=s["name"], owner=s["owner"], was=s["was"],
                         changed=s["owner"] != s["was"], his_len=s["his_len"], kit_len=s["kit_len"],
                         vanilla=van.get_data(va - base, n).hex(),
                         built=built.get_data(va - base, n).hex()))
    return dict(rule="more capability wins (Sean, 2026-10-30 08:15)",
                supersedes=WAS_RULE,
                configuration=dict(runtime=bool(config.get("runtime")),
                                   plugins=bool(config.get("plugins")),
                                   mods=list(config.get("mods") or [])),
                built_sha256=hashlib.sha256(exe).hexdigest(),
                vanilla_sha256=hashlib.sha256(vanilla).hexdigest(),
                sites=rows, findings=findings, verdict="pass" if not findings else "FAIL")
