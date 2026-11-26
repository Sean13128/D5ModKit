"""Conservative percent encoding for Skill.dat descriptions.

The Skill Trainer formats descriptions once with an integer value and, for some
language paths, formats the resulting text again without arguments. An ASCII
literal percent escaped as ``%%`` survives the first pass as ``%`` and can be
interpreted as another conversion on the second pass. Vanilla descriptions use
the full-width percent character (UTF-8 EF BC 85) for visible percent signs.

Keep ``%d`` as a first-pass integer placeholder; encode literal percent signs as
``％``. This is a conservative data rule, not proof of the reported crash's
cause. It does not check buffer lengths or other game text paths.
"""

import re


def bad_format(text) -> bool:
    """Flag ASCII percent signs other than the supported integer placeholder."""
    if not text:
        return False
    i = 0
    while i < len(text):
        if text[i] == "%":
            if text[i:i + 2] != "%d":
                return True
            i += 2
        else:
            i += 1
    return False


def format_text(text) -> str:
    """Keep %d placeholders and convert literal percent runs to vanilla's sign.

    A run of 1, 2, or 4 ASCII percent characters denotes one visible sign in
    the plain, once-escaped, or twice-escaped source respectively. Longer runs
    are deliberately left for manual review rather than silently losing text.
    """
    if not text:
        return text or ""
    out = []
    i = 0
    while i < len(text):
        if text[i:i + 2] == "%d":
            out.append("%d")
            i += 2
        elif text[i] == "%":
            end = i + 1
            while end < len(text) and text[end] == "%":
                end += 1
            count = end - i
            out.append("％" if count in (1, 2, 4) else text[i:end])
            i = end
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


_PROSE = re.compile(r"%\d*[ds]|%+")


def prose(text) -> str:
    """Row-writer rule: keep %d / %s (width digits allowed) placeholders, turn every other ASCII
    percent run into the full-width sign (one visible sign per run of 1, 2 or 4; longer runs are
    left so the text gate fails them).  Idempotent."""
    if not text:
        return text or ""

    def one(m):
        t = m.group()
        return "％" if set(t) == {"%"} and len(t) in (1, 2, 4) else t
    return _PROSE.sub(one, text)


def fix_row(row, langs=("JP", "EN", "FR", "CHN", "KOR")) -> list:
    """Rewrite description fields in place; return the fields that changed."""
    changed = []
    for lang in langs:
        key = "desc_" + lang
        if key not in row:
            continue
        old = row.get(key) or ""
        new = format_text(old)
        if new != old:
            row[key] = new
            changed.append(key)
    return changed
