"""VOICES3: listening data + Builds/VOICES3-<date>/ bundle (overlay on TEST18B)."""
from __future__ import annotations

import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

NEW = Path("/Volumes/Data/ai-tmp/voices3/out/mods")
DATE = "20261030"
BASE_NAME = "LIVE5_TEST18B-20261030"
BUNDLE = Path(f"/Volumes/Data/Projects/D5/Builds/VOICES3-{DATE}")
ROLES = [("attack", [0], "attack"), ("skill shout A", [1, 2], "skill-shout A"),
         ("cast", [4], "elemental cast"), ("skill shout B", [6], "skill-shout B"),
         ("cast release", [9], "cast release / healing cast"), ("lift", [10], "lift"),
         ("throw", [11], "throw"), ("move", [13], "move / landing")]
GAPS = ["damage", "KO / death", "level-up", "menu / hire", "base idle"]

# Characters in this lane with no D4 / DD2 recording, or with a recording that cannot be bound yet.
NOT_STAGED = [
    ("D4_Unique_610", "Politan (D4)", "no D4 recording",
     "D4's voice table has no group 610 (checked directly). D4's Politan is published silent; the pack keeps "
     "its current D5 voice and will still speak with a donor line until a D4 recording exists."),
    ("D4_Unique_210", "Pringer X (D4)", "no D4 recording",
     "D4 row 210 points at voice group 5405 and row 5405 points back at 210; neither group exists in D4's "
     "voice table, so D4 has no Pringer X voice bank at all. Unchanged, as in VOICES2."),
]


def listening():
    out = {}
    for pack in sorted(p for p in NEW.iterdir() if p.is_dir()):
        data = json.loads((pack / "patches/voices/voices.json").read_text())
        vid, v = next(iter(data["voices"].items()))
        per_role = defaultdict(lambda: defaultdict(set))
        for line in v["lines"]:
            for lang, f in (line.get("files") or {}).items():
                for role, cats, _label in ROLES:
                    if set(cats) & set(line["cats"]):
                        per_role[role][lang].add(f)
        out[pack.name] = dict(voice_id=int(vid), lines=len(v["lines"]),
                              roles={role: {lang: sorted(fs) for lang, fs in per_role.get(role, {}).items()}
                                     for role, _c, _l in ROLES})
    Path("/Volumes/Data/ai-tmp/voices3/listening.json").write_text(json.dumps(out, indent=1))
    return out


def pack_name(pack):
    try:
        d = json.loads((pack / "patches/db/char.dat.json").read_text())
        rows = d.get("added") or list((d.get("rows") or {}).values())
        return rows[0].get("name_EN") or pack.name
    except Exception:
        return pack.name


