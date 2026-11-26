"""D4 idle timing / weapon positions (d5lib.d4idle).  Needs local D4 and D5 installs; skipped elsewhere."""
import os
import unittest

D4_ROOT = os.environ.get("D4_ROOT", "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 4 Complete+")
D5_ROOT = os.environ.get("D5_ROOT", "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")


@unittest.skipUnless(os.path.isdir(D4_ROOT) and os.path.isdir(D5_ROOT), "needs local D4 and D5 installs")
class D4IdleTests(unittest.TestCase):
    def test_idle_weapon_keys_follow_d4(self):
        from d5lib import anm, d4idle, d4source, rpgidle, sprites
        from d5lib.gamefs import GameFS
        fs = GameFS(D5_ROOT)
        template = anm.load(fs.read(sprites.sprite_vpath(fs, 1150, "EN")))     # D5 Armor Knight (back idle: param 17)
        d4 = d4source.D4Data(D4_ROOT).anm(1080)
        out, audit = d4idle.apply(template, d4, log=lambda *_: None)
        self.assertGreater(audit["weapon_keys"], 0)
        pb, db = out.blocks[0], d4.blocks[0]
        for aid, _ in d4idle.IDLES:
            _, an = d4idle._anim(out, aid)
            _, dan = d4idle._anim(d4, aid)
            d4n = {db.nodes[i].id: i for i, _, _ in db.walk(dan.root)}
            self.assertEqual(anm.animation_info(pb, an)["loop"], anm.animation_info(db, dan)["loop"])
            for i, _, _ in pb.walk(an.root):
                n = pb.nodes[i]
                if n.id not in d4idle.WEAPON_NODES or n.id not in d4n:
                    continue
                dks = db.node_keys(db.nodes[d4n[n.id]])
                for k in pb.node_keys(n):
                    src = rpgidle.key_at(dks, k.time)
                    if 0 <= src.param < len(db.params):                      # else the template value stays
                        self.assertEqual(pb.params[k.param], db.params[src.param], (aid, n.id, k.time))


if __name__ == "__main__":
    unittest.main()
