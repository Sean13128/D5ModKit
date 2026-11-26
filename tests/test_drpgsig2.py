"""DRPGSIG2: the second-word family invincible_hits (Cheshire Cat Majorita) and the alias row of Jusoso (D5 Lich Deimos 145)."""
import json
import struct
import tempfile
from pathlib import Path

import pytest

from d5lib import evility as ev
import drpg_text_stub
from d5lib.importers import _drpg_text
from d5lib.importers import drpg_evilities as de

KIT = Path(__file__).resolve().parents[1]
OVERLAY = KIT / "d5lib/importers/drpg-evility-overlay.json"
EXE = Path("/Volumes/Data/Projects/D5/D5Modkit/state/games/Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")
ASM = (KIT / "d5lib/native/d5evil.inc.asm").read_text()


def _ev(base, evid):
    d = _drpg_text.load(OVERLAY)
    return next(e for e in d["bases"][str(base)]["evilities"] if e["id"] == evid)


def test_row_encoding():
    rows, conds, fx = ev.table({1: {"family": "invincible_hits", "effects": [{"value": 2}]}})
    evid, mask, cond_off, n_cond, fx_off, n_fx, flags, filt = rows[0]
    assert (evid, mask, n_cond, n_fx) == (1, 0, 0, 1) and flags == 8 << 8 and ev.ext_query("invincible_hits") == 8 << 32
    assert fx == [(0, 2)]
    assert dict(list(ev.EXT_FAMILIES.items())[:5]) == {"face_target_away": 0, "enemy_heal_percent": 1, "attack_counter": 2, "invincible_hits": 3, "special_seal": 4}
    assert "mov rdi, 0x800000000" in ASM            # the asm queries bit 35 of the second word, nothing else


@pytest.mark.parametrize("bad", [
    {"family": "invincible_hits"},                                                    # needs its number
    {"family": "invincible_hits", "effects": []},
    {"family": "invincible_hits", "effects": [{"value": 0}]},
    {"family": "invincible_hits", "effects": [{"value": 101}]},
    {"family": "invincible_hits", "effects": [{"value": 2}, {"value": 1}]},
    {"family": "invincible_hits", "effects": [{"value": 2, "stat": "atk"}]},
    {"family": ["invincible_hits", "attack_counter"], "effects": [{"value": 2}]},
    {"family": ["invincible_hits", "nullify"], "effects": [{"value": 2}]},
])
def test_row_rules(bad):
    with pytest.raises(ValueError):
        ev.table({1: bad})


def test_wrappers_and_sites_are_unchanged_and_the_return_addresses_are_the_predicate_sites():
    assert len(ev.WRAPPERS) == 37 and len(ev.TAGS) == len(set(ev.TAGS))                # 33 at DRPGSIG2 (no new site); D4SIG10b adds roc_geo and roc_skill; DD2EVIL2 adds victims; LONGTAIL2 adds max_reflect
    nul = ev.wrapper("nullify")
    assert nul[2][:2] == [0x1401BF0F0, 0x1401BF6DD]
    # the two return addresses wrap_nullify admits are exactly those sites + 5
    assert "mov rcx, 0x1401BF0F5" in ASM and "mov rcx, 0x1401BF6E2" in ASM
    assert ev.wrapper("atkcount")[2] == [0x1401B1BE0]
    if EXE.exists():
        raw = EXE.read_bytes()
        for site in (0x1401BF0F0, 0x1401BF6DD):
            off = ev._offset(raw, site)
            assert raw[off] == 0xE8 and site + 5 + struct.unpack_from("<i", raw, off + 1)[0] == ev.NULLIFY
        off = ev._offset(raw, 0x1401B1BE0)
        assert raw[off] == 0xE8 and 0x1401B1BE0 + 5 + struct.unpack_from("<i", raw, off + 1)[0] == ev.APPLY_DAMAGE


def test_section_assembles_with_the_pend_table_marked_and_the_old_data_in_place():
    src = ev._asm_source(*ev.table({}))
    code, labels = ev._assemble(src, 0x14808F000)
    assert "evil_pend" in ev.SECTION_SYMBOLS and "evil_ctx" in ev.SECTION_SYMBOLS
    pend, ctx = ev.SECTION_SYMBOLS["evil_pend"], ev.SECTION_SYMBOLS["evil_ctx"]
    assert pend < ctx and (ctx - pend) >= 656 + 8 * 512                                   # the table, then the presence map, then evil_ctx
    assert code[pend - 0x14808F000 - 8: pend - 0x14808F000] == struct.pack("<Q", ev.EVIL_PEND_MAGIC)
    assert code[pend - 0x14808F000: pend - 0x14808F000 + 656] == bytes(656)               # starts all clear
    assert labels[0xE70020] > 0x14808F000


