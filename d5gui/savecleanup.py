"""Keep the saves in step with the mods (d5lib.savegame).

* After a mod or a new character is deleted: a save keeps every unit of the deleted character; with its row gone the
  game shows a 'DLC Dummy' in its place, or crashes at the next battle when no row has the class.  offer() lists the
  saves that hold such units (the game's save folder and the saves the kit keeps for profiles) and, for the checked
  ones, takes the units out as the game's Dismiss does, puts units wearing one of the mod's outfits back into their
  own look and clears the progress of its recruit quests, so a new quest on that slot starts fresh.
* Home > More > Check saves (check_saves): the same for characters deleted earlier, and recruit quests whose progress
  doesn't match the army: shown done while the character isn't in the save (progress another quest left on the
  slot: it can be done again), or the character is there but its quest isn't done (it is marked done, so the Quest
  Shop doesn't recruit a second one).
* After an install (after_install), and in Check saves: units made before their class's weapon mastery changed.  A
  unit keeps the ranks it was made with (the game copies the class's into it once), and starting weapon levels are
  given to new units only, so such units get their class's ranks now, and weapon levels below the class's starting
  level are raised (levels earned in game stay).  Only the game's save folder: the saves kept for other profiles go
  with other mods.
* Stages (stage_targets, Check saves): a save keeps a slot for every stage it knew; the game adds a mod's new
  stages to a save by itself when it loads it (seen in game, 2026-10-16).  A slot whose stage no mod has any more (a
  deleted mod) is emptied: the stage list would still show it, and the game closes when its cursor reaches a stage
  it can't find.  Switched-off mods keep theirs.
The saves are copied to state/save_backups first.  The game's own characters and quests are never touched.
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                             QVBoxLayout)

from d5lib import savegame

from .workspace import KIT_DIR, game_running


def _vanilla_chars(ws):
    from .dbservice import get_service
    try:
        return get_service(ws).vanilla("char.dat")
    except Exception:                              # no game folder: every added row counts
        return None


def mod_info(ws, mod):
    """what of `mod` saves can hold (savegame.mod_characters), plus guard {slot: class ids}: other mods' recruit
    quests on the same progress slots (a save that has their character keeps the slot's progress)"""
    van = _vanilla_chars(ws)
    info = savegame.mod_characters(mod, van)
    guard = {}
    for m in ws.mods.all_mods():
        if m.id == mod.id:
            continue
        other = savegame.mod_characters(m, van)
        for r in (m.load_patch("db", "Quest.dat.json") or {}).get("added") or []:
            slot = int(r.get("sort_order", -1))
            if slot in info["quests"] and int(r.get("reward_type", 0)) in (5, 6):
                cls = int(r.get("reward_value", -1))
                guard.setdefault(slot, set()).update({cls} | {o for o, b in other["outfits"].items() if b == cls})
    info["guard"] = guard
    return info


def offer(parent, ws, what, classes, outfits=None, quests=None, guard=None):
    """`what` was deleted (a mod or a character): offer to take `classes` out of the saves that hold them.
    classes {id: name}, outfits {outfit class: base class}, quests {progress slot: title}"""
    classes = {int(k): v for k, v in (classes or {}).items()}
    outfits = {int(k): int(v) for k, v in (outfits or {}).items()}
    quests = {int(k): v for k, v in (quests or {}).items()}
    if not classes and not outfits:
        return
    look = set(classes) | set(outfits)
    rows = []
    for label, root in savegame.save_roots(KIT_DIR):
        for path, s, army, res, qs in savegame.find(look, quests, root=root):
            have = {u.cls for u in s.units()}
            qs = {q: st for q, st in qs.items() if not (guard and have & set(guard.get(q, ())))}
            bits = [f"{u.name} Lv{u.level}" + (" (back to own look)" if u.cls in outfits and u.cls not in classes
                                               else "") for u in army]
            bits += [f"{u.name} (waiting to join)" for u in res]
            bits += [f"quest “{quests[q]}”: progress cleared" for q in qs]
            if bits:
                rows.append((label, path, s, bits, dict(classes=classes, outfits=outfits, quests=list(quests),
                                                       guard=guard)))
    if not rows:
        ws.log(f"No save holds units of {what}.")
        return
    names = sorted(set(classes.values()))
    intro = (f"<b>{what}</b> is deleted, but these saves still have "
             f"{', '.join(names) if names else 'units wearing its outfits'}. Without the mod the game shows them as "
             "'DLC Dummy' or crashes at the next battle.<br><br>Take them out of the checked saves? The game's own "
             "characters stay; a unit in one of its outfits goes back to its own look"
             + (", and its recruit quest starts fresh" if quests else "") + ".")
    if not _run(parent, ws, intro, rows):
        ws.log(f"Saves left as they are: they still hold units of {what}.")


RANK_LETTERS = "EDCBAS"
WEAPON_NAMES = ["Fist", "Sword", "Spear", "Bow", "Gun", "Axe", "Staff", "Monster (physical)", "Monster (magic)",
                "Armor"]


def rank_letter(v):
    """the letter the game shows for a weapon aptitude (0x14015b8b0)"""
    return "–" if not v else RANK_LETTERS[min(6, int(v) // 5 + 1) - 1]


def weapon_targets(ws):
    """{class id: (aptitudes, starting levels or None)} as the next install gives the classes"""
    from d5lib import weaponlevels
    from .dbservice import get_service
    levels = weaponlevels.merged(ws.mods.enabled_mods())
    out = {}
    for r in get_service(ws).table("char.dat").rows:
        if r["id"] in out or r["name_EN"] in savegame.RESERVED_NAMES:
            continue                               # (the game reads the first row of an id)
        out[r["id"]] = ([r["mastery_" + n] for n in weaponlevels.WEAPONS], levels.get(r["id"]))
    return out


def _weapon_text(u, changes):
    now = u.weapons()
    bits = []
    for w, apt, lv in changes:
        if apt is not None:
            bits.append(f"{WEAPON_NAMES[w]} rank {rank_letter(now[w][1])} → {rank_letter(apt)}")
        if lv is not None:
            bits.append(f"{WEAPON_NAMES[w]} Lv {now[w][0]} → {lv}")
    return f"{u.name} Lv{u.level}: " + ", ".join(bits)


def weapon_plans(ws, path, s, targets):
    """([text], plan) for the units of save `s` whose weapon mastery isn't their class's (savegame.weapon_mismatches)"""
    bits, plan = [], {}
    for u, changes in savegame.weapon_mismatches(s, targets):
        bits.append(_weapon_text(u, changes))
        plan[u.slot] = (u.cls, changes)
    return bits, plan


def after_install(parent, ws):
    """after an install: offer to give units made before a weapon mastery change their class's ranks and starting
    levels (the game's save folder only)"""
    try:
        targets = weapon_targets(ws)
    except Exception as e:
        ws.log(f"(saves not checked for weapon mastery: {e})")
        targets = {}
    rows = []
    for path in savegame.save_files(savegame.save_root()):
        try:
            s = savegame.Save(path)
        except (OSError, ValueError):
            continue
        bits, plan = weapon_plans(ws, path, s, targets) if targets else ([], {})
        if bits:
            rows.append(("", path, s, bits, dict(weapons=plan)))
    if not rows:
        return
    intro = ("These saves have units made before their weapon mastery was changed. A unit keeps the ranks it was "
             "made with, and starting weapon levels are given to new units, so they don't show your changes yet."
             "<br><br><b>Update them?</b> Their ranks become their class's, and weapon levels below the starting "
             "level are raised (levels earned in game stay).")
    if not _run(parent, ws, intro, rows, title="Update saves", ok="Update the checked saves"):
        ws.log("Saves left as they are: units made earlier keep their weapon ranks and levels.")


def stage_targets(ws):
    """(wanted {map id: savegame.stage_info}, known {map id}): the stages the switched-on mods add (dungeon.dat rows
    after the game's), and every stage of the game and of any mod (a switched-off mod keeps its slots)"""
    from .dbservice import get_service
    from d5lib import mapfile
    svc = get_service(ws)
    van = svc.vanilla("dungeon.dat").rows
    rows = svc.table("dungeon.dat").rows
    lang = ws.settings.get("language", "EN")
    info = savegame.stage_info([bytes(r.raw) for r in rows], lang)
    van_ids = {mapfile.DungeonRecord(bytes(r.raw)).map_id for r in van}
    wanted = {m: v for m, v in info.items() if v[4] >= len(van) and m not in van_ids}
    known = set(van_ids) | set(info)
    for m in ws.mods.all_mods():
        p = m.load_patch("db", "dungeon.dat.json") or {}
        for r in p.get("added") or []:
            if "map_id" in r:
                known.add(int(r["map_id"]))
        for fields in (p.get("rows") or {}).values():
            if "map_id" in fields:
                known.add(int(fields["map_id"]))
    return wanted, known


def stage_plans(s, targets):
    """([text], {}, drop [map id]) for one save: slots of stages of deleted mods (new stages the game adds itself)"""
    wanted, known = targets
    _, drop = savegame.stage_mismatches(s, {}, known)
    bits = [f"stage map{m:05d} of a deleted mod: taken off the stage list" for m in drop]
    return bits, {}, drop


def save_plans(ws):
    """Check saves: rows [(label, path, Save, [text], plan)] for every save that doesn't match the mods"""
    from .dbservice import get_service
    svc = get_service(ws)
    van = svc.vanilla("char.dat")
    have_rows = {r["id"]: r["name_EN"] for r in svc.table("char.dat").rows}
    known, outfit_base, mod_chars = set(), {}, {}
    for m in ws.mods.all_mods():                   # a switched-off mod's characters are kept for when it is back
        info = savegame.mod_characters(m, van)
        known |= set(info["classes"]) | set(info["outfits"])
        outfit_base.update(info["outfits"])
        mod_chars.update(info["classes"])
    game_chars = {}
    for r in van.rows:
        if r["id"] < 1000 and r["name_EN"] not in savegame.RESERVED_NAMES:
            game_chars.setdefault(r["name_EN"], r["id"])
    # recruit quests of the characters the switched-on mods make (as the next install has them)
    recruits = []
    for r in svc.table("Quest.dat").rows:
        cls = r["reward_value"]
        if r["reward_type"] == 5 and cls in mod_chars and cls in have_rows:
            looks = {cls} | {o for o, b in outfit_base.items() if b == cls}
            recruits.append((r["sort_order"], r["name_EN"], have_rows[cls], looks))
    try:
        targets = weapon_targets(ws)
    except Exception:
        targets = {}
    try:
        stages = stage_targets(ws)
    except Exception:
        stages = None
    rows = []
    for label, root in savegame.save_roots(KIT_DIR):
        for path in savegame.save_files(root):
            try:
                s = savegame.Save(path)
            except (OSError, ValueError):
                continue
            classes, outfits, bits = {}, {}, []
            weapons = {}
            add, drop = {}, []
            if not label:                          # (the saves kept for other profiles go with other mods)
                wbits, weapons = weapon_plans(ws, path, s, targets)
                bits += [b + " (made before its weapon mastery changed: updated)" for b in wbits]
                if stages:
                    sbits, add, drop = stage_plans(s, stages)
                    bits += sbits
            for u in s.units():
                c = u.cls
                if c in known or (c in have_rows and have_rows[c] not in savegame.RESERVED_NAMES):
                    continue
                if c not in have_rows and u.name in game_chars and c < 1000:
                    outfits[c] = game_chars[u.name]
                    bits.append(f"{u.name} Lv{u.level}: back to own look (outfit of a deleted mod)")
                else:
                    classes[c] = have_rows.get(c) or u.name or f"class {c}"
                    bits.append(f"{u.name} Lv{u.level}: taken out (character of a deleted mod)")
            reset, finish = [], []
            for slot, title, name, why in savegame.recruit_mismatches(s, recruits):
                if why == "missing":
                    reset.append(slot)
                    bits.append(f"quest “{title}” shows done but {name} isn't in this save: it can be done again")
                else:
                    finish.append(slot)
                    bits.append(f"{name} is here but quest “{title}” isn't done: marked done")
            if bits:
                rows.append((label, path, s, bits, dict(classes=classes, outfits=outfits, quests=reset,
                                                       finish=finish, weapons=weapons, stages=add,
                                                       drop_stages=drop)))
    return rows


def check_saves(parent, ws):
    """Home > More > Check saves (see the module text)"""
    rows = save_plans(ws)
    if not rows:
        QMessageBox.information(parent, "Check saves", "Every save matches your mods: nothing to clean.")
        return
    intro = ("These saves don't match your mods. The game's own characters and quests are never changed.<br><br>"
             "<b>Fix the checked saves?</b>")
    _run(parent, ws, intro, rows)


def apply_plans(ws, rows, paths=None, why="before_cleanup"):
    """clean the saves of `rows` (all, or `paths`) after a backup -> backup folder"""
    plans = {path: plan for _, path, _, _, plan in rows}
    paths = list(plans) if paths is None else paths
    backup = savegame.backup(paths, KIT_DIR, why)
    for path in paths:
        p = plans[path]
        try:
            s = savegame.Save(path)
            lines = savegame.clean(s, p.get("classes") or {}, p.get("quests") or (), p.get("outfits") or {},
                                   finish=p.get("finish") or (), guard=p.get("guard"))
            lines += savegame.fix_weapons(s, p.get("weapons"))
            lines += savegame.fix_stages(s, p.get("stages"), p.get("drop_stages"))
            if lines:
                s.write()
            ws.log(f"{_name(path)}: " + ("; ".join(lines) if lines else "nothing to change"))
        except (OSError, ValueError) as e:
            ws.log(f"{_name(path)}: not changed ({e})")
    ws.log(f"Copies of the saves as they were: {os.path.relpath(backup, KIT_DIR)}")
    return backup


def _run(parent, ws, intro, rows, title="Clean saves", ok="Fix the checked saves"):
    """the dialog for rows [(label, path, Save, [text], plan)], then the checked saves cleaned -> True if done"""
    dlg = _Dialog(parent, intro, rows, title, ok)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    paths = dlg.checked()
    if not paths:
        return False
    while game_running():
        if QMessageBox.question(parent, title, "Close Disgaea 5 first: the game writes its saves when it "
                                "closes.\n\nClosed it?", QMessageBox.StandardButton.Retry |
                                QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Retry:
            return False
    apply_plans(ws, rows, paths)
    return True


def _name(path):
    player = os.path.basename(os.path.dirname(os.path.dirname(path)))
    return f"{os.path.splitext(os.path.basename(path))[0].replace('_', ' ')} (player {player})"


class _Dialog(QDialog):
    def __init__(self, parent, intro, rows, title="Clean saves", ok="Fix the checked saves"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 460)
        lay = QVBoxLayout(self)
        lab = QLabel(intro + " The saves are copied to state/save_backups first.")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.list = QListWidget()
        for label, path, s, bits, _ in rows:
            text = f"{_name(path)}{' - ' + label if label else ''}: {s.chapter or s.title}\n    " + "\n    ".join(bits)
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, path)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(it)
        lay.addWidget(self.list, 1)
        bb = QDialogButtonBox()
        bb.addButton(ok, QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton("Leave the saves", QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def checked(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]
