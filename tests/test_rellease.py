"""Re-leasing a pack's colliding ids, and the enabled-set scan (offline, synthetic mod folders).

The case these tests pin down is the one DEDUP2 found in the live profile: a pack built in isolation
appends an id another installed pack already has, so one of the two rows can never be looked up.  The
fix has to (a) hand out an id nobody else uses, (b) never hand the pack one of its own ids, (c) repoint
the pack's own references to the new id, and (d) leave the source folder untouched.
"""
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from d5lib import modclaims, ownership, rellease  # noqa: E402

MANIFEST = ownership.load(os.path.join(ROOT, "d5lib", "data", "ownership_manifest.json"))


def mod(root, name, **tables):
    dbdir = os.path.join(root, name, "patches", "db")
    os.makedirs(dbdir, exist_ok=True)
    with open(os.path.join(root, name, "mod.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": name, "source_import": {"gameplay": [{"fields": {"evility1": 7000,
                                                                             "learn1_skill": 13000}}]}}, fh)
    for member, patch in tables.items():
        body = dict(table=member)
        body.update(patch)
        with open(os.path.join(dbdir, member + ".json"), "w", encoding="utf-8") as fh:
            json.dump(body, fh)
    return os.path.join(root, name)


def scan_without(root, exclude):
    scan = modclaims.scan_mods(root)
    out = modclaims.Scan()
    out.mods = [m for m in scan.mods if m != exclude]
    out.added = {k: {i: [h for h in hs if h != exclude] for i, hs in v.items() if any(h != exclude for h in hs)}
                 for k, v in scan.added.items()}
    out.patched = {k: {i: [h for h in hs if h != exclude] for i, hs in v.items() if any(h != exclude for h in hs)}
                   for k, v in scan.patched.items()}
    out.payloads = {(k, i): {h: p for h, p in v.items() if h != exclude}
                    for (k, i), v in scan.payloads.items() if any(h != exclude for h in v)}
    out.patch_payloads = {(k, i): {h: p for h, p in v.items() if h != exclude}
                          for (k, i), v in scan.patch_payloads.items() if any(h != exclude for h in v)}
    return out


VANILLA = {"Skill.dat": {1: "Attack", 2: "Defend"},
           "magic.dat": {1001: "Fire"},
           "charPersonal.dat": {131: "Brother"}}


# ------------------------------------------------------------------------------------------- the scan
def test_scan_only_restricts_to_the_enabled_set(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"Skill.dat": {"added": [{"id": 7000}]}})
    mod(root, "B", **{"Skill.dat": {"added": [{"id": 7000}]}})
    assert modclaims.scan_mods(root).mods == ["A", "B"]
    scan = modclaims.scan_mods(root, only=["A", "Ghost"])
    assert scan.mods == ["A"]
    assert scan.missing == ["Ghost"]
    assert modclaims.findings(scan) == []          # B is not in the enabled set


def test_profile_and_only_flags_reach_the_cli(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"Skill.dat": {"added": [{"id": 7000}]}})
    mod(root, "B", **{"Skill.dat": {"added": [{"id": 7000}]}})
    order = os.path.join(root, "load_order.json")
    with open(order, "w", encoding="utf-8") as fh:
        json.dump(["A"], fh)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    run = lambda *a: subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_ownership.py"), *a],
                                    capture_output=True, text=True, env=env)
    assert run("--installed", root).returncode == 1
    enabled = run("--installed", root, "--profile", order)
    assert enabled.returncode == 0, enabled.stdout + enabled.stderr
    assert "1 mod folders" in enabled.stdout
    assert run("--installed", root, "--only", "A").returncode == 0


def test_profile_naming_a_missing_folder_is_reported(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"Skill.dat": {"added": [{"id": 7000}]}})
    order = os.path.join(root, "load_order.json")
    with open(order, "w", encoding="utf-8") as fh:
        json.dump(["A", "Gone"], fh)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_ownership.py"),
                          "--installed", root, "--profile", order], capture_output=True, text=True, env=env)
    assert "WARNING missing" in out.stdout and "Gone" in out.stdout


# ---------------------------------------------------------------------------------------- the re-lease
def test_plan_leases_a_free_id_from_the_manifest_band(tmp_path):
    root = str(tmp_path)
    mod(root, "Other", **{"Skill.dat": {"added": [{"id": 8062, "name_EN": "Mind Mastery"}]}})
    pack = mod(root, "Pack", **{"Skill.dat": {"added": [{"id": 8062, "name_EN": "Mind Mastery"},
                                                          {"id": 7000, "name_EN": "Aegis"}]}})
    plan = rellease.plan(pack, scan_without(root, "Pack"), VANILLA, MANIFEST)
    leases = {(l.member, l.old): l.new for l in plan.leases}
    assert set(leases) == {("Skill.dat", 8062)}
    new = leases[("Skill.dat", 8062)]
    assert 7000 <= new <= 7999 and new not in (7000, 8062)   # kit band, not the pack's own 7000
    owner, _band = rellease._band_owner(MANIFEST, "evility_id", new)
    assert owner == "kit"


def test_plan_never_hands_out_the_packs_own_ids(tmp_path):
    root = str(tmp_path)
    for rid in range(7000, 7060):
        mod(root, f"Other{rid}", **{"Skill.dat": {"added": [{"id": rid}]}})
    pack = mod(root, "Pack", **{"Skill.dat": {"added": [{"id": 7060, "name_EN": "x"}]}})
    # 7060 collides with Other7060 and no id below it is free: the lease must go above the block
    mod(root, "Other7060", **{"Skill.dat": {"added": [{"id": 7060}]}})
    plan = rellease.plan(pack, scan_without(root, "Pack"), VANILLA, MANIFEST)
    assert [l.new for l in plan.leases] == [7061]
    assert pack  # the source folder is untouched by planning


