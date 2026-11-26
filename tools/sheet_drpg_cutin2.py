#!/usr/bin/env python3
"""DRPGCUTIN2: one comparison sheet per look, every picture rendered from a BUILT bank by the kit's own renderer
(anm.render_frame of the portrait's animation 8000): the donor cut-in installed today, the new one (staged pack),
and a real cut-in of another character (the staged/rebuilt Higan base pack's own cut-in).  With STAGED_V1_MODS (the first staging, generic illustration
framing) the sheet shows donor | v1 | new | real for the looks whose cut-in changed since.

    python tools/sheet_drpg_cutin2.py INSTALLED_MODS STAGED_MODS REBUILT_MODS OUT_DIR [STAGED_V1_MODS]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw

from d5lib import anm

BANK = "files/Anime/ANM_HI_JP.dat/anm{:05d}.lzs"
LOOKS = [("60019", "Colossal Prinny (Blue)", "DRPG_Core_ColossalPrinnyBlue_60019", 27050),
         ("60021", "Colossal Prinny (Red)", "DRPG_Core_ColossalPrinnyBlue_60019", 27060),
         ("60025", "Dark Lord Valvolga", "DRPG_Core_DarkLordValvolga_60025", 27070),
         ("426", "Halloween Strategist Higan", "DRPG_Core_HiganZesshosai_222", 25850)]
CONTROL = ("DRPG_Core_HiganZesshosai_222", 25800, "real cut-in of another character (Higan 222, built bank)")


def render(path):
    return anm.render_frame(anm.load(str(path)), ("id", 8000), 0, 0).convert("RGBA")


def main(installed, staged, rebuilt, out, v1=None):
    installed, staged, rebuilt, out = map(Path, (installed, staged, rebuilt, out))
    v1 = Path(v1) if v1 else None
    out.mkdir(parents=True, exist_ok=True)
    ctl = render(rebuilt / CONTROL[0] / BANK.format(CONTROL[1]))
    for lid, name, pack, n in LOOKS:
        panels = [(f"donor cut-in installed today\n{pack} anm{n}", render(installed / pack / BANK.format(n))),
                  ] + ([("old (v1): generic 2.25x blow-up of chara/illust\nstaged v1 " + f"anm{n}", render(v1 / pack / BANK.format(n)))]
                       if v1 and lid != "426" else []) + [
                  (f"{'newer' if v1 and lid != '426' else 'new'}: made from the look's own art\nstaged {pack} anm{n}", render(staged / pack / BANK.format(n))),
                  (f"{CONTROL[2]}\nanm{CONTROL[1]}", ctl)]
        w, h = max(p.width for _, p in panels), max(p.height for _, p in panels)
        sheet = Image.new("RGB", (len(panels) * (w + 20) + 20, h + 100), (90, 90, 90))
        d = ImageDraw.Draw(sheet)
        d.text((20, 8), f"{name} (look {lid})", fill=(255, 255, 255))
        for i, (cap, im) in enumerate(panels):
            x = 20 + i * (w + 20)
            d.text((x, 30), cap, fill=(255, 255, 255))
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            bg.alpha_composite(im)
            sheet.paste(bg.convert("RGB"), (x, 90))
        sheet.save(out / f"{lid}_{name.replace(' ', '_').replace('(', '').replace(')', '')}.png")
        print("wrote", lid)


if __name__ == "__main__":
    main(*sys.argv[1:6])
