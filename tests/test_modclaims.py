"""Installed-set claim scan: duplicate ids across every mod folder, plus the vanilla table (offline).

Synthetic mod folders only -- no game, no kit state, no installed kit.  The 491-495 outfit-row collision
is the case these tests pin down: two mods appending the same id must be refused even when neither pack
knows about the other.
"""
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from d5lib import modclaims, ownership  # noqa: E402

MANIFEST = os.path.join(ROOT, "d5lib", "data", "ownership_manifest.json")


def mod(root, name, **tables):
    """Write one mod folder: mod(root, "A", **{"char.dat": {"added": [{"id": 491, "name_EN": "x"}]}})."""
    dbdir = os.path.join(root, name, "patches", "db")
    os.makedirs(dbdir, exist_ok=True)
    with open(os.path.join(root, name, "mod.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": name}, fh)
    for member, patch in tables.items():
        body = dict(table=member)
        body.update(patch)
        with open(os.path.join(dbdir, member + ".json"), "w", encoding="utf-8") as fh:
            json.dump(body, fh)
    return os.path.join(root, name)


def kinds(findings):
    return [f.kind for f in findings]


# ------------------------------------------------------------------------------------------------- scan
def test_two_mods_appending_one_id_are_refused(tmp_path):
    root = str(tmp_path)
    mod(root, "Outfits", **{"char.dat": {"added": [{"id": 491, "name_EN": "Majorita (Halloween)"}]}})
    mod(root, "Sample", **{"char.dat": {"added": [{"id": 491, "name_EN": "Melodia (School Uniform)"}]}})
    scan = modclaims.scan_mods(root)
    assert scan.mods == ["Outfits", "Sample"]
    assert scan.holders("char.dat", 491) == ["Outfits", "Sample"]
    findings = modclaims.findings(scan)
    assert kinds(findings) == ["duplicate_id"]
    f = findings[0]
    assert (f.severity, f.table, f.rid) == ("error", "char.dat", 491)
    assert "2 different rows" in f.detail


def test_identical_rows_are_still_a_duplicate(tmp_path):
    root = str(tmp_path)
    row = {"id": 13000, "name_EN": "Ignis Fatuus", "sp_cost": 49}
    mod(root, "ClassA", **{"magic.dat": {"added": [dict(row)]}})
    mod(root, "ClassB", **{"magic.dat": {"added": [dict(row)]}})
    findings = modclaims.duplicate_findings(modclaims.scan_mods(root))
    assert kinds(findings) == ["duplicate_id"]
    assert "identical rows" in findings[0].detail


def test_distinct_ids_and_a_mod_without_db_patches_are_clean(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"char.dat": {"added": [{"id": 233, "name_EN": "Melodia"}]}})
    mod(root, "B", **{"char.dat": {"added": [{"id": 234, "name_EN": "Citri"}]}})
    os.makedirs(os.path.join(root, "Art"), exist_ok=True)          # no patches/db at all
    assert modclaims.findings(modclaims.scan_mods(root)) == []


def test_row_index_patches_that_differ_are_a_conflict(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"char.dat": {"rows": {"48": {"sprite_id": 263}}}})
    mod(root, "B", **{"char.dat": {"rows": {"48": {"sprite_id": 273}}}})
    findings = modclaims.duplicate_findings(modclaims.scan_mods(root))
    assert kinds(findings) == ["patch_conflict"]
    assert findings[0].severity == "error"
    assert findings[0].rid == 48


def test_row_index_patches_that_agree_are_information_only(tmp_path):
    root = str(tmp_path)
    for name in ("A", "B"):
        mod(root, name, **{"char.dat": {"rows": {"48": {"sprite_id": 263}}}})
    findings = modclaims.duplicate_findings(modclaims.scan_mods(root))
    assert [(f.kind, f.severity) for f in findings] == [("patch_merge", "info")]


def test_row_index_patches_on_different_fields_compose(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"char.dat": {"rows": {"48": {"sprite_id": 263}}}})
    mod(root, "B", **{"char.dat": {"rows": {"48": {"name_EN": "Melodia"}}}})
    findings = modclaims.duplicate_findings(modclaims.scan_mods(root))
    assert [(f.kind, f.severity) for f in findings] == [("patch_merge", "info")]