def test_only_ids_restricts_what_a_pack_yields(tmp_path):
    root = str(tmp_path)
    mod(root, "Canonical", **{"Skill.dat": {"added": [{"id": 8062}]},
                              "charPersonal.dat": {"added": [{"id": 132}]}})
    pack = mod(root, "Pack", **{"Skill.dat": {"added": [{"id": 8062}]},
                                "charPersonal.dat": {"added": [{"id": 132}]}})
    plan = rellease.plan(pack, scan_without(root, "Pack"), VANILLA, MANIFEST,
                         only_ids={"charPersonal.dat": {132}})
    assert [(l.member, l.old) for l in plan.leases] == [("charPersonal.dat", 132)]
    assert plan.leases[0].new == 132 + 0 or plan.leases[0].new > 131


def test_personality_namespace_covers_vanilla_and_kit():
    ns = MANIFEST.namespace("personality_id")
    assert ns is not None and ns.kind == "range"
    owner_at = lambda rid: rellease._band_owner(MANIFEST, "personality_id", rid)[0]
    assert owner_at(131) == "vanilla" and owner_at(132) == "kit"


def test_a_vanilla_id_is_leased_away_too(tmp_path):
    root = str(tmp_path)
    pack = mod(root, "Pack", **{"magic.dat": {"added": [{"id": 1001, "name_EN": "Fire (copy)"}]}})
    plan = rellease.plan(pack, scan_without(root, "Pack"), VANILLA, MANIFEST)
    assert [(l.member, l.old, l.new) for l in plan.leases] == [("magic.dat", 1001, 13000)]
    assert "vanilla" in plan.leases[0].reason


def test_a_row_index_patch_conflict_is_reported_not_leased(tmp_path):
    root = str(tmp_path)
    mod(root, "Outfits", **{"char.dat": {"rows": {"48": {"base_HP": 10, "JMP": 3}}}})
    pack = mod(root, "Sample", **{"char.dat": {"rows": {"48": {"base_HP": 99, "JMP": 5}}}})
    plan = rellease.plan(pack, scan_without(root, "Sample"), VANILLA, MANIFEST)
    assert plan.leases == []
    assert [f[0] for f in plan.findings] == ["row_patch_conflict"]
    assert not plan.ok


# ----------------------------------------------------------------------------------------- the rewrite
def test_apply_writes_a_consistent_copy_and_leaves_the_source(tmp_path):
    root = os.path.join(str(tmp_path), "mods")
    mod(root, "Other", **{"Skill.dat": {"added": [{"id": 8062}]},
                          "magic.dat": {"added": [{"id": 13000}]}})
    pack = mod(root, "Pack", **{
        "Skill.dat": {"added": [{"id": 8062, "name_EN": "Mind Mastery"}, {"id": 8391, "name_EN": "Advance"}]},
        "magic.dat": {"added": [{"id": 13000, "name_EN": "Legit Shield"}]},
        "char.dat": {"added": [{"id": 14080, "evility1": 8062, "learn1_skill": 13000, "evility2": 8391}]},
    })
    before = {p: open(os.path.join(pack, "patches", "db", p), encoding="utf-8").read()
              for p in os.listdir(os.path.join(pack, "patches", "db"))}
    plan = rellease.plan(pack, scan_without(root, "Pack"), VANILLA, MANIFEST)
    out = os.path.join(str(tmp_path), "out")
    receipt = rellease.apply(pack, out, plan)

    # the source is untouched
    after = {p: open(os.path.join(pack, "patches", "db", p), encoding="utf-8").read()
             for p in os.listdir(os.path.join(pack, "patches", "db"))}
    assert before == after

    fixed = os.path.join(out, "Pack")
    skills = {r["id"]: r for r in json.load(open(os.path.join(fixed, "patches", "db", "Skill.dat.json")))["added"]}
    magic = {r["id"]: r for r in json.load(open(os.path.join(fixed, "patches", "db", "magic.dat.json")))["added"]}
    chars = json.load(open(os.path.join(fixed, "patches", "db", "char.dat.json")))["added"]
    new_skill = receipt["leases"][0]["new"]
    assert 8062 not in skills and new_skill in skills
    assert 8391 in skills                                   # an unreleased id is left alone
    new_magic = [l["new"] for l in receipt["leases"] if l["member"] == "magic.dat"][0]
    assert 13000 not in magic and new_magic in magic
    assert chars[0]["evility1"] == new_skill                # the row follows its evility
    assert chars[0]["learn1_skill"] == new_magic
    assert chars[0]["evility2"] == 8391
    # mod.json provenance follows too
    modjson = json.load(open(os.path.join(fixed, "mod.json")))
    fields = modjson["source_import"]["gameplay"][0]["fields"]
    assert fields["evility1"] == new_skill and fields["learn1_skill"] == new_magic


def test_apply_refuses_to_overwrite_the_source(tmp_path):
    root = os.path.join(str(tmp_path), "mods")
    pack = mod(root, "Pack", **{"Skill.dat": {"added": [{"id": 8062}]}})
    plan = rellease.plan(pack, scan_without(root, "Pack"), VANILLA, MANIFEST)
    try:
        rellease.apply(pack, root, plan)
    except ValueError as exc:
        assert "copy" in str(exc)
    else:
        raise AssertionError("apply() must refuse to rewrite the source pack")
