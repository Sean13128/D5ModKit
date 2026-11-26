"""BANKGUI1: the logic behind the Character Bank page (no widgets: tested headless).

Everything with a save format is `tools/unit_bank.py` (which calls `d5lib/unitbank.py`); this module only
turns its answers into cards and plain sentences.  Art goes through the editor's own calls
(`d5lib.sprites`, `d5lib.anm`), reading the installed game's archives read-only.

Ideas credited to Cryswar's Overlord source (Unlicense) for unit storage: none were needed; the bank design is ours
(docs/CHARACTER_BANK.md).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
for p in (str(KIT), str(KIT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import unit_bank  # noqa: E402  tools/unit_bank.py: the CLI's own export / import / refusals
from d5lib import savegame, unitbank  # noqa: E402

BADGES = {"d1c": "D1C", "d4": "D4", "dd2": "DD2", "drpg": "DRPG", "drpgsource": "DRPG"}


@dataclass
class Card:
    side: str                    # "save" | "bank"
    key: str                     # roster slot (save) or file name (bank)
    name: str
    title: str
    cls: int
    level: int
    game: str                    # D5 / D4 / D1C / DD2 / DRPG / ?
    game_why: str = ""           # where the badge came from
    refusal: str | None = None   # why the action on this card is refused (plain sentence), None = allowed
    details: list = field(default_factory=list)   # lines for the detail pane
    path: str | None = None      # bank file
    serial: int | None = None    # save card: the unit's serial when listed (a changed save refuses the stale card)


def vanilla_rows(fs):
    """{class id: row} of the UNMODDED char.dat (the editor's GameFS reads vanilla members through the install backups)"""
    from d5lib import database
    return {r["id"]: r for r in database.load_table("char.dat", fs.read("Database/Database_0.dat/char.dat")).rows}


def refuse_live(path):
    """a path under the game's live save folder is refused unless the page opens it as a real save (live=True)"""
    if unit_bank.under_live(path):
        raise unit_bank.Refused(f"{path} is the game's live save folder. Open it as a real save (it is backed up "
                                f"before every change) or work on a copy.")


PREFIXES = {"D1C_": "D1C", "D4_": "D4", "DD2_": "DD2", "DRPG_": "DRPG"}


def game_badges(mods_dir):
    """{class id: (badge, why)} of every class row an installed mod adds, from the mod that owns the row:
    mod.json source_import (source_game, or identity.source), else the import pack's folder prefix (DRPG packs
    carry no source key).  A mod that is not a source import gives badge "?" with the reason."""
    out = {}
    if not mods_dir or not os.path.isdir(mods_dir):
        return out
    for d in sorted(os.listdir(mods_dir)):
        try:
            added = json.loads(Path(mods_dir, d, "patches/db/char.dat.json").read_text()).get("added") or []
            meta = json.loads(Path(mods_dir, d, "mod.json").read_text())
        except (OSError, ValueError):
            continue
        si = meta.get("source_import") or {}
        src = str(si.get("source_game") or (si.get("identity") or {}).get("source") or "").lower()
        game = BADGES.get(src) or next((g for pre, g in PREFIXES.items() if d.startswith(pre)), None)
        for r in added:
            out[int(r["id"])] = ((game, f"added by installed pack {d}") if game else
                                 ("?", f"added by installed mod {d}, which names no source game"))
    return out


def badge_for(cls, badges, vanilla):
    """-> (badge, why).  A class the clean game has is D5; otherwise only the owning installed mod decides."""
    if cls in badges:
        return badges[cls]
    if cls in vanilla:
        return "D5", "a row of the unmodded game"
    return "?", f"class {cls} is in no installed mod and not in the unmodded game"


def _details(record: bytes, entry=None):
    """what the record itself says without decoding new formats: weapon masteries, learned-evility bits, extras"""
    weapons = []
    for w in range(savegame.WEAPON_COUNT):
        o = savegame.U_WEAPONS - 0 + w * savegame.WEAPON_SIZE
        weapons.append((record[o + 4], record[o + 6]))
    bits = sum(bin(b).count("1") for b in record[0x2E70:0x2E70 + 125])
    lines = [f"Weapon mastery levels (fist .. armor): {', '.join(str(l) for l, _ in weapons)}",
             f"Learned evilities (native bitmap): {bits}"]
    if entry and entry.get("learned_extra"):
        lines.append(f"Learned evilities past the bitmap (banked): {len(entry['learned_extra'])}")
    return lines


def save_cards(save_path, installed, vanilla, badges=None, live=False):
    """one Card per army/reserve unit of a save copy; refusal = what Export would say"""
    if not live:
        refuse_live(save_path)
    save = savegame.Save(str(save_path))
    badges = badges or {}
    out = []
    for u in save.units():
        why = unit_bank.story_locked(u.cls, vanilla, u.reserve)
        base = savegame.ROSTER + u.slot * savegame.UNIT
        rec = bytes(save.state[base:base + savegame.UNIT])
        g, gw = badge_for(u.cls, badges, vanilla)
        out.append(Card("save", str(u.slot), u.name, u.title, u.cls, u.level, g, gw,
                        f"Cannot export: story-locked, {why}." if why else None,
                        [f"Roster slot {u.slot}" + (" (reserve)" if u.reserve else ""), f"Class {u.cls}",
                         *_details(rec)], serial=u.serial))
    return out, save


def import_refusal(entry, installed, vanilla, save=None):
    """the sentence for what Import would refuse for this bank entry, else None (the CLI's three rules)"""
    cls = int(entry["class"])
    if cls not in installed:
        return (f"Cannot import: class {cls} ({entry['name']}) is not installed. "
                f"Install its class/character mod first.")
    why = unit_bank.story_locked(cls, vanilla)
    if why:
        return f"Cannot import: story-locked, {why}."
    if save is not None and save.army_count + save.reserve_count >= savegame.SLOTS:
        return (f"Cannot import: the save is full ({save.army_count} army + {save.reserve_count} reserve = "
                f"the {savegame.SLOTS}-unit limit).")
    return None


def bank_cards(bank_dir, installed, vanilla, save=None, badges=None):
    """one Card per unit file in the bank folder"""
    badges = badges or {}
    out = []
    if not bank_dir or not os.path.isdir(bank_dir):
        return out
    for p in sorted(Path(bank_dir).glob("*" + unit_bank.EXT)):
        try:
            doc = json.loads(p.read_text())
            unit_bank.check_doc(doc, p.name)              # the same checks Import makes: a damaged file shows as unreadable
            for e in doc["units"]:
                g, gw = badge_for(int(e["class"]), badges, vanilla)
                out.append(Card("bank", p.name, e["name"], e.get("title", ""), int(e["class"]), int(e["level"]),
                                g, gw, import_refusal(e, installed, vanilla, save),
                                [f"File {p.name}", f"Class {e['class']}", *_details(unitbank.entry_record(e), e)],
                                str(p)))
        except (OSError, ValueError, KeyError, unit_bank.Refused) as ex:
            out.append(Card("bank", p.name, p.name, "", 0, 0, "?", "unreadable file", f"Cannot read this file: {ex}.", [], str(p)))
    return out


def backup_note(folder):
    return f" The save was backed up first: {folder}." if folder else ""


def do_export(save_path, card, bank_dir, vanilla, move=True, live=False, kit_dir=None):
    """-> (message, ok).  move: the unit leaves the save copy (the bank holds it now).  Refusals come back as
    sentences, never raised.  live: the page opened a real save (backed up first, see unit_bank.protected)"""
    try:
        if not live:
            refuse_live(save_path)
        out, entry = unit_bank.export(save_path, card.key, bank_dir, vanilla, move=move, live=live, kit_dir=kit_dir,
                                        serial=card.serial)
        gear = (f" Its {entry['unequipped']} equipped items went into the save's item bag." if move else
                f" Its {entry['unequipped']} equipped items stayed in the save.") if entry.get("unequipped") else ""
        where = "; it is no longer in the save" if move else ""
        return f"Exported {entry['name']} to {out.name}{where}.{gear}{backup_note(entry.get('backup'))}", True
    except (unit_bank.Refused, ValueError, OSError) as ex:
        return f"Cannot export {card.name}: {ex}", False


def do_import(save_path, card, installed, vanilla, skill_ids=None, live=False, kit_dir=None):
    try:
        if not live:
            refuse_live(save_path)
        res, entry = unit_bank.import_(card.path, save_path, installed, vanilla, move=True, skill_ids=skill_ids,
                                       live=live, kit_dir=kit_dir)
        extra = f" {res['companion']} evilities past the game's bitmap went into the save's companion file." if res.get("companion") else ""
        moved = " The bank file moved to the imported folder." if res.get("moved_to") else ""
        lost = "".join(f" Note: {w}." for w in res["warnings"] if "not carried" in w)
        return (f"Imported {entry['name']} into roster slot {res['slot']}.{extra}{moved}{lost}"
                f"{backup_note(res.get('backup'))}"), True
    except (unit_bank.Refused, ValueError, OSError) as ex:
        return f"Cannot import {card.name}: {ex}", False


# --------------------------------------------------------------------------------------------- art
class Art:
    """stand pose + face portrait of a class, from the installed game's archives (read-only).  -> (stand, face, why)"""

    def __init__(self, game_dir, db_path=None):
        from d5lib import database
        from d5lib.gamefs import GameFS
        self.game_dir = game_dir
        self.fs = GameFS(game_dir)
        db_path = db_path or os.path.join(game_dir, "Data", "Database", "Database_0.dat")
        self.rows = {r["id"]: r for r in database.load_database(db_path)["char.dat"].rows}
        self._cache = {}
        self._faces = None

    def _open(self, num):
        from d5lib import anm, sprites
        v = sprites.sprite_vpath(self.fs, num)
        try:
            data = self.fs.read(v)
        except Exception:                                                  # noqa: BLE001
            data = self.fs.read(f"Anime/ANM_HI_JP.dat/anm{num:05d}.lzs")
        return sprites.preview_file(self.fs, anm.load(data))

    def _render(self, num, anim_ids, pal):
        from d5lib import anm
        f = self._open(num)
        for aid in anim_ids:
            if anm.has_animation(f, aid):
                items = anm.evaluate(f, ("id", aid), anm.frame_times(f, ("id", aid))[0], nested=True)
                if items:
                    return anm.render_items(f, items, min(pal, max(0, len(f.palettes) - 1)))[0]
        raise LookupError(f"anm{num:05d} has no drawable pose {anim_ids}")

    def resolve(self, cls):
        if cls in self._cache:
            return self._cache[cls]
        row = self.rows.get(cls)
        if row is None:
            res = (None, None, f"class {cls} is not in the installed char.dat")
        elif not row["sprite_id"]:
            res = (None, None, f"class {cls} has no sprite id")
        else:
            sprite, colour = int(row["sprite_id"]), int(row["color_id"])
            pal = colour - sprite if 0 <= colour - sprite < 10 else colour % 10
            why = []
            try:
                stand = self._render(sprite, (1001, 1), pal)
            except Exception as ex:                                        # noqa: BLE001
                stand = None
                why.append(f"stand anm{sprite:05d}: {ex}")
            try:
                from d5lib import outfits           # face block 9017, animation 10000 + colour id, read from the INSTALLED
                if self._faces is None:             # resident pack: imported characters' faces are painted into it
                    self._faces = outfits._face_file(self.fs, fresh=True)
                face = outfits.base_face_image(self.fs, colour, self._faces)
            except Exception:                                              # noqa: BLE001
                face = None
            res = (stand, face, "; ".join(why))
        self._cache[cls] = res
        return res