def test_row_index_patches_that_disagree_name_the_field(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"char.dat": {"rows": {"48": {"sprite_id": 263, "base_HP": 26}}}})
    mod(root, "B", **{"char.dat": {"rows": {"48": {"sprite_id": 263, "base_HP": 32}}}})
    findings = modclaims.duplicate_findings(modclaims.scan_mods(root))
    assert [(f.kind, f.severity) for f in findings] == [("patch_conflict", "error")]
    assert "base_HP" in findings[0].detail and "sprite_id" not in findings[0].detail


def test_an_old_name_pack_and_a_new_name_pack_clash_on_the_same_field(tmp_path):
    # SCHEMA1 renamed char.dat unk_0E0 -> exp_yield_weight; a pack built before and one after must still clash.
    root = str(tmp_path)
    mod(root, "Old", **{"char.dat": {"rows": {"48": {"unk_0E0": 4}}}})
    mod(root, "New", **{"char.dat": {"rows": {"48": {"exp_yield_weight": 6}}}})
    findings = modclaims.duplicate_findings(modclaims.scan_mods(root))
    assert [(f.kind, f.severity) for f in findings] == [("patch_conflict", "error")]
    assert "exp_yield_weight" in findings[0].detail and "unk_0E0" not in findings[0].detail
    mod(root, "New", **{"char.dat": {"rows": {"48": {"exp_yield_weight": 4}}}})     # same value: they compose
    assert kinds(modclaims.duplicate_findings(modclaims.scan_mods(root))) == ["patch_merge"]


def test_an_added_row_without_an_id_claims_nothing(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"charPersonal.dat": {"added": [{"voice_group": 135}]}})
    scan = modclaims.scan_mods(root)
    assert scan.added.get("charPersonal.dat", {}) == {}
    assert ("A", "charPersonal.dat") in scan.empty_tables


# ---------------------------------------------------------------------------------------------- vanilla
def test_ids_the_vanilla_table_has_are_refused_but_dummy_rows_are_filled(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"char.dat": {"added": [{"id": 233, "name_EN": "Melodia"},
                                             {"id": 490, "name_EN": "Melodia (Priestess)"}]}})
    names = {"char.dat": {233: "Des X", 490: "Unique Dummy"}}
    fillable = modclaims.vanilla_fillable(names)
    got = {f.kind: f for f in modclaims.findings(modclaims.scan_mods(root), names, fillable)}
    assert got["vanilla_collision"].severity == "error"
    assert got["vanilla_collision"].rid == 233
    assert got["fills_vanilla_dummy"].severity == "info"
    assert got["fills_vanilla_dummy"].rid == 490


def test_fillable_ids_are_only_the_games_dummy_rows():
    assert modclaims.fillable_ids({470: "Unique Dummy", 233: "Des X", 980: "DLC Dummy"}) == {470, 980}


# ----------------------------------------------------------------------------------------------- claims
def test_claims_map_to_the_manifest_namespaces(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"char.dat": {"added": [{"id": 300}]},
                      "Skill.dat": {"added": [{"id": 7100}]},
                      "magic.dat": {"added": [{"id": 13000}]},
                      "Quest.dat": {"added": [{"id": 900}]}})          # no namespace: not an id claim
    claims = modclaims.claims(modclaims.scan_mods(root))
    got = sorted((c.namespace, c.start, c.holder) for c in claims)
    assert got == [("char_dat_row", 300, "mod:A"), ("evility_id", 7100, "mod:A"),
                   ("special_id", 13000, "mod:A")]


