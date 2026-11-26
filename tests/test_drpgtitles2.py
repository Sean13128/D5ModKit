"""DRPGTITLE2: DRPG class titles that have a documented English name.

The 144 titles were all provisional literal translations (SMALLFIX1b).  This lane replaces the ones a documented
source names.  The admissible source is the Disgaea RPG Wiki (Fandom) character page, which renders the title at
each star rarity; the archived Global client master is cited beside it as corroboration where the two agree.
Nine titles are documented and seven of those pair verbatim with the JP character row's class-name column; the two
whose JP character row has no class-name columns pair through the wiki's own rarity slot.  The two titles where the
wiki and the archived Global master disagree (55 Noel, 20011 Tink) stay provisional.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from d5lib.importers import drpg_titles  # noqa: E402

# the titles whose English is documented by a community page (see DRPGTITLE2-REPORT.md)
COMMUNITY = {
    "15": "Order-Taking Demon",       # wiki Barbara rev 53134; Global row 15 class_name_3, JP string verbatim
    "47": "Kunoichi",                 # wiki Yukimaru rev 53010; Global row 47 class_name_3
    "48": "Blind Ninja",              # wiki Fubuki rev 53039; Global row 48 class_name_3
    "59": "Magic Cutie",              # wiki Love Oracle rev 53300; Global row 59 class_name_4
    "95": "Legendary Witch",          # wiki Majolene rev 53075; Global row 95 class_name_1-4
    "20006": "Prinny x3",             # wiki Pringer V3 rev 53340; Global row 20006 class_name_2
    "20009": "Adell's Brother",       # wiki Taro rev 53407; JP character row empty -> wiki rarity slot
    "20010": "Adell's Sister",        # wiki Hanako rev 53249; JP character row empty -> wiki rarity slot
    "21002": "Laharl's Babysitter",   # wiki Rainier rev 53372; Global row 21002 class_name_3
}
# documented names that disagree between the wiki and the archived Global master -> stay provisional
CONFLICT = {"55": "Yuletide Mage", "20011": "Boy-Turned-Frog"}
# rows whose JP character row has no class-name columns: the pairing is the wiki's rarity slot, not a JP string
WIKI_SLOT_ONLY = {"20009", "20010"}
PROVISIONAL_REASONS = ("no official English:", "no official English for this title:", "no agreed English:")


def test_community_titles_are_exactly_the_documented_set():
    doc = drpg_titles.load()
    community = {k: v["en"] for k, v in doc["titles"].items() if v.get("en_kind") == "community"}
    assert community == COMMUNITY


def test_no_title_is_sourced_from_the_archived_global_master_alone():
    doc = drpg_titles.load()
    assert not [k for k, v in doc["titles"].items() if v.get("en_kind") == "official"]


def test_every_title_declares_its_kind_and_cites_its_source():
    doc = drpg_titles.load()
    for base, t in doc["titles"].items():
        assert t["en_kind"] in ("community", "official", "provisional"), base
        if t["en_kind"] == "community":
            assert "https://disgaea-rpg.fandom.com/wiki/" in t["en_source"], base
            assert "rev " in t["en_source"] and "DragoSaiHero3" in t["en_source"], base
            assert 'renders "' in t["en_source"], base
            assert "DRPGTITLE2" in t["en_source"], base
        else:
            assert t["en_source"].startswith("provisional literal translation (SMALLFIX1)"), base
            assert any(r in t["en_source"] for r in PROVISIONAL_REASONS), base


def test_verbatim_and_wiki_slot_pairings_are_labelled_apart():
    doc = drpg_titles.load()
    for base in COMMUNITY:
        src = doc["titles"][base]["en_source"]
        if base in WIKI_SLOT_ONLY:
            assert "JP character row has no class-name columns" in src, base
            assert "wiki's own slot assignment" in src, base
        else:
            assert "same string as the JP character row's class_name_" in src, base


def test_conflicting_documented_names_stay_provisional_and_say_so():
    doc = drpg_titles.load()
    for base, wiki_name in CONFLICT.items():
        t = doc["titles"][base]
        assert t["en_kind"] == "provisional", base
        assert "no agreed English" in t["en_source"], base
        assert wiki_name in t["en_source"], base


def test_community_english_fits_the_field_and_is_ascii():
    doc = drpg_titles.load()
    for base in COMMUNITY:
        t = doc["titles"][base]
        assert t["en"].isascii() and len(t["en"].encode()) <= 67, base
        assert t["en"] != drpg_titles.PLACEHOLDER, base


def test_table_and_source_blocks_hold_no_workstation_paths():
    raw = drpg_titles.TABLE.read_text(encoding="utf-8")
    assert "/Volumes/" not in raw and "/Users/" not in raw and "ai-tmp" not in raw


def test_apply_writes_the_documented_english_and_keeps_the_jp_string(tmp_path):
    (tmp_path / "patches/db").mkdir(parents=True)
    path = tmp_path / "patches/db/char.dat.json"
    path.write_text(json.dumps({"table": "char.dat", "added": [
        dict(id=743, title_EN="Disgaea RPG", title_FR="Disgaea RPG", title_JP="Disgaea RPG",
             title_CHN="Disgaea RPG", title_KOR="Disgaea RPG")]}))
    assert drpg_titles.apply(tmp_path, 15) == 1
    row = json.loads(path.read_text())["added"][0]
    rec = drpg_titles.title_of(15)
    assert row["title_EN"] == row["title_FR"] == "Order-Taking Demon" == rec["en"]
    assert row["title_JP"] == row["title_CHN"] == row["title_KOR"] == rec["jp"]
    assert drpg_titles.gate(tmp_path, 15)[0]


def test_source_blocks_record_the_two_sources():
    doc = drpg_titles.load()
    src = doc["official_source"]
    assert src["rows"] == 489
    assert src["sha256"] == "4ef77b532cd3846351bdc596bf7b04d4167edf08650cec6d72a91d1b5baa0cac"
    assert "id" in src["pairing"] and "class_name_" in src["pairing"]
    com = doc["community_source"]
    assert com["base_url"] == "https://disgaea-rpg.fandom.com"
    assert "Template:Enum/JP/Titles" in com["title_template"]
    assert com["retrieved"] == "2026-11-19"


def test_apply_retitles_a_row_that_already_carries_an_older_wording(tmp_path):
    """A staged/installed pack carries the provisional wording; re-applying the table must replace it."""
    (tmp_path / "patches/db").mkdir(parents=True)
    path = tmp_path / "patches/db/char.dat.json"
    path.write_text(json.dumps({"table": "char.dat", "added": [
        dict(id=743, title_EN="Magical Girl", title_FR="Magical Girl", title_JP="old jp",
             title_CHN="old jp", title_KOR="old jp")]}), encoding="utf-8")
    assert drpg_titles.apply(tmp_path, 59) == 1
    row = json.loads(path.read_text(encoding="utf-8"))["added"][0]
    assert row["title_EN"] == row["title_FR"] == "Magic Cutie"
    assert row["title_JP"] == row["title_CHN"] == row["title_KOR"] == drpg_titles.title_of(59)["jp"] != "old jp"
    assert drpg_titles.gate(tmp_path, 59)[0]
