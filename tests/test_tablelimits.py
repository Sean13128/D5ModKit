"""Tests for d5lib.tablelimits (C1: Skill-Shop description buffers + printf safety)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import tablelimits as tl


# ---------------------------------------------------------------- format_ok
def test_plain_text_is_ok():
    for s in ("", "DEF increased by 10.", "HP +5%% (flat)", "%d"):
        ok, why = tl.format_ok(s)
        assert ok, (s, why)
    # an unescaped single '%' is a real hazard (the game's own text writes '%%')
    ok, why = tl.format_ok("HP +5% (flat)")
    assert not ok and "%(" in why


def test_double_percent_is_ok():
    ok, why = tl.format_ok("DEF & RES increased by 50%% when HP is under 25%%.")
    assert ok, why
    ok, why = tl.format_ok("SPD Aptitude increased by %d%%.")
    assert ok, why


def test_flags_width_precision_ok_for_d():
    for s in ("+%03d", "%-5d", "%.2d", "% 4d", "%#5d"):
        ok, why = tl.format_ok(s)
        assert ok, (s, why)


def test_lone_trailing_percent_rejected():
    ok, why = tl.format_ok("boost 50%")
    assert not ok
    assert "trailing" in why


def test_bad_conversions_rejected():
    for s in ("%x", "%f", "%n", "%s", "%d %d", "%5s"):
        ok, _ = tl.format_ok(s)
        assert not ok, s


def test_two_d_conversions_rejected():
    ok, why = tl.format_ok("%d and %d")
    assert not ok
    assert "conversions" in why


def test_allowed_set_is_caller_specified():
    ok, _ = tl.format_ok("%s", allowed={"s", "%"}, max_conversions=1)
    assert ok
    ok, _ = tl.format_ok("%d %s", allowed={"d", "s", "%"}, max_conversions=2)
    assert ok


# ---------------------------------------------------------------- byte_len
def test_byte_len_counts_nul():
    assert tl.byte_len("") == 1
    assert tl.byte_len("abc") == 4


def test_byte_len_multibyte():
    s = "ＨＰ＋５０%"                      # fullwidth: 3 bytes each in UTF-8
    assert tl.byte_len(s) == len(s.encode("utf-8")) + 1
    assert tl.byte_len(s) > len(s) + 1
    # 84 fullwidth chars already exceed the 255-byte description buffer
    assert tl.byte_len("\uff21" * 85) == 256


# ---------------------------------------------------------------- findings
def _desc(n, ch="A"):
    return ch * (n - 1)                        # n bytes with the NUL


def test_clean_skill_row_has_no_findings():
    row = {"id": 8228, "name_EN": "Last Fortress",
           "desc_EN": "DEF & RES increased by 50%% when HP is under 25%%."}
    assert tl.findings("Skill.dat", [row]) == []


def test_over_long_desc_finding():
    row = {"id": 9001, "desc_EN": _desc(256)}
    found = tl.findings("Skill.dat", [row])
    assert len(found) == 1
    f = found[0]
    assert (f["table"], f["id"], f["field"], f["kind"]) == ("Skill.dat", 9001, "desc_EN", "length")
    assert "256 bytes" in f["detail"] and "limit 255" in f["detail"]


def test_desc_at_limit_is_fine():
    assert tl.findings("Skill.dat", [{"id": 1, "desc_EN": _desc(255)}]) == []


def test_over_long_name_finding():
    found = tl.findings("Skill.dat", [{"id": 2, "name_JP": "N" * 63}])
    assert [f["kind"] for f in found] == ["length"]
    assert found[0]["field"] == "name_JP"


def test_bad_format_finding():
    found = tl.findings("Skill.dat", [{"id": 3, "desc_JP": "boost %s"}])
    assert len(found) == 1 and found[0]["kind"] == "format"
    assert "%s" in found[0]["detail"]


def test_unknown_limit_is_not_a_finding():
    # magic.dat desc has no known buffer yet: only format is checked
    assert tl.findings("magic.dat", [{"id": 1, "desc_EN": "A" * 400}]) == []
    found = tl.findings("magic.dat", [{"id": 1, "desc_EN": "A" * 400 + " %d"}])
    assert [f["kind"] for f in found] == ["format"]


def test_magic_desc_wants_one_string_conversion():
    # vanilla magic.dat uses "Unique:%s..." (445 rows): one string argument
    assert tl.findings("magic.dat", [{"id": 1, "desc_EN": "Unique:%sSlash."}]) == []
    found = tl.findings("magic.dat", [{"id": 1, "desc_EN": "hit for %d"}])
    assert found and found[0]["severity"] == "display"


def test_severity_classes():
    assert tl.severity("length", "x") == "overflow"
    assert tl.severity("format", "see %s") == "crash"
    assert tl.severity("format", "2 %d") == "display"
    # the drawer's own over-limit crash is the overflow class
    f = tl.findings("Skill.dat", [{"id": 1, "desc_EN": "A" * 300}])
    assert f[0]["severity"] == "overflow"
    f = tl.findings("Skill.dat", [{"id": 1, "desc_EN": "%s"}])
    assert f[0]["severity"] == "crash"


def test_plain_text_name_may_contain_percent():
    # a name is drawn as a %s argument, not as a format: '%' is literal there
    assert tl.findings("Skill.dat", [{"id": 4, "name_EN": "100% Rage"}]) == []


def test_rows_may_be_id_field_pairs():
    found = tl.findings("Skill.dat", [(77, {"desc_EN": "x" * 300})])
    assert found and found[0]["id"] == 77


def test_non_string_values_ignored():
    assert tl.findings("Skill.dat", [{"id": 5, "value1": 50, "desc_EN": None}]) == []