def test_check_usage_refuses_two_holders_and_keeps_band_ownership_out_of_it(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"char.dat": {"added": [{"id": 300}]}})
    mod(root, "B", **{"char.dat": {"added": [{"id": 300}]}})
    manifest = ownership.load(MANIFEST)
    findings = ownership.check_usage(manifest, modclaims.claims(modclaims.scan_mods(root)))
    assert [f.kind for f in ownership.errors(findings)] == ["duplicate_claim"]
    # 9995 is a vanilla row id: outside every kit band, so a pack claiming it is refused by check_claims,
    # but check_usage (the installed set) does not judge bands at all
    assert ownership.check_usage(manifest, [ownership.Claim("mod:x", "char_dat_row", 9995, 9995)]) == []


def test_a_pack_is_refused_against_the_installed_set(tmp_path):
    """The gate itself: a pack's own claim plus every installed claim, one duplicate between them."""
    root = str(tmp_path)
    mod(root, "DRPG_Outfits_Majorita", **{"char.dat": {"added": [{"id": 491}, {"id": 492}]}})
    manifest = ownership.load(MANIFEST)
    installed = modclaims.claims(modclaims.scan_mods(root))
    pack = [ownership.Claim("kit:DRPG_Sample", "char_dat_row", 491, 493, label="outfit slots")]
    findings = ownership.check_usage(manifest, installed + pack)
    errs = ownership.errors(findings)
    assert {f.kind for f in errs} == {"duplicate_claim"}
    assert sorted(f.start for f in errs) == [491, 492]      # one per id the two of them both take


# -------------------------------------------------------------------------------------------------- cli
def _run(*args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_ownership.py"), *args],
                          capture_output=True, text=True, env=env)


def test_cli_exits_one_on_a_duplicate_and_zero_when_clean(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"char.dat": {"added": [{"id": 491}]}})
    mod(root, "B", **{"char.dat": {"added": [{"id": 491}]}})
    bad = _run("--installed", root)
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert "duplicate_id" in bad.stdout and "char.dat[491]" in bad.stdout
    clean = _run("--installed", root + "/A")
    assert clean.returncode == 0, clean.stdout + clean.stderr


def test_cli_json_reports_the_installed_scan(tmp_path):
    root = str(tmp_path)
    mod(root, "A", **{"char.dat": {"added": [{"id": 491}]}})
    mod(root, "B", **{"char.dat": {"added": [{"id": 491}]}})
    out = json.loads(_run("--installed", root, "--json").stdout)
    installed = out["installed"]
    assert installed["mods"] == ["A", "B"]
    assert [f["kind"] for f in installed["findings"]] == ["duplicate_id"]


# ----------------------------------------------------------------------------------------- positional
def test_positional_member_repeated_inside_one_pack_is_information(tmp_path):
    """charPersonal rows are read by position and Overlord's own member is `3, 4, 5, 3, 4, 5`."""
    root = str(tmp_path)
    rows = [{"id": 3, "name_EN": "Energetic"}, {"id": 4, "name_EN": "Aiming For Ace"},
            {"id": 5, "name_EN": "Effort"}, {"id": 3, "name_EN": "Energetic"},
            {"id": 4, "name_EN": "Aiming For Ace"}, {"id": 5, "name_EN": "Effort"}]
    mod(root, "Overlord Characters", **{"charPersonal.dat": {"added": rows}})
    find = modclaims.findings(modclaims.scan_mods(root),
                              {"charPersonal.dat": {3: "Energetic", 4: "Aiming For Ace",
                                                    5: "Effort"}},
                              modclaims.vanilla_fillable(
                                  {"charPersonal.dat": {3: "Energetic", 4: "Aiming For Ace",
                                                        5: "Effort"}}))
    assert {f.kind for f in find} == {"positional_repeat", "positional_vanilla_id"}
    assert all(f.severity == modclaims.INFO for f in find)


def test_positional_member_claimed_by_two_packs_is_still_an_error(tmp_path):
    root = str(tmp_path)
    mod(root, "PackA", **{"charhelp.dat": {"added": [{"id": 22682, "char_id": 22682}]}})
    mod(root, "PackB", **{"charhelp.dat": {"added": [{"id": 22682, "char_id": 22682}]}})
    findings = modclaims.duplicate_findings(modclaims.scan_mods(root))
    assert kinds(findings) == ["duplicate_id"]
    assert findings[0].severity == "error"
