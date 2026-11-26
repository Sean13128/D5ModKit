"""Offline finalization + validators for the converted Overlord v3 character.

Runs the Kit's own writers over the staged mod, reads the rows back, validates the .d5el table the
Kit's evility builder would emit, and writes a receipt.  Nothing is installed and nothing is written
into the game: modsys.build keeps every changed member in memory.

  PYTHONDONTWRITEBYTECODE=1 python3 tools/overlord_port/finalize.py <mod-dir> [receipt.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parents[1]
sys.path.insert(0, str(KIT))

from d5lib import database, evility, gamefs, modsys, ownership, voices  # noqa: E402
from d5lib.d4unique import Originals  # noqa: E402

PROJECT = Path("/Volumes/Data/Projects/D5")
GAME = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
STATE = PROJECT / "D5Modkit/state/games/Disgaea_5_Complete-d8040a88"
DB0 = "Database/Database_0.dat/"
# The pinned ids, used when no build evidence sits next to the mod.  A rebuild re-leases (help ids are
# allocated above every installed claim), so run() prefers the ids the converter actually used.
CHAR, HELP, QUEST = 224, 22682, 9503
EVILITIES = (7700, 7701, 7702, 7703)
SPECIALS = (10220, 10221, 10222)
VOICE = 9071


def leased(mod_dir):
    """(char, help, quest, evilities, specials, voice) from the converter's evidence, else the pins."""
    for candidate in (mod_dir.parents[1] / "p4-evidence.json", mod_dir.parent / "p4-evidence.json"):
        if candidate.is_file():
            lease = json.loads(candidate.read_text()).get("lease") or {}
            if "char_row" in lease:
                return (int(lease["char_row"]), int(lease["help_id"]), int(lease["quest_id"]),
                        tuple(int(v) for v in lease["evilities"]),
                        tuple(int(v) for v in lease["specials"]), int(lease["voice"]))
    return CHAR, HELP, QUEST, EVILITIES, SPECIALS, VOICE
FIELDS_CHAR = ("id", "name_EN", "title_EN", "sprite_id", "color_id", "help_id", "voice_id", "evility1",
               "evility2", "evility_count", "learn_count", "base_HP", "base_ATK", "apt_HP", "kind_gender",
               "MOV", "JMP", "throw", "counter", "crit", "res_fire")
FIELDS_EVIL = ("id", "name_EN", "slot_cost", "mana_cost", "owner", "kind", "effect_group", "value1")
FIELDS_MAGIC = ("id", "name_EN", "sp_cost", "element", "anim_id", "user1", "user_count", "attack_map")


