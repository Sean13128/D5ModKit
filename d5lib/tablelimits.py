"""Field limits and printf-safety checks for database patch text.

Why this module exists (C1, 2026-10-28): the Skill Shop "Learn Evility" list draws one
row at a time with FUN_1407d22b0 / FUN_1407ce3e0 (two copies of the same drawer, see
/Volumes/Data/Decomp/d5/functions).  Both do::

    char local_138[256];                       // stack buffer, memset 0x100
    ...
    events_env_snprintf_s(local_138, 0x100, fmt, *(undefined4 *)(row + 0x38));

i.e. the row's description is used as a printf FORMAT with exactly ONE 32-bit integer
argument (the field at row+0x38).  MSVC's _vsnprintf_s calls the invalid-parameter
handler when the result does not fit -- which here is a CRT fast-fail (c0000409,
int 0x29), the reported crash.  A format with a %s/%f/%n conversion makes the same
call read an argument that was never passed.

So two independent hazards per description string:
  * byte length     -- must fit the 0x100 buffer with its NUL;
  * printf validity -- only conversions that one integer argument can satisfy.

Pure functions only: no file or database I/O happens in this module.

PROVENANCE of the numbers
-------------------------
MEASURED (read off the decompiled drawer / its buffers):
  skill.dat desc_*   255 bytes + NUL  -- local_138[256], snprintf size 0x100, in both
                        FUN_1407d22b0 (line 40/78/55) and FUN_1407ce3e0 (line 40/78/55).
                        The same drawer formats a second string into local_138 with size
                        0x80 (name/footer line, no argument), so 127 is a hard limit for
                        anything drawn there -- not modelled per field here.
INFERRED (from the game's common UI row buffers, not traced to one drawer):
  skill.dat name_*    63 bytes + NUL  -- menu row text is built in char[0x40] buffers and
                        drawn through events_env_snprintf_s(buf, 0x40, fmt, str) in the
                        row-text helpers (e.g. FUN_140791060, FUN_140793560 use 0x40 in
                        every branch).  For a name passed as a %s argument this is a
                        drawing-width limit, not the crash path.
UNKNOWN (None -> no length check, format check still applies where listed):
  magic.dat name_*/desc_*, char.dat name_*/help fields, charhelp.dat lines.  The kit
  writes them, but no buffer of theirs has been traced yet.  A None limit means "not
  checked", never "checked and fine" -- callers that learn a number should extend
  LIMITS (it is a plain dict) rather than guess.

Ground truth measured on the installed vanilla Database_0.dat (998 Skill.dat rows, 609
magic.dat rows), which is why the two tables get DIFFERENT format rules:
  skill.dat desc_*   504 rows use one %d, 111 one %%, 50 %d+%%, 6 %%%% -- and 80 rows use
                     two conversions ("Increase ATK by %d%, but INT & RES become %d.").
                     The evility drawer passes one argument, so a second conversion is
                     unspecified there (wrong number shown); it does not fault.  Kept as
                     a finding because the kit's own packs are what we ship.
  magic.dat desc_*   445 rows use exactly one %s (the attack name is substituted), so the
                     rule for that table is one %s, not one %d.
"""
from __future__ import annotations

import re
import unicodedata

__all__ = [
    "LIMITS", "FORMATTED", "UNKNOWN", "format_ok", "byte_len", "findings",
    "limit_for", "rule_for", "is_formatted", "severity",
]

UNKNOWN = None          # documented sentinel: no length limit known -> nothing checked

LANGS = ("JP", "EN", "FR", "CHN", "KOR")

# table (archive member or patch "table" value, case-insensitive) -> {field: max bytes incl. NUL}
LIMITS: dict[str, dict[str, int | None]] = {
    "skill.dat": {
        **{f"name_{l}": 63 for l in LANGS},       # INFERRED (0x40 row buffers)
        **{f"desc_{l}": 255 for l in LANGS},      # MEASURED (0x100 drawer buffer)
    },
    # Written by mods, buffer not traced yet: only reported, never flagged on length.
    "magic.dat": {**{f"name_{l}": UNKNOWN for l in LANGS},
                  **{f"desc_{l}": UNKNOWN for l in LANGS}},
    "char.dat": {"name_EN": UNKNOWN, "name_JP": UNKNOWN,
                 "help_EN": UNKNOWN, "help_JP": UNKNOWN},
    "charhelp.dat": {"line1_EN": UNKNOWN, "line2_EN": UNKNOWN, "line3_EN": UNKNOWN},
}

# the evility drawer's argument list: one integer printed with %d; '%%' is a literal
DRAWER_CONVERSIONS = frozenset({"d", "%"})
DRAWER_MAX_CONVERSIONS = 1

# table -> {field: (allowed conversions, conversions the call can satisfy)}.  Only these
# fields are used as printf FORMATS; a plain-text name may legitimately contain '%'.
FORMATTED: dict[str, dict[str, tuple[frozenset, int]]] = {
    "skill.dat": {f"desc_{l}": (DRAWER_CONVERSIONS, DRAWER_MAX_CONVERSIONS) for l in LANGS},
    # magic descriptions substitute the attack name: one %s, vanilla has 445 of them
    "magic.dat": {f"desc_{l}": (frozenset({"s", "%"}), 1) for l in LANGS},
}