def test_majorita_row_in_overlay_both_halves():
    e = _ev(392, 28376)
    assert e["rpg_ids"] == [3921, 3925] and e["cls"] == "A+" and "alias" not in e
    assert e["rows"][-1] == {"family": "invincible_hits", "effects": [{"value": 2}]}
    fams = [r["family"] for r in e["rows"]]
    assert fams == ["stats", ["stats", "aura"], "crit_damage", ["crit_damage", "aura"], "invincible_hits"]
    assert e["rows"][0]["effects"] == [{"stat": "atk", "value": 18}] and e["rows"][2]["effects"] == [{"value": 18}]
    assert e["label"].startswith("source: Disgaea RPG JP leaderskill 3921+3925; adapted:")
    assert "a lethal one too" in e["label"] and "poison, falls and field damage do not pass this check" in e["label"]
    assert e["skill_row"]["desc_EN"].endswith("Nullify the damage of the first 2 hits taken in a battle.")
    ev.table({e["id"]: e["rows"]})


def test_other_invincible_rows_follow_the_same_family():
    assert _ev(310, 28303)["rows"] == [{"family": "invincible_hits", "effects": [{"value": 5}]}]      # Krai Andrey sub 3, 5 hits
    liam = _ev(20103, 28538)
    assert liam["rows"][0] == {"family": "invincible_hits", "effects": [{"value": 2}]}
    assert [r["family"] for r in liam["rows"][1:]] == ["taken", ["taken", "aura"]]                  # the other half was already built
    for e in (_ev(310, 28303), liam):
        ev.table({e["id"]: e["rows"]})


def test_the_single_hit_row_still_aliases_first_impression():
    d = _drpg_text.load(OVERLAY)
    hado = [e for b in d["bases"].values() for e in b["evilities"] if e["rpg_ids"] == [200784]]
    assert len(hado) == 1 and hado[0]["alias"] == 6047 and "rows" not in hado[0]


def test_jusoso_keeps_its_stat_rows_and_the_alias():
    with drpg_text_stub.names("Lich Deimos"):
        _jusoso()


def _jusoso():
    e = _ev(20100, 28528)
    assert e["rpg_ids"] == [201001, 201005] and e["alias"] == 145 and e["cls"] == "A+" and e["needs"] == ["D1"]
    assert [r["family"] for r in e["rows"]] == ["stats", ["stats", "aura"], "crit_damage", ["crit_damage", "aura"]]
    assert e["rows"][0]["effects"] == [{"stat": "hp", "value": 20}, {"stat": "atk", "value": 20}]
    assert e["skill_row"]["desc_EN"].endswith("Once per battle, revive with full HP after being defeated (inside the Base Panel).")
    assert "Lich Deimos 145" in e["label"] and "Base Panel" in e["label"]
    ev.table({e["id"]: e["rows"]})
    assert "revives only units on the player's side" in e["label"]
    zed = _ev(94, 28077)
    assert "revives only units on the player's side" in zed["label"]
    zed = _ev(94, 28077)                                                    # Zed's sub 1 is the same revive on its own
    assert zed["alias"] == 145 and "rows" not in zed and zed["label"].startswith("D5 equivalent: 145 Lich Deimos")


def test_apply_writes_both_the_runtime_rows_and_the_alias():
    e = _ev(20100, 28528)
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "pack"
        (d / "patches/db").mkdir(parents=True)
        (d / "mod.json").write_text(json.dumps({"name": "x", "source_import": {"source": {"character": {"base_id": 20100, "leader_skills": []}}}}))
        (d / "patches/db/char.dat.json").write_text(json.dumps({"table": "char.dat", "added": [{"id": 1, "evility1": 1235, "evility_count": 1}]}))
        out = de.apply(d, 20100)
        assert out and 28528 in out["own"]
        assert json.loads((d / "patches/evilities/aliases.json").read_text())["28528"] == 145
        rt = json.loads((d / "patches/evilities/evilities.json").read_text())["evilities"]["28528"]
        assert rt == e["rows"]
        ok, why = de.gate(d, 20100)
        assert ok, why


def test_the_overlay_names_for_the_three_new_evilities_are_ascii_and_provisional():
    """The JP names are hashes in the file (TEXTHASH-DRPG): the rows are found by the SHA-256 of the JP name."""
    doc = json.loads((KIT / "d5lib/importers/drpg-evility-names.json").read_text())
    names = {row["jp"]["@text"]: row["en"]["@authored"] for row in doc["names"]}
    for digest, en in (("ddd4ce3063feeb65a9ec043d7455cbb9be3f8397aa9a1c3067e7583c7e653596", "Zombie Revival"), ("730511841c0c1b13b403763fddb6bd2a45bc66f0c2818ef38d7a9e63237cf5f5", "Barrier Ring"), ("52951cc0d002ebf2e5c3fac8bb7a09c8768a67bf03608e34051446dde112cc71", "Pringer Protect L")):
        assert names[digest] == en and en.isascii()