def run(mod_dir: Path, out: Path) -> dict:
    global CHAR, HELP, QUEST, EVILITIES, SPECIALS, VOICE
    CHAR, HELP, QUEST, EVILITIES, SPECIALS, VOICE = leased(mod_dir)
    receipt = dict(schema="overlord-port-finalization/1", mod=str(mod_dir), checks={}, notes=[],
                   lease=dict(char=CHAR, help=HELP, quest=QUEST, evilities=list(EVILITIES),
                              specials=list(SPECIALS), voice=VOICE))
    fs = gamefs.GameFS(str(GAME), backup_resolver=Originals(STATE))
    try:
        mods = [modsys.Mod(str(mod_dir))]
        logs = []
        ctx = modsys.build(fs, mods, log=lambda s: logs.append(s))
        receipt["build"] = dict(outputs=len(ctx.outputs), log=[l for l in logs if l][-8:])
        char = database.load_table("char.dat", ctx.get(DB0 + "char.dat"))
        skill = database.load_table("Skill.dat", ctx.get(DB0 + "Skill.dat"))
        magic = database.load_table("magic.dat", ctx.get(DB0 + "magic.dat"))
        help_t = database.load_table("charhelp.dat", ctx.get(DB0 + "charhelp.dat"))
        quest = database.load_table("Quest.dat", ctx.get(DB0 + "Quest.dat"))

        row = char.find(CHAR)
        receipt["checks"]["char_row_added"] = row is not None
        receipt["checks"]["char_row"] = {f: _j(row[f]) for f in FIELDS_CHAR} if row else None
        receipt["checks"]["char_row_readback"] = bool(row) and (
            row["evility1"] == EVILITIES[0] and row["evility2"] == EVILITIES[1] and row["learn_count"] == 8
            and row["voice_id"] == VOICE and row["help_id"] == HELP)

        found = {i: skill.find(i) for i in EVILITIES}
        receipt["checks"]["evilities_added"] = all(found.values())
        receipt["checks"]["evilities"] = {str(i): {f: _j(r[f]) for f in FIELDS_EVIL} for i, r in found.items() if r}

        found_m = {i: magic.find(i) for i in SPECIALS}
        receipt["checks"]["specials_added"] = all(found_m.values())
        receipt["checks"]["specials"] = {str(i): {f: _j(r[f]) for f in FIELDS_MAGIC} for i, r in found_m.items() if r}

        help_row = help_t.find(HELP)
        receipt["checks"]["help_added"] = help_row is not None
        receipt["checks"]["help"] = {k: help_row[k] for k in ("line1_EN", "line2_EN", "line3_EN")} if help_row else None
        q = quest.find(QUEST)
        receipt["checks"]["quest_added"] = q is not None
        receipt["checks"]["quest"] = {k: q[k] for k in ("id", "name_EN", "cond_type", "desc1_EN")} if q else None

        # the .d5el table the evility builder would emit -- the same validation the installer runs
        data = evility.load(mods[0])
        rows, conds, fx = evility.table(data["evilities"])
        receipt["checks"]["evility_table"] = dict(rows=len(rows), conditions=len(conds), effects=len(fx),
                                                  ids=[r[0] for r in rows], masks=[r[1] for r in rows])
        receipt["checks"]["evility_table_valid"] = True

        # voices: the mod's own voice data has to resolve through the Kit's catalog-free loader
        vdata = voices.load(mods[0])
        v = vdata["voices"].get(str(VOICE))
        pdir = mod_dir / "patches/voices"
        missing = [l["file"] for l in (v or {}).get("lines", []) if not (pdir / l["file"]).is_file()]
        receipt["checks"]["voice"] = dict(id=VOICE, lines=len((v or {}).get("lines", [])),
                                          missing_files=missing, clips=len(list(pdir.glob("*.vag"))))
        receipt["checks"]["voice_ok"] = bool(v) and not missing

        # the ANM members have to load with the Kit's reader and carry the leased ids
        import d5lib.anm as anm
        members = {}
        for p in sorted((mod_dir / "files/Anime/ANM_HI_JP.dat").glob("anm*.lzs")):
            a = anm.load(str(p))
            members[p.name] = dict(block_id=a.blocks[0].id, animations=sorted(x.id for x in a.blocks[0].animations),
                                   cells=len(a.blocks[0].cells), palettes=len(a.palettes))
        receipt["checks"]["anm_members"] = members
        receipt["checks"]["anm_ok"] = (members.get("anm00224.lzs", {}).get("block_id") == 224
                                       and members.get("anm00225.lzs", {}).get("block_id") == 225
                                       and members.get("anm10224.lzs", {}).get("block_id") == 10224)

        # claim check against the allocation manifest
        man = ownership.load()
        claims = ownership.load_claims(str(out.parent / "p4-claims.json"))
        findings = ownership.check_claims(man, claims)
        receipt["ownership"] = dict(claims=len(claims),
                                    errors=[f.as_dict() for f in ownership.errors(findings)],
                                    warnings=[f.as_dict() for f in findings if f.severity == "warning"])
        receipt["ok"] = all(v is True for k, v in receipt["checks"].items() if k.endswith(("_ok", "_added",
                                                                                           "readback",
                                                                                           "table_valid")))
    finally:
        fs.reset()
    out.write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n")
    return receipt


def _j(v):
    return v.hex() if isinstance(v, bytes) else v


if __name__ == "__main__":
    mod = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else mod.parent.parent / "finalization.json"
    r = run(mod, out)
    print(json.dumps({k: r["checks"].get(k) for k in ("char_row_added", "char_row_readback", "evilities_added",
                                                      "specials_added", "help_added", "quest_added",
                                                      "evility_table_valid", "voice_ok", "anm_ok")}, indent=1))
    print("ok:", r["ok"], "| ownership errors:", len(r["ownership"]["errors"]))