_FLAGS = set("-+ 0#")
_LENGTH_MODS = ("ll", "hh", "l", "h", "L", "z", "j", "t")


def _norm_table(table: str) -> str:
    return str(table or "").strip().lower()


def limit_for(table: str, field: str, limits: dict | None = None) -> int | None:
    """max byte length (including NUL) for a field, or None when unknown."""
    lim = LIMITS if limits is None else limits
    return (lim.get(_norm_table(table)) or {}).get(field, UNKNOWN)


def rule_for(table: str, field: str, formatted: dict | None = None):
    """(allowed conversions, max conversions) when `field` is a printf format, else None"""
    fmt = FORMATTED if formatted is None else formatted
    return (fmt.get(_norm_table(table)) or {}).get(field)


def is_formatted(table: str, field: str, formatted: dict | None = None) -> bool:
    return rule_for(table, field, formatted) is not None


def byte_len(text) -> int:
    """UTF-8 byte length of `text` plus its NUL terminator (the buffer cost)."""
    if text is None:
        return 1
    return len(str(text).encode("utf-8")) + 1


def format_ok(text, allowed: "set[str] | frozenset[str] | tuple[str, ...]" = DRAWER_CONVERSIONS,
              max_conversions=DRAWER_MAX_CONVERSIONS):
    """Is `text` a safe printf format for a call that passes `max_conversions` ints?

    Returns (ok, reason).  `reason` is "" when ok.  Accepts flags (-+ 0# space),
    width, precision and length modifiers so a wider caller can allow more, but the
    default set is what the Skill-Shop drawer can satisfy: 'd' and '%%'.
    """
    s = "" if text is None else str(text)
    allowed = frozenset(allowed)
    i, n, used = 0, len(s), 0
    while i < n:
        ch = s[i]
        if ch != "%":
            i += 1
            continue
        if i + 1 >= n:
            return False, "lone trailing '%' (truncated format)"
        if s[i + 1] == "%":
            i += 2
            continue
        j = i + 1
        while j < n and s[j] in _FLAGS:
            j += 1
        if j < n and s[j] == "*":                 # width from an argument
            return False, "'*' width needs an extra argument"
        while j < n and s[j].isdigit():
            j += 1
        if j < n and s[j] == ".":
            j += 1
            if j < n and s[j] == "*":
                return False, "'*' precision needs an extra argument"
            while j < n and s[j].isdigit():
                j += 1
        for mod in _LENGTH_MODS:
            if s.startswith(mod, j):
                j += len(mod)
                break
        if j >= n:
            return False, "format ends inside a conversion after '%'"
        conv = s[j]
        if conv not in allowed:
            return False, (f"conversion '%{conv}' is not one the drawer can supply "
                           f"(allowed: " +
                           ", ".join("%" + c for c in sorted(allowed)) + ")")
        used += 1
        if used > max_conversions:
            return False, (f"{used} conversions but the drawer passes {max_conversions} "
                           f"integer argument")
        i = j + 1
    return True, ""


_DANGEROUS = re.compile(r"%[-+ 0#]*[0-9]*(?:\.[0-9]*)?(?:ll|hh|l|h|L|z|j|t)?[sn]")


def severity(kind: str, value) -> str:
    """How a finding bites: "overflow" (CRT invalid parameter -> c0000409),
    "crash" (%s/%n read a pointer that was never passed), "display" (a conversion
    the call cannot fill -> wrong number on screen)."""
    if kind == "length":
        return "overflow"
    return "crash" if _DANGEROUS.search(str(value or "")) else "display"


def findings(table, rows, limits=None, formatted=None) -> list[dict]:
    """Check row text against LIMITS.

    `rows` is an iterable of row dicts (with an optional "id") or (row_id, fields)
    pairs.  Returns [{table, id, field, kind, detail, severity}] with kind "length"
    or "format"; empty when everything fits and every format is safe.
    """
    out = []
    tname = str(table)
    for item in rows or ():
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], dict):
            rid, fields = item
        elif isinstance(item, dict):
            fields = item
            rid = item.get("id", "")
        else:
            continue
        for field, value in fields.items():
            if not isinstance(value, str):
                continue
            lim = limit_for(tname, field, limits)
            if lim is not None and byte_len(value) > lim:
                out.append({"table": tname, "id": rid, "field": field, "kind": "length",
                            "severity": severity("length", value),
                            "detail": (f"{byte_len(value)} bytes incl. NUL, limit {lim} "
                                       f"({byte_len(value) - lim} over)")})
            rule = rule_for(tname, field, formatted)
            if rule is not None:
                ok, why = format_ok(value, allowed=rule[0], max_conversions=rule[1])
                if not ok:
                    out.append({"table": tname, "id": rid, "field": field, "kind": "format",
                                "severity": severity("format", value),
                                "detail": f"{why}: {value!r}"})
    return out


def is_ascii(text) -> bool:
    """helper for census output: a value that needs no multibyte care"""
    try:
        str(text).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def is_fullwidth(text) -> bool:
    """True when the text contains EAW fullwidth characters (CHN/KOR/JP text)"""
    return any(unicodedata.east_asian_width(c) in ("F", "W") for c in str(text or ""))
