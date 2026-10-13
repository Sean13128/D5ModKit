"""Render a skill's animation with the kit's preview (no game): frames + a contact sheet, drawn exactly as the skill
editor's preview draws them (d5lib.stage + d5gui.skilledit.glrender on the GPU, the game camera, a battle map).

    python tools/render_skill.py SKILL OUTDIR [--caster=SPRITE] [--target=SPRITE] [--facing=0-3] [--dist=PANELS]
                                [--map=ID (0: flat floor)] [--panel=I,J] [--every=N] [--from=F] [--to=F]
                                [--frames=F1,F2,...] [--size=WxH] [--mod=FOLDER (one more mod, e.g. a scratch one)]
                                [--enemies=all|X,Y;X,Y...] [--no-area]

--dist: panels to the cursor (skills with a range) or to the target; --enemies: which of the skill's hit panels
hold an enemy (all, or x sideways / y forward from the caster; default: the first one); --no-area: don't draw
the skill's panels on the ground.

SKILL is a magic.dat id (the enabled mods' version of it) or a choreography event id (15xxxxxx).
Sprites may be a mod's own (looked up in the enabled mods).  Needs a real display driver with OpenGL 4.1 (no window
is shown); don't set QT_QPA_PLATFORM=offscreen.
"""
import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)
from d5lib import paths  # noqa: E402

from PyQt6.QtGui import QGuiApplication, QOpenGLContext, QOffscreenSurface, QSurfaceFormat, QImage, QPainter  # noqa
from PyQt6.QtGui import QColor, QFont  # noqa: E402
from PyQt6.QtOpenGL import (QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat,  # noqa: E402
                            QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile)

from d5lib import battlemap, choreo, modsys, particles, skillarea, skills, stage  # noqa: E402
from d5lib.gamefs import GameFS  # noqa: E402


def opt(name, default=None, cast=str):
    for a in sys.argv[3:]:
        if a.startswith(f"--{name}="):
            return cast(a.split("=", 1)[1])
        if a == f"--{name}":
            return True
    return default


def gl_context():
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create():
        sys.exit("no OpenGL 4.1 context")
    surf = QOffscreenSurface()
    surf.setFormat(ctx.format())
    surf.create()
    ctx.makeCurrent(surf)
    prof = QOpenGLVersionProfile()
    prof.setVersion(4, 1)
    prof.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    gl = QOpenGLVersionFunctionsFactory.get(prof, ctx)
    gl.initializeOpenGLFunctions()
    return ctx, surf, gl, prof            # all kept alive while drawing (Qt objects freed early crash)


def main():
    app = QGuiApplication(sys.argv)
    from d5gui.skilledit import glview              # needs the application
    skill, out = int(sys.argv[1]), sys.argv[2]
    os.makedirs(out, exist_ok=True)
    game = paths.require_game_dir()
    fs = GameFS(game, backup_resolver=modsys.Installer(game, KIT, log=lambda *a: None).backup_resolver)
    mods = modsys.ModManager(KIT).enabled_mods()
    if opt("mod"):
        mods.append(modsys.Mod(opt("mod")))
    sc = skills.with_mods(fs, mods)
    root = skill if skill >= skills.CHOREO_MIN else sc.root_of(skill)
    facing = opt("facing", 0, int)
    caster = opt("caster", 10, int)
    dist = opt("dist", 1.0, float)

    def owner_read(vp):
        for m in reversed(mods):
            if m.has_file(vp):
                return m.read_file(vp)
        return None
    sr = glview.StageRenderer(fs, mods, owner_read)
    mid = opt("map", battlemap.DEFAULT_MAP, int)
    sr.set_stage(mid or None, tuple(int(x) for x in opt("panel").split(",")) if opt("panel") else None)
    sr.caster_sprite, sr.target_sprite = caster, opt("target", 2010, int)
    sr.facing, sr.distance = facing, dist
    sr.show_area = not opt("no-area")
    if skill < skills.CHOREO_MIN:
        sr.area = skillarea.area_for(*skillarea.load_tables(fs.read, mods), skill)
        en = opt("enemies")
        if en == "all":
            sr.enemies = [(x, y) for x, y, k in sr.area.panels(sr.cursor()) if k != skillarea.USER_TO]
        elif en:
            sr.enemies = [tuple(int(v) for v in p.split(",")) for p in en.split(";")]
        print(skillarea.describe(sr.area), "· targets on", sr.target_panels())
    ctx = choreo.Context(loading=True, in_battle=tuple(s for s in (sr.caster_sprite, sr.target_sprite) if s))
    ctx.vars[60201] = facing
    ctx.vars[62199] = caster
    ctx.vars[64000] = sr.target_distance()
    ctx.vars.update(skillarea.target_vars(len(sr.target_panels())))
    tl = choreo.simulate(sc.ev, root, ctx)
    print(f"skill {skill} root {root}: {tl.length} frames")
    sr.particles = particles.ParticleSim(tl.ops)
    sim = sr.bind(tl)
    w, h = (int(x) for x in opt("size", "960x540").split("x"))
    gctx, surf, gl, prof = gl_context()
    ff = QOpenGLFramebufferObjectFormat()
    ff.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
    fbo = QOpenGLFramebufferObject(w, h, ff)
    fbo.bind()
    r = sr.gl
    every = opt("every", 6, int)
    frames = ([int(x) for x in opt("frames").split(",")] if opt("frames") else
              list(range(opt("from", 0, int), min(tl.length, opt("to", tl.length, int)) + 1, every)))
    files = []
    for f in frames:
        st = sim.at(f)
        r.paint(gl, w, h, st, stage.GameView(st, w / float(h)))
        p = os.path.join(out, f"f{f:04d}.png")
        fbo.toImage().convertToFormat(QImage.Format.Format_RGB32).save(p)
        files.append((f, p))
    fbo.release()
    gctx.doneCurrent()
    # frame numbers drawn afterwards: text painted while the GL context is current crashes Qt's collector
    for f, p in files:
        img = QImage(p)
        qp = QPainter(img)
        qp.setPen(QColor("#ffffff"))
        qp.setFont(QFont("Segoe UI", 10))
        qp.drawText(8, 18, f"frame {f}")
        qp.end()
        img.save(p)
    files = [p for _, p in files]
    cols = 4
    tw, th = w // 2, h // 2
    rows = (len(files) + cols - 1) // cols
    from PyQt6.QtCore import QRectF
    sheet = QImage(cols * tw, max(1, rows) * th, QImage.Format.Format_RGB32)
    sheet.fill(QColor("#000000"))
    qp = QPainter(sheet)
    for k, p in enumerate(files):
        qp.drawImage(QRectF(k % cols * tw, k // cols * th, tw, th), QImage(p))
    qp.end()
    sheet.save(os.path.join(out, "sheet.png"))
    print(len(files), "frames ->", out)


if __name__ == "__main__":
    main()