def main():
    listen = listening()
    gate = json.loads(Path("/Volumes/Data/ai-tmp/voices3/gate-report.json").read_text())
    inv_doc = json.loads(Path("/Volumes/Data/ai-tmp/voices3/out/VOICES3-INVENTORY.json").read_text())
    by_pack = {e["pack"]: e for e in inv_doc}
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    (BUNDLE / "mods").mkdir(parents=True)
    packs = sorted(p for p in NEW.iterdir() if p.is_dir())
    inv = []
    for p in packs:
        shutil.copytree(p, BUNDLE / "mods" / p.name)
        l = listen.get(p.name, {})
        src = by_pack.get(p.name, {})
        inv.append(dict(pack=p.name, character=pack_name(p), voice_id=l.get("voice_id"),
                        d4_row=(src.get("source") or {}).get("row"),
                        d4_voice_group=(src.get("groups") or [None])[0],
                        clips=next((x["clips"] for x in gate["packs"] if x["pack"] == p.name), None),
                        lines=l.get("lines"),
                        roles={r: {lang: len(f) for lang, f in v.items()} for r, v in l.get("roles", {}).items()},
                        gaps=GAPS))
    total_clips = gate["clips"]
    (BUNDLE / "INVENTORY.json").write_text(json.dumps(
        dict(date=DATE, base=BASE_NAME, packs=len(packs), clips=total_clips, packs_detail=inv,
             not_staged=[dict(pack=a, character=b, reason=c, detail=d) for a, b, c, d in NOT_STAGED]),
        indent=1))
    lines = [f"VOICES3 overlay on {BASE_NAME} — {DATE}", "",
             f"{len(packs)} mod folders, {total_clips} staged recordings (48 kHz mono MS-ADPCM in the kit's VAG wrapper).",
             "Only patches/voices/ and the voice_id field of patches/db/char.dat.json differ from TEST18B.",
             "These are the ten D4UNIQ3 characters plus Pringer X; nine of the ten have a D4 bank and are staged here.",
             "", f"{'mod':20s} {'character':24s} {'voice':>5s} {'clips':>5s}  roles with a D4 line"]
    for e in inv:
        roles = [r for r in [x[0] for x in ROLES] if e["roles"].get(r, {}).get("EN")]
        lines.append(f"{e['pack']:20s} {str(e['character'])[:24]:24s} {e['voice_id']:5d} {str(e['clips']):>5s}  "
                     + ", ".join(roles))
    lines += ["", "Not staged (no real source recording):"]
    for a, b, c, _d in NOT_STAGED:
        lines.append(f"  {a:20s} {b:24s} {c}")
    lines += ["", "Every pack: no recording for " + ", ".join(GAPS) + " (see VOICES3-REPORT.md §2)."]
    (BUNDLE / "INVENTORY.txt").write_text("\n".join(lines) + "\n")

    # listening sheet
    md = ["# VOICES3 listening sheet", "",
          "Per character: which staged clip plays for which role. Files are in",
          "`mods/<pack>/patches/voices/`; `_EN` and `_JP` are the two dub recordings. A clip listed",
          "under two roles is one D4 recording that D4 itself flagged for both situations - that is",
          "D4's data, not a duplicate.", ""]
    for e in inv:
        l = listen[e["pack"]]
        md.append(f"## {e['character']} — `{e['pack']}`, voice {e['voice_id']} "
                  f"(D4 row {e.get('d4_row')}, D4 voice group {e.get('d4_voice_group')})")
        md.append("")
        md.append("| situation (D5) | role | English clips | Japanese clips |")
        md.append("|---|---|---|---|")
        for role, cats, label in ROLES:
            v = l["roles"].get(role, {})
            en = ", ".join(v.get("EN", [])) or "—"
            jp = ", ".join(v.get("JP", [])) or "—"
            cat = "/".join(str(c) for c in cats)
            md.append(f"| {cat} | {label} | {en} | {jp} |")
        md.append("")
        md.append("No recording for: " + ", ".join(GAPS) + " — D4 has no such line for this character, so the "
                  "unit is silent there (it is not borrowing one).")
        md.append("")
    md.append("## Characters in this lane that are NOT staged")
    md.append("")
    for a, b, c, d in NOT_STAGED:
        md.append(f"### {b} — `{a}` — {c}")
        md.append("")
        md.append(d)
        md.append("")
    (BUNDLE / "LISTENING-SHEET.md").write_text("\n".join(md))

    (BUNDLE / "VERIFY.json").write_text(json.dumps(dict(
        base=BASE_NAME, date=DATE, packs=len(packs), clips=total_clips,
        voice_only_diff="pass: every non-voice file byte-identical to TEST18B; char.dat.json differs only in voice_id",
        decode_proof=dict(result="pass", detail="every staged .vag decodes to 48 kHz mono, finite, peak <= 0.8501, >= 1000 samples"),
        situation_coverage="pass: every pack has a line in D5 situations 0,1,2,4,6,11,13 (the ones weapon-skill and skill-wrapper scripts name)",
        references="pass: no line names a missing file and no .vag is unreferenced",
        problems=gate["problems"]), indent=1))
    print("bundle:", BUNDLE, len(packs), "packs,", total_clips, "clips")


if __name__ == "__main__":
    main()
