"""Names and categories of effect models for the skill editor and the effect library.

The game's 383 effect models have names and categories given in d5lib/data/effect_names.json (from their thumbnails
and the skills that use them).  Your own names override them: for the game's effects in state/effect_labels.json
(the kit's, every mod sees them), for a mod's new effects in that mod's skills.json ("effects" -> "name" / "cat").
"""
import json
import os

from . import skills

CATEGORIES = [
    ("circle", "Magic circles"), ("fire", "Fire"), ("ice", "Ice & water"), ("wind", "Wind"),
    ("lightning", "Lightning"), ("star", "Star & light"), ("dark", "Dark"), ("heal", "Heal & status"),
    ("slash", "Slashes & trails"), ("impact", "Hits & bursts"), ("explosion", "Explosions"),
    ("glow", "Glows & orbs"), ("ring", "Rings"), ("beam", "Beams & pillars"), ("projectile", "Projectiles"),
    ("aura", "Auras & swirls"), ("smoke", "Smoke & dust"), ("object", "Objects & props"),
    ("backdrop", "Backdrops & pictures"), ("custom", "New effects (mods)"), ("misc", "Other / faint"),
]
CATEGORY_NAMES = dict(CATEGORIES)
DATA = os.path.join(os.path.dirname(__file__), "data", "effect_names.json")
_vanilla = None


def vanilla():
    global _vanilla
    if _vanilla is None:
        try:
            with open(DATA, encoding="utf-8") as f:
                _vanilla = {int(k): v for k, v in json.load(f)["effects"].items()}
        except (OSError, ValueError, KeyError):
            _vanilla = {}
    return _vanilla


class Names:
    """effect id -> name / category / skills using it, with your overrides"""

    def __init__(self, mods=(), user_file=None):
        self.mods = list(mods)
        self.user_file = user_file
        self.user = {}
        if user_file and os.path.exists(user_file):
            try:
                with open(user_file, encoding="utf-8") as f:
                    self.user = {int(k): v for k, v in json.load(f).items()}
            except (OSError, ValueError):
                self.user = {}
        self.custom = {}                    # mod effects: id -> (entry, mod)
        for m in self.mods:
            for k, e in (skills.load(m).get("effects") or {}).items():
                self.custom[int(k)] = (e, m)

    def _entry(self, eid):
        eid = int(eid)
        out = dict(vanilla().get(eid) or {})
        if eid in self.custom:
            e, m = self.custom[eid]
            src = e.get("from")
            base = vanilla().get(int(src)) if src is not None else None
            out = {"name": e.get("name") or (f"New effect from {base['name']}" if base else f"New effect {eid}"),
                   "cat": e.get("cat") or "custom", "used": [], "mod": m.name, "from": src}
        out.update(self.user.get(eid) or {})
        return out

    def name(self, eid):
        return self._entry(eid).get("name") or f"Effect {int(eid)}"

    def cat(self, eid):
        return self._entry(eid).get("cat") or "misc"

    def cat_name(self, eid):
        return CATEGORY_NAMES.get(self.cat(eid), "Other")

    def used(self, eid):
        return list(self._entry(eid).get("used") or [])

    def label(self, eid):
        """'Red rune circle (1426)'"""
        return f"{self.name(eid)} ({int(eid)})"

    def tooltip(self, eid):
        e = self._entry(eid)
        lines = [f"<b>{self.name(eid)}</b> &nbsp;·&nbsp; effect {int(eid)}", self.cat_name(eid)]
        if e.get("mod"):
            lines.append(f"new effect of mod {e['mod']}" + (f", made from effect {e['from']}" if e.get("from") is not None
                                                              else ""))
        if e.get("used"):
            lines.append("used by: " + ", ".join(e["used"]))
        return "<br>".join(lines)

    def matches(self, eid, q):
        q = q.lower().strip()
        if not q:
            return True
        return q in str(int(eid)) or q in self.name(eid).lower() or q in self.cat_name(eid).lower() or \
            any(q in u.lower() for u in self.used(eid))

    # ---------------------------------------------------------------- your names
    def rename(self, eid, name=None, cat=None):
        """name / category of an effect (None: keep; '' : back to the default)"""
        eid = int(eid)
        if eid in self.custom:                          # a mod's own effect: stored with the mod
            e, m = self.custom[eid]
            d = skills.load(m)
            ent = d["effects"].setdefault(str(eid), {})
            for k, v in (("name", name), ("cat", cat)):
                if v is not None:
                    if v:
                        ent[k] = v
                    else:
                        ent.pop(k, None)
            skills.save(m, d)
            self.custom[eid] = (ent, m)
            return
        u = self.user.setdefault(eid, {})
        for k, v in (("name", name), ("cat", cat)):
            if v is not None:
                if v:
                    u[k] = v
                else:
                    u.pop(k, None)
        if not u:
            self.user.pop(eid, None)
        if self.user_file:
            os.makedirs(os.path.dirname(self.user_file), exist_ok=True)
            with open(self.user_file, "w", encoding="utf-8") as f:
                json.dump({str(k): v for k, v in sorted(self.user.items())}, f, indent=1, ensure_ascii=False)
