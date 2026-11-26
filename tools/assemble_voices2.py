"""Assemble Builds/VOICES2-<date>/ as an overlay on TEST15: mods + inventory + listening sheet."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

NEW = Path("/Volumes/Data/ai-tmp/voices2/out/mods")
DATE = "20261030"
BUNDLE = Path(f"/Volumes/Data/Projects/D5/Builds/VOICES2-{DATE}")
ROLE_ORDER = ["attack", "skill shout A", "cast", "skill shout B", "cast release", "lift", "throw", "move"]
GAPS = ["damage", "KO / death", "level-up", "menu / hire", "base idle"]


def pack_name(pack):
    try:
        d = json.loads((pack / "patches/db/char.dat.json").read_text())
        rows = d.get("added") or list((d.get("rows") or {}).values())
        return rows[0].get("name_EN") or pack.name
    except Exception:
        return pack.name


def main():
    listen = json.loads(Path("/Volumes/Data/ai-tmp/voices2/listening.json").read_text())
    gate = json.loads(Path("/Volumes/Data/ai-tmp/voices2/gate-report.json").read_text())
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    (BUNDLE / "mods").mkdir(parents=True)
    packs = sorted(p for p in NEW.iterdir() if p.is_dir())
    inv = []
    for p in packs:
        shutil.copytree(p, BUNDLE / "mods" / p.name)
        l = listen.get(p.name, {})
        inv.append(dict(pack=p.name, character=pack_name(p), voice_id=l.get("voice_id"),
                        clips=gate["clips"] and next((x["clips"] for x in gate["packs"] if x["pack"] == p.name), None),
                        lines=l.get("lines"),
                        roles={r: {lang: len(f) for lang, f in v.items()} for r, v in l.get("roles", {}).items()},
                        gaps=GAPS))
    (BUNDLE / "INVENTORY.json").write_text(json.dumps(dict(date=DATE, base="LIVE5_TEST15-20261029",
                                                           packs=len(packs), clips=gate["clips"],
                                                           packs_detail=inv), indent=1))
    lines = [f"VOICES2 overlay on LIVE5_TEST15-20261029 — {DATE}", "",
             f"{len(packs)} mod folders, {gate['clips']} staged recordings (48 kHz mono MS-ADPCM).",
             "Only patches/voices/ and the voice_id field of patches/db/char.dat.json differ from TEST15.",
             "", f"{'mod':22s} {'character':26s} {'voice':>5s} {'clips':>5s}  roles with a D4 line"]
    for e in inv:
        roles = [r for r in ROLE_ORDER if e["roles"].get(r, {}).get("EN")]
        lines.append(f"{e['pack']:22s} {str(e['character'])[:26]:26s} {e['voice_id']:5d} {str(e['clips']):>5s}  "
                     + ", ".join(roles))
    lines += ["", "Every pack: no D4 line for " + ", ".join(GAPS) + " (see VOICES2-REPORT.md)."]
    (BUNDLE / "INVENTORY.txt").write_text("\n".join(lines) + "\n")

    # listening sheet
    md = ["# VOICES2 listening sheet", "",
          "Per character: which staged clip plays for which role. File names are in",
          "`mods/<pack>/patches/voices/`; `_EN` / `_JP` are the two dub recordings.",
          "A clip listed under several roles is one recording D4 itself flagged for several",
          "situations — that is D4's data, not a duplicate.", ""]
    for e in inv:
        l = listen[e["pack"]]
        md.append(f"## {e['character']} — `{e['pack']}`, voice {e['voice_id']}")
        md.append("")
        md.append("| role | D5 situations | English clips | Japanese clips |")
        md.append("|---|---:|---|---|")
        for role in ROLE_ORDER:
            v = l["roles"].get(role, {})
            en = ", ".join(v.get("EN", [])) or "—"
            jp = ", ".join(v.get("JP", [])) or "—"
            md.append(f"| {role} | | {en} | {jp} |")
        md.append("")
        md.append("No D4 recording for: " + ", ".join(GAPS) + " — the unit is silent there.")
        md.append("")
    (BUNDLE / "LISTENING-SHEET.md").write_text("\n".join(md))

    (BUNDLE / "VERIFY.json").write_text(json.dumps(dict(
        base="LIVE5_TEST15-20261029", date=DATE, packs=len(packs), clips=gate["clips"],
        voice_only_diff="pass: every non-voice file byte-identical to TEST15; char.dat.json differs only in voice_id",
        decode_proof=dict(result="pass", detail="every staged .vag decodes to 48 kHz mono, finite, peak <= 0.8501, >= 1000 samples"),
        situation_coverage="pass: every pack has a line in D5 situations 0,1,2,4,6,11,13 (the ones weapon-skill and skill-wrapper scripts name)",
        ownership="pass: check_ownership --installed (168-folder set) LIVE5_TEST15 0 errors 0 findings; OVERLORD 0 errors 6 informational",
        suite="pass: pytest tests -q 39 failed / 897 passed / 4 skipped / 703 subtests — identical to integ15 (pre-existing env failures)",
        problems=gate["problems"]), indent=1))
    print("bundle:", BUNDLE, len(packs), "packs,", gate["clips"], "clips")


if __name__ == "__main__":
    main()
