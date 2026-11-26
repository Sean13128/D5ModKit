"""Rewrite a *built* class pack: renumber its family consistently, or normalise its text to ASCII.

Two operations, both learned from a live failure and both refused rather than done silently:

* `renumber(mod_dir, mapping)` moves one or more class families to new ids and rewrites **every**
  field that carries the family, the family + rank, or the family's decade.  The A/B probes of
  D1CWEDGE2/D1CWEDGE3 were hand-renumbered and missed `help_id`, so both wedging builds pointed at
  a charhelp row the same build had moved away - a third variable in an experiment meant to isolate
  two.  After the rewrite the pack is re-checked (R8) and a dangling link raises.

* `ascii_text(mod_dir)` rewrites the pack's own text to printable ASCII.  Every length the game
  reads next to that text is a *character* count while the storage is a UTF-8 byte pool
  (`database._write_pool`), and the charhelp line slots are 92 fixed bytes; a typographic character
  is 2-3 bytes where the game counts 1.  Every working shipped pack is pure ASCII.

Pure file work: no game, no exe, no installer state, no Unicorn.
"""
from __future__ import annotations

import json
import os

from . import classcheck

# field name -> how its value relates to the family
RANK_KEYS = ("id", "next_id")                  # may be family + rank
FAMILY_KEYS = ("family", "help_id", "char_id")  # the family base itself
DECADE_KEYS = ("voice_group", "group")          # family // 10

# what a typographic character becomes.  Applied longest-first, then anything left is a refusal.
TRANSLIT = {
    "\u2014": "-",       # em dash: the character every D1C class pack carried
    "\u2013": "-",       # en dash
    "\u2012": "-",
    "\u2212": "-",
    "\u2019": "'",
    "\u2018": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00a0": " ",
    "\u00b7": ".",
    "\u2022": "*",
    "\u00d7": "x",
    "\u00e9": "e",
    "\u00e8": "e",
    "\u00ea": "e",
    "\u00e1": "a",
    "\u00e0": "a",
    "\u00e4": "a",
    "\u00f6": "o",
    "\u00fc": "u",
    "\u00df": "ss",
}
# spaced forms first, so "word \u2014 word" becomes "word - word" and not "word  -  word"
SPACED = {" \u2014 ": " - ", " \u2013 ": " - ", "\u2014 ": "- ", " \u2014": " -"}


def _json_files(mod_dir):
    root = os.path.join(str(mod_dir), "patches")
    for folder, _dirs, names in os.walk(root):
        for n in sorted(names):
            if n.endswith(".json"):
                yield os.path.join(folder, n)


def _rewrite(mod_dir, fn):
    """Apply `fn(value)` to every string in every patch JSON; return the number changed."""
    changed = 0
    for path in _json_files(mod_dir):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        def walk(x):
            if isinstance(x, dict):
                return {k: walk(v) for k, v in x.items()}
            if isinstance(x, list):
                return [walk(v) for v in x]
            if isinstance(x, str):
                new = fn(x)
                return new
            return x

        new = walk(data)
        if new != data:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(new, f, indent=1, ensure_ascii=False)
                f.write("\n")
            changed += 1
    return changed


def ascii_text(mod_dir, strict=True):
    """Rewrite every string the pack carries to printable ASCII. -> {original char: count}.

    `strict` refuses (ValueError) when a character has no mapping, instead of guessing.
    """
    seen = {}

    def fix(text):
        for spaced, plain in SPACED.items():
            if spaced in text:
                seen[spaced[1]] = seen.get(spaced[1], 0) + text.count(spaced)
                text = text.replace(spaced, plain)
        out = []
        for ch in text:
            if 0x20 <= ord(ch) <= 0x7E:
                out.append(ch)
                continue
            if ch in TRANSLIT:
                seen[ch] = seen.get(ch, 0) + 1
                out.append(TRANSLIT[ch])
                continue
            if strict:
                raise ValueError("no ASCII mapping for U+%04X in %r" % (ord(ch), text[:60]))
            out.append("?")
        return "".join(out)

    _rewrite(mod_dir, fix)
    return seen


def _spec_path(mod_dir, family):
    return os.path.join(str(mod_dir), "patches", "classes", "class_%d.json" % int(family))


def renumber(mod_dir, mapping, strict=True):
    """Move class families `mapping = {old: new}` and rewrite every id that depends on them.

    Rewritten: char.dat row ids (`family` .. `family+5`) and `help_id`; JobRank row ids; charhelp
    `id` and `char_id`; charPersonal `voice_group` / any `group`; the class descriptor's `family`
    (and its file name); the mastery/evility blocks that name a family.  Values that are *not*
    derived from the family are left untouched, and `strict` re-checks the help links afterwards.
    """
    mapping = {int(k): int(v) for k, v in mapping.items()}
    for old, new in mapping.items():
        if new % 10 or new == old:
            raise ValueError("new family %d for %d must be a different multiple of 10" % (new, old))

    def rewrite(obj):
        if isinstance(obj, dict):
            return {k: (rewrite_family(v, k) if isinstance(v, int) and not isinstance(v, bool)
                        else rewrite(v)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [rewrite(v) for v in obj]
        return obj

    def rewrite_family(value, key):
        for old, new in mapping.items():
            if key in FAMILY_KEYS and value == old:
                return new
            if key in RANK_KEYS and old <= value <= old + 9:
                return new + (value - old)
            if key in DECADE_KEYS and value == old // 10:
                return new // 10
        return value

    for path in _json_files(mod_dir):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        new = rewrite(data)
        if new != data:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(new, f, indent=1, ensure_ascii=False)
                f.write("\n")

    for old, new in mapping.items():
        src = _spec_path(mod_dir, old)
        if os.path.exists(src) and old != new:
            os.replace(src, _spec_path(mod_dir, new))

    if strict:
        dangling = [f for f in classcheck.help_link_findings(mod_dir) if f["severity"] == "error"]
        if dangling:
            raise ValueError("renumber left a dangling description link: %s"
                             % json.dumps(dangling, sort_keys=True))
    return mapping
